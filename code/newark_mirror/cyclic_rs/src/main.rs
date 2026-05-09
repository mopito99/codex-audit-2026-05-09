//! cyclic_rs daemon (Phase 1+2):
//!   Task A: Yellowstone subscriber → updates PoolRegistry on every account change.
//!   Task B: Shadow loop → on every tick scans for cycles, fetches p75 priority fee,
//!           applies R28 Q5 threshold formula, writes a ShadowRecord (R28 Q1 schema).
//! Phase 2 is paper-only — no transaction is ever submitted.

use anyhow::Result;
use cyclic_rs::{
    config::Config,
    cycle_finder::scan_best_cycle,
    grpc,
    priority_fee::{PriorityFeeCache, PriorityFeeConfig},
    shadow_logger::{build_record, ShadowLogger},
};
use solana_sdk::pubkey::Pubkey;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

// R74 Ventana 1 Fase 1.2 — Tokio worker_threads=8 (Gemma R74 v1 E.2 pick;
// see liquidator_rs/main.rs for rationale).
#[tokio::main(flavor = "multi_thread", worker_threads = 8)]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let cfg = Config::from_env()?;
    info!(?cfg.pools, log_path = %cfg.log_path, "cyclic_rs starting");

    let registry = grpc::new_registry();
    let logger = Arc::new(ShadowLogger::open(&cfg.log_path)?);
    let prio_cache = PriorityFeeCache::new(cfg.rpc_url.clone());
    let prio_config = PriorityFeeConfig::new();

    let probe_amount: u128 = std::env::var("CYCLIC_PROBE_BASE_UNITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1_000_000); // 1 USDC (6 decimals) default
    let interval_ms: u64 = std::env::var("CYCLIC_SCAN_INTERVAL_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(200);
    // Cycles starting in USDC: amount_in_usd = amount_in / 1e6.
    // For non-USDC inputs, this needs the per-pool decimals + price (R28 Q1
    // follow-up #3 — pending Gemma's snippet).
    let assumed_input_decimals: u32 = std::env::var("CYCLIC_INPUT_DECIMALS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(6);
    let cycle_path_tokens: Vec<String> = std::env::var("CYCLIC_PATH_TOKENS")
        .map(|s| s.split(',').map(str::trim).map(str::to_string).collect())
        .unwrap_or_else(|_| {
            vec!["USDC".into(), "SOL".into(), "USDC".into()]
        });

    let registry_b = registry.clone();
    let logger_b = logger.clone();
    let prio_cache_b = prio_cache.clone();
    let prio_config_b = prio_config;
    let pool_pubkeys: Vec<Pubkey> = cfg.pools.iter().map(|p| p.address).collect();

    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(interval_ms));
        let mut scans: u64 = 0;
        let mut quotes: u64 = 0;
        loop {
            interval.tick().await;
            scans += 1;

            let Some(quote) = scan_best_cycle(&registry_b, probe_amount) else {
                continue;
            };
            quotes += 1;

            // Latency: now() - max(updated_at) across the registry.
            let now_ms = chrono::Utc::now().timestamp_millis();
            let max_updated_ms = registry_b
                .iter()
                .map(|e| e.value().updated_at.timestamp_millis())
                .max()
                .unwrap_or(now_ms);
            let latency_ms = now_ms - max_updated_ms;

            let slot = registry_b
                .iter()
                .map(|e| e.value().slot)
                .max()
                .unwrap_or(0);

            let amount_in_usd =
                (quote.amount_in as f64) / 10f64.powi(assumed_input_decimals as i32);

            // R28 Q5: threshold = base + p75_per_cu * cu_estimate
            let p75 = prio_cache_b.get_p75(&pool_pubkeys).await.unwrap_or(0);
            let threshold_lamports = prio_config_b.calculate_threshold(p75);

            // would_send: net profit (in lamport-equivalent) > threshold.
            // For now we treat `net` (USDC base units) as roughly equivalent to
            // lamports for shadow gating — the proper conversion needs SOL price
            // (R28 Q1 follow-up #3 pending).
            let net_lamports_approx = quote.net;
            let would_send = net_lamports_approx > threshold_lamports as i128
                && !quote.stale_due_to_missing_ticks;

            let rec = build_record(
                &quote,
                slot,
                latency_ms,
                amount_in_usd,
                cycle_path_tokens.clone(),
                p75,
                threshold_lamports,
                would_send,
            );
            if let Err(e) = logger_b.write(&rec) {
                warn!(error=?e, "shadow log write failed");
            }
            if quotes % 200 == 0 {
                info!(scans, quotes, log = %logger_b.path().display(), "shadow stats");
            }
        }
    });

    let mut backoff_secs = 2u64;
    loop {
        match grpc::run(cfg.clone(), registry.clone()).await {
            Ok(()) => {
                info!("grpc::run returned Ok unexpectedly; restarting");
                backoff_secs = 2;
            }
            Err(e) => {
                error!(error=?e, "grpc::run failed; reconnecting in {}s", backoff_secs);
            }
        }
        tokio::time::sleep(Duration::from_secs(backoff_secs)).await;
        backoff_secs = (backoff_secs * 2).min(60);
    }
}
