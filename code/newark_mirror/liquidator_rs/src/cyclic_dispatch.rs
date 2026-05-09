//! Cyclic worker — receives CLMM pool account updates from the shared
//! Yellowstone gRPC stream, decodes them, scans for arb cycles, and writes
//! shadow log records.
//!
//! Architecture (R28 Q2 Option B per Gemma): the gRPC receive loop in `grpc.rs`
//! does only cheap dispatch (~1µs) by matching `SubscribeUpdate.filters` and
//! forwards CLMM updates to this worker via an unbounded mpsc channel. The
//! liquidator hot path (Kamino) runs unaffected.

use crate::circuit_breaker::CircuitBreaker;
use crate::priority_fee::FeeManager;
use crate::pyth_oracle::{evaluate_depeg_for_tier, PoolTier, PythCache};
use crate::stats::DaemonStats;
use crate::telemetry::Telemetry;
use crate::wallet::HotWallet;
use anyhow::Result;
use std::time::Instant as StdInstant;
use cyclic_rs::config::{PoolEntry, PoolKind};
use uuid::Uuid;
use cyclic_rs::cycle_finder::scan_best_cycle;
use cyclic_rs::pool_state::{decode, PoolState};
use cyclic_rs::priority_fee::PriorityFeeCache;
use cyclic_rs::shadow_logger::{build_record, ShadowLogger};
use dashmap::DashMap;
use solana_sdk::pubkey::Pubkey;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tracing::{info, warn};

#[derive(Debug)]
pub struct CyclicAccountUpdate {
    pub pubkey: Pubkey,
    pub data: Vec<u8>,
    pub slot: u64,
}

#[derive(Clone)]
pub struct CyclicConfig {
    pub pools: Vec<PoolEntry>,
    pub log_path: String,
    pub rpc_url: String,
    pub probe_base_units: u128,
    pub input_decimals: u32,
    pub cycle_path_tokens: Vec<String>,
    pub scan_interval_ms: u64,
    /// R64 A4.1 BLOCKING fix — per-pool tier from TOML registry. Used to
    /// dispatch evaluate_depeg_for_tier with the correct threshold (Major=40bps,
    /// MidCap=100bps, LongTail=200bps). Pubkey → PoolTier.
    pub tier_lookup: Arc<HashMap<Pubkey, PoolTier>>,
    /// R64 A4.1 — Pyth oracle cache (gRPC-fed) for depeg gating.
    pub pyth_cache: Arc<PythCache>,
    /// R64 A4.1 — Pyth feed pubkey for the cycle's intermediate token (e.g.
    /// PYTH_SOL_USD when cycle path is USDC→SOL→USDC). Required to evaluate
    /// the pool's mid-cycle price vs oracle. Empty/zero → depeg gate disabled.
    pub pyth_feed_intermediate: Pubkey,
    /// R64 A4.1 — Conversion factor for sqrt_price_x64 of leg0 to USD price of
    /// the intermediate token. For SOL/USDC (decimals 9 vs 6): 10^(9-6)=1000.
    pub price_decimal_adjustment: f64,
    /// R64 A4.1 — Max staleness in seconds before oracle is considered Stale.
    pub oracle_max_staleness_secs: u64,
    /// R65 C.3 BLOCKING fix — isolated wallet for cyclic execute path. Loaded
    /// from LIQ_CYCLIC_WALLET_PRIVATE_KEY (e.g. hot200 $200 probe wallet).
    /// MANDATORY when LIQ_CYCLIC_EXECUTE_LIVE=true; warning-only otherwise
    /// (shadow mode). Master wallet WALLET_PRIVATE_KEY is NEVER used by the
    /// cyclic execute path — blast radius isolation per Gemma R64 B4.
    pub cyclic_wallet: Option<Arc<HotWallet>>,
}

pub fn spawn_worker(
    cfg: CyclicConfig,
    current_slot: Arc<AtomicU64>,
    fee_manager: Arc<FeeManager>,
    circuit_breaker: Arc<CircuitBreaker>,
    stats: Arc<DaemonStats>,
    telemetry: Arc<Telemetry>,
) -> Result<mpsc::Sender<CyclicAccountUpdate>> {
    // R74 Ventana 2 Fase 2 (Path C, Gemma R74 v3) — bounded channel.
    // unbounded → memory risk during Geyser bursts; bounded(1000) implements
    // back-pressure (R72 Q1.a) without dragging in crossbeam (sync) or flume.
    // Channel capacity 1000 = middle ground per Gemma constraint #1.
    // R65 C.3 BLOCKING — log isolated wallet status at startup so operators
    // can verify blast radius is preserved. Loud warn if cyclic_wallet=None
    // (shadow-only is allowed but make it impossible to miss).
    let live_execute = std::env::var("LIQ_CYCLIC_EXECUTE_LIVE")
        .map(|v| v == "true")
        .unwrap_or(false);
    match (&cfg.cyclic_wallet, live_execute) {
        (Some(w), true) => {
            info!(
                cyclic_wallet = %w.pubkey,
                "R65 C.3: cyclic execute path will sign with isolated wallet (LIVE mode)"
            );
        }
        (Some(w), false) => {
            info!(
                cyclic_wallet = %w.pubkey,
                "R65 C.3: cyclic isolated wallet loaded but LIQ_CYCLIC_EXECUTE_LIVE=false → shadow mode"
            );
        }
        (None, true) => {
            anyhow::bail!(
                "R65 C.3 BLOCKING: LIQ_CYCLIC_EXECUTE_LIVE=true requires \
                 LIQ_CYCLIC_WALLET_PRIVATE_KEY set. Master wallet must NEVER \
                 sign cyclic txs (Gemma R64 B4 blast radius isolation)."
            );
        }
        (None, false) => {
            warn!(
                "R65 C.3: cyclic isolated wallet NOT loaded \
                 (LIQ_CYCLIC_WALLET_PRIVATE_KEY missing). Shadow mode only — \
                 setting LIQ_CYCLIC_EXECUTE_LIVE=true will refuse to start."
            );
        }
    }

    // R74 Ventana 2 Fase 2 — bounded(1000) per Gemma R74 v3 Path C.
    let (tx, mut rx) = mpsc::channel::<CyclicAccountUpdate>(1000);
    let registry: Arc<DashMap<Pubkey, PoolState>> = Arc::new(DashMap::new());
    let logger = Arc::new(ShadowLogger::open(&cfg.log_path)?);
    let prio_cache = PriorityFeeCache::new(cfg.rpc_url.clone());

    let pool_lookup: HashMap<Pubkey, (String, PoolKind)> = cfg
        .pools
        .iter()
        .map(|p| (p.address, (p.label.clone(), p.kind)))
        .collect();
    let pool_pubkeys: Vec<Pubkey> = cfg.pools.iter().map(|p| p.address).collect();

    // Decoder task — drains the channel and updates the registry
    let registry_d = registry.clone();
    let pool_lookup_d = pool_lookup.clone();
    let stats_d = stats.clone();
    let telemetry_d = telemetry.clone();
    tokio::spawn(async move {
        let mut decoded_ok: u64 = 0;
        let mut decoded_err: u64 = 0;
        while let Some(update) = rx.recv().await {
            // R49 C4 — recv'd one item, channel depth drops by 1.
            telemetry_d.dec_pending();
            telemetry_d.inc_updates();

            let Some((label, kind)) = pool_lookup_d.get(&update.pubkey).cloned() else {
                continue;
            };
            // R49 C4 — measure decode + registry insert.
            let t0 = StdInstant::now();
            match decode(update.pubkey, &label, kind, &update.data, update.slot) {
                Ok(state) => {
                    decoded_ok += 1;
                    stats_d.cyclic_decoded_ok.fetch_add(1, Ordering::Relaxed);
                    registry_d.insert(update.pubkey, state);
                    stats_d
                        .pool_count
                        .store(registry_d.len(), Ordering::Relaxed);
                    let elapsed_ms = t0.elapsed().as_millis() as u64;
                    telemetry_d.record_decode_to_registry(elapsed_ms);
                    if decoded_ok % 500 == 0 {
                        info!(decoded_ok, decoded_err, "cyclic decode stats");
                    }
                }
                Err(e) => {
                    decoded_err += 1;
                    stats_d.cyclic_decoded_err.fetch_add(1, Ordering::Relaxed);
                    warn!(error=?e, %update.pubkey, "cyclic decode failed");
                }
            }
        }
    });

    // Shadow scan task
    let registry_s = registry.clone();
    let logger_s = logger.clone();
    let prio_cache_s = prio_cache.clone();
    let cfg_s = cfg.clone();
    let current_slot_s = current_slot.clone();
    let fee_manager_s = fee_manager.clone();
    let circuit_breaker_s = circuit_breaker.clone();
    let stats_s = stats.clone();
    let telemetry_s = telemetry.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(cfg_s.scan_interval_ms));
        let mut scans: u64 = 0;
        let mut quotes: u64 = 0;
        loop {
            interval.tick().await;
            // R49 C4 — measure full scan tick duration.
            let scan_start = StdInstant::now();
            scans += 1;
            stats_s.cyclic_scans.fetch_add(1, Ordering::Relaxed);

            // R31 Q2 + R34 Q1: feed slot_lag to circuit breaker every tick.
            let cur_slot = current_slot_s.load(Ordering::Relaxed);
            let max_pool_slot = registry_s.iter().map(|e| e.value().slot).max().unwrap_or(0);
            let slot_lag = if max_pool_slot == 0 { 0 } else { cur_slot.saturating_sub(max_pool_slot) };
            circuit_breaker_s.check_slot_lag(slot_lag);
            stats_s.last_slot_lag.store(slot_lag, Ordering::Relaxed);
            stats_s
                .circuit_breaker_tripped
                .store(circuit_breaker_s.is_tripped(), Ordering::Relaxed);

            let Some(quote) = scan_best_cycle(&registry_s, cfg_s.probe_base_units) else {
                continue;
            };
            quotes += 1;
            stats_s.cyclic_quotes.fetch_add(1, Ordering::Relaxed);

            let now_ms = chrono::Utc::now().timestamp_millis();
            let max_updated_ms = registry_s
                .iter()
                .map(|e| e.value().updated_at.timestamp_millis())
                .max()
                .unwrap_or(now_ms);
            let latency_ms = now_ms - max_updated_ms;
            let amount_in_usd =
                (quote.amount_in as f64) / 10f64.powi(cfg_s.input_decimals as i32);

            // R34 Q2 tip-laddering: priority_fee (leader) + jito_tip (validator).
            let p75 = prio_cache_s.get_p75(&pool_pubkeys).await.unwrap_or(0);
            let (priority_fee, jito_tip) = fee_manager_s.get_execution_fees(p75);
            let total_cost_lamports = priority_fee.saturating_add(jito_tip);

            // R35 Q0 — USD-based comparison. Convert SOL lamports to USD using the
            // pool sqrt_price; convert USDC base units to USD via decimals.
            // raw_p = (sqrt_p_x64 / 2^64)^2 = token_b_base / token_a_base ratio
            // price = raw_p × price_decimal_adjustment (1000 for SOL/USDC: 10^(9-6))
            let sqrt_p_norm = quote.sqrt_price_0 as f64 / 2f64.powi(64);
            let price_sol_usdc = sqrt_p_norm * sqrt_p_norm * cfg_s.price_decimal_adjustment;
            let total_cost_usd = (total_cost_lamports as f64 * 1e-9) * price_sol_usdc;
            let net_profit_usd = quote.net as f64 / 10f64.powi(cfg_s.input_decimals as i32);

            // R64 A4.1 + R65 C.1 BLOCKING fix — Pyth depeg gate per-tier.
            // R65 C.1 (Gemma): use the STRICTEST (lowest bps threshold) tier
            // among ALL legs in the cycle. If any leg is Major (40bps), the
            // tighter gate must apply. Previous version only checked leg0 →
            // a depeg on leg1 could pass un-gated.
            // Si Pyth feed pubkey == default (todo cero) → gate desactivado (sin pyth subscribe).
            let depeg_blocked = if cfg_s.pyth_feed_intermediate != Pubkey::default() {
                let tier_leg0 = cfg_s
                    .tier_lookup
                    .get(&quote.leg0_pool)
                    .copied()
                    .unwrap_or(PoolTier::LongTail);
                let tier_leg1 = cfg_s
                    .tier_lookup
                    .get(&quote.leg1_pool)
                    .copied()
                    .unwrap_or(PoolTier::LongTail);
                // Strictest = lowest depeg_threshold_bps.
                let tier = if tier_leg0.depeg_threshold_bps()
                    <= tier_leg1.depeg_threshold_bps()
                {
                    tier_leg0
                } else {
                    tier_leg1
                };
                let oracle = cfg_s.pyth_cache.get(&cfg_s.pyth_feed_intermediate);
                let now_unix = chrono::Utc::now().timestamp();
                let status = evaluate_depeg_for_tier(
                    price_sol_usdc,
                    oracle.as_ref(),
                    now_unix,
                    tier,
                    cfg_s.oracle_max_staleness_secs,
                );
                if status.should_trip() {
                    stats_s.cyclic_depeg_skipped.fetch_add(1, Ordering::Relaxed);
                    if quotes % 50 == 0 {
                        warn!(
                            ?status, ?tier, pool = %quote.leg0_pool,
                            pool_price = price_sol_usdc,
                            oracle_price = oracle.as_ref().map(|o| o.price_usd).unwrap_or(0.0),
                            "R64 A4.1 depeg gate blocked would_send"
                        );
                    }
                    true
                } else {
                    false
                }
            } else {
                false
            };

            // R31 Q2 + R34 Q1 + R35 Q0: would_send needs USD-corrected profit >
            // USD-corrected cost AND fresh data AND circuit breaker not tripped
            // AND R64 A4.1 Pyth depeg gate.
            // R74 V3 — capturar el estado de cada gate ANTES de combinar (para
            // que el JSONL grabe las causas reales del rechazo, no la composición).
            let cb_blocked_now = !circuit_breaker_s.is_allowed();
            let would_send = net_profit_usd > total_cost_usd
                && !quote.stale_due_to_missing_ticks
                && slot_lag <= 2
                && !cb_blocked_now
                && !depeg_blocked;

            // R48 C3 — generate UUID v4 only when this is an actionable opportunity.
            let bundle_id = if would_send {
                Some(Uuid::new_v4().to_string())
            } else {
                None
            };

            stats_s
                .last_jito_tip_lamports
                .store(jito_tip, Ordering::Relaxed);

            let rec = build_record(
                &quote,
                max_pool_slot,
                latency_ms,
                slot_lag,
                amount_in_usd,
                cfg_s.cycle_path_tokens.clone(),
                p75,
                priority_fee,
                jito_tip,
                total_cost_lamports,
                net_profit_usd,
                total_cost_usd,
                would_send,
                bundle_id,
                cb_blocked_now,        // R74 V3 Visibility
                depeg_blocked,         // R74 V3 Visibility
            );
            // R49 C4 — measure quote→record (build_record + JSONL write).
            let q2r_start = StdInstant::now();
            if let Err(e) = logger_s.write(&rec) {
                warn!(error=?e, "cyclic shadow log write failed");
            }
            telemetry_s.record_quote_to_record(q2r_start.elapsed().as_millis() as u64);

            // R49 C4 — full scan tick duration.
            telemetry_s.record_scan_duration(scan_start.elapsed().as_millis() as u64);

            if quotes % 200 == 0 {
                info!(scans, quotes, "cyclic shadow stats");
            }
        }
    });

    Ok(tx)
}
