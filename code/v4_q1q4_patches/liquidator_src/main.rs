//! liquidator_rs main daemon — Yellowstone gRPC subscriber + simulator dispatcher.

use anyhow::{Context, Result};
use std::str::FromStr;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{info, warn};

mod grpc;

use liquidator_rs::{
    circuit_breaker::CircuitBreaker,
    config::Config,
    cyclic_dispatch::{spawn_worker, CyclicConfig},
    logger,
    priority_fee::{FeeManager, PriorityFeeConfig},
    rpc, tip_stream, wallet,
};
use cyclic_rs::config::PoolEntry;
use solana_sdk::pubkey::Pubkey;

// R74 Ventana 1 Fase 1.2 — Tokio worker_threads=8 (Gemma R74 v1 E.2 pick).
// Newark = 32c/64t. Más hilos ≠ más velocidad en HFT: contención cache L3 +
// context-switching. 8 hilos para runtime, resto del CPU libre para gRPC/TCP
// stack y procesos auxiliares.
#[tokio::main(flavor = "multi_thread", worker_threads = 8)]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info,liquidator_rs=debug")),
        )
        .init();

    let cfg = Config::from_env().context("loading config")?;
    let rpc_url = std::env::var("LIQ_RPC_URL")
        .or_else(|_| std::env::var("CHAINSTACK_RPC_URL"))
        .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".to_string());
    let rpc_client = Arc::new(rpc::RpcClient::new(rpc_url.clone()));

    let wallet = Arc::new(wallet::HotWallet::from_env()
        .context("wallet load failed (set WALLET_PRIVATE_KEY in .env)")?);

    info!(
        grpc = %cfg.grpc_url,
        rpc = %rpc_url,
        kamino_program = %cfg.kamino_program_id,
        wallet = %wallet.pubkey,
        "liquidator_rs M1 starting"
    );

    let logger = Arc::new(Mutex::new(logger::JsonlLogger::open(&cfg.log_path)?));
    // Liquidator status writer — refresh stats.json every 10s for dashboard
    {
        let live_mode = std::env::var("LIQ_LIVE_MODE").map(|v| v == "true").unwrap_or(false);
        let wallet_pk = wallet.pubkey;
        // r116 Item #2: capture configurable risk params (was hardcoded 200/2/5M)
        let max_debt_cap_usd = cfg.max_debt_cap_usd;
        let min_profit_usd = cfg.min_profit_usd;
        let max_tip_lamports = cfg.max_tip_lamports;
        tokio::spawn(async move {
            let stats_path = std::path::PathBuf::from("/home/ubuntu/liquidator_rs/data/stats.json");
            loop {
                let live_attempts_path = std::path::PathBuf::from("/home/ubuntu/liquidator_rs/data/live_attempts.jsonl");
                let attempts_count = std::fs::read_to_string(&live_attempts_path)
                    .map(|s| s.lines().count())
                    .unwrap_or(0);
                let unhealthy_path = std::path::PathBuf::from("/home/ubuntu/liquidator_rs/data/unhealthy_positions.jsonl");
                let unhealthy_count = std::fs::read_to_string(&unhealthy_path)
                    .map(|s| s.lines().count())
                    .unwrap_or(0);
                let stats = serde_json::json!({
                    "updated_at": chrono::Utc::now().to_rfc3339(),
                    "live_mode": live_mode,
                    "wallet": wallet_pk.to_string(),
                    "max_debt_cap_usd": max_debt_cap_usd,
                    "min_profit_usd": min_profit_usd,
                    "max_tip_lamports": max_tip_lamports,
                    "unhealthy_detected_total": unhealthy_count,
                    "live_attempts_total": attempts_count
                });
                let _ = std::fs::write(&stats_path, serde_json::to_string_pretty(&stats).unwrap());
                tokio::time::sleep(std::time::Duration::from_secs(10)).await;
            }
        });
    }


    // R31 Q2: shared current-slot atomic, written by gRPC slot subscription
    // and read by the cyclic worker for slot_lag.
    let current_slot = std::sync::Arc::new(std::sync::atomic::AtomicU64::new(0));

    // R34 Q2: tip-laddering — Jito public tip_floor stream + FeeManager.
    let tip_stream = Arc::new(liquidator_rs::tip_stream::TipStream::new());
    tip_stream::spawn(tip_stream.handle(), rpc_url.clone());
    let fee_manager = Arc::new(FeeManager::new(
        PriorityFeeConfig::default(),
        tip_stream.clone(),
    ));

    // R34 Q1: shared circuit breaker (slot_lag warnings + execution-failure trip).
    let circuit_breaker = Arc::new(CircuitBreaker::new(10));
    // r122 firma Gemma — spawn endpoint /cb/status localhost:9090 (lock-free)
    liquidator_rs::cb_status_server::spawn_cb_status_server(circuit_breaker.clone());

    // R49 C4 — telemetry + background monitor (auto-trip CB on backlog/stall).
    let telemetry = Arc::new(liquidator_rs::telemetry::Telemetry::new());
    liquidator_rs::telemetry::spawn_telemetry_monitor(
        telemetry.clone(),
        circuit_breaker.clone(),
    );

    // R62 A4 + Principio #1: PythCache early init (necesario para SafetyWorker
    // que lo consume + grpc.rs que lo populó vía push gRPC).
    let pyth_cache_early = Arc::new(liquidator_rs::pyth_oracle::PythCache::new());

    // R59 Pieza 5 wire-up — SafetyWorker EVENT-DRIVEN (R62 audit A3).
    // Detection → mpsc channel → orchestrator trip CB.
    // Sin polling externo. Sin race conditions.
    if std::env::var("LIQ_SAFETY_WORKER_ENABLE").map(|v| v == "true").unwrap_or(false) {
        let safety_cfg = liquidator_rs::safety_worker::SafetyConfig::default_for(wallet.pubkey);
        let worker = liquidator_rs::safety_worker::SafetyWorker::new(safety_cfg);
        let (alert_tx, mut alert_rx) = tokio::sync::mpsc::unbounded_channel::<
            liquidator_rs::safety_worker::SafetyAlert
        >();
        let pyth_cache = pyth_cache_early.clone();

        // Spawn worker run loop with event channel
        // R62 wire-up: real HTTP RPC fetch via wallet_query module.
        // SafetyWorker NO está en hot path → HTTP es válido (Principio #1).
        let worker_clone = worker.clone();
        let alert_tx_clone = alert_tx.clone();
        let rpc_url_for_safety = rpc_url.clone();
        let wallet_pk_for_safety = wallet.pubkey;
        let pyth_cache_for_safety = pyth_cache.clone();
        tokio::spawn(async move {
            let url = rpc_url_for_safety.clone();
            let wallet_pk = wallet_pk_for_safety;
            let pyth = pyth_cache_for_safety;
            let fetch = move || {
                let url = url.clone();
                let pyth = pyth.clone();
                async move {
                    // Build price_map dynamically from PythCache snapshot.
                    let mut price_map = std::collections::HashMap::new();
                    // SOL → SOL/USD feed
                    if let Ok(sol_mint) = "So11111111111111111111111111111111111111112"
                        .parse::<solana_sdk::pubkey::Pubkey>()
                    {
                        if let Ok(sol_feed) = liquidator_rs::pyth_oracle::PYTH_SOL_USD
                            .parse::<solana_sdk::pubkey::Pubkey>()
                        {
                            if let Some(p) = pyth.get(&sol_feed) {
                                price_map.insert(sol_mint, p.price_usd);
                            }
                        }
                    }
                    // USDC → $1 (whitelist anyway, value irrelevant)
                    if let Ok(usdc) = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        .parse::<solana_sdk::pubkey::Pubkey>()
                    {
                        price_map.insert(usdc, 1.0);
                    }
                    if let Ok(usdt) = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
                        .parse::<solana_sdk::pubkey::Pubkey>()
                    {
                        price_map.insert(usdt, 1.0);
                    }
                    liquidator_rs::wallet_query::fetch_wallet_tokens_priced(
                        &url, &wallet_pk, &price_map,
                    ).await
                }
            };
            worker_clone.run(fetch, alert_tx_clone).await;
        });

        // Spawn orchestrator: receives alerts → trips CB on TokenDetected
        let cb_for_safety = circuit_breaker.clone();
        tokio::spawn(async move {
            while let Some(alert) = alert_rx.recv().await {
                use liquidator_rs::safety_worker::SafetyAlert;
                match alert {
                    SafetyAlert::TokenDetected { flagged_tokens, total_value_usd, .. } => {
                        tracing::error!(
                            n_tokens = flagged_tokens.len(),
                            total_value_usd,
                            "🚨 R62 A3 event-driven: SafetyWorker emergency → tripping CB(WalletDrain)"
                        );
                        cb_for_safety.trip(
                            liquidator_rs::circuit_breaker::TripReason::WalletDrain
                        );
                        // TODO: spawn emergency Jupiter sell here (decoupled R61 Q6)
                    }
                    SafetyAlert::StateChanged { from, to, .. } => {
                        tracing::info!(?from, ?to, "SafetyWorker state changed");
                    }
                    SafetyAlert::Heartbeat { n_tokens_observed, .. } => {
                        tracing::debug!(n_tokens_observed, "SafetyWorker heartbeat OK");
                    }
                }
            }
            tracing::warn!("SafetyWorker alert channel closed");
        });

        info!("R59/R62 Pieza 5: SafetyWorker spawned event-driven (stub fetch)");
    }

    // R62 A4 + Principio #1: PythOracle wire-up via gRPC push (NO HTTP poll).
    // Latencia ~10-30ms vs HTTP ~1.97s peor caso. Pyth pubkeys se añaden al
    // SubscribeRequest existente — coste cero, multiplexa la conexión actual.
    let pyth_addrs: Vec<String> = if std::env::var("LIQ_PYTH_ORACLE_ENABLE")
        .map(|v| v == "true").unwrap_or(false)
    {
        let feeds = liquidator_rs::pyth_oracle::default_pyth_feeds()
            .unwrap_or_default();
        let addrs: Vec<String> = feeds.values().map(|p| p.to_string()).collect();
        info!(
            n_feeds = addrs.len(),
            "R62 A4: PythOracle subscribed via gRPC push (cero HTTP poll)"
        );
        addrs
    } else {
        Vec::new()
    };
    let pyth_cache_for_grpc = if pyth_addrs.is_empty() {
        None
    } else {
        Some(pyth_cache_early.clone())
    };

    // R67 (c1) per Gemma: Pyth V1 push oracle decommissioned ~14 months ago.
    // gRPC subscription stays as no-op (V1 accounts dead) but we ALSO spawn
    // a Hermes HTTP poller that populates PythCache using V1 pubkeys as keys.
    // The depeg gate code is unchanged — same cache lookup, just fed by HTTP.
    if std::env::var("LIQ_PYTH_ORACLE_ENABLE")
        .map(|v| v == "true")
        .unwrap_or(false)
    {
        liquidator_rs::pyth_hermes::spawn_poller(pyth_cache_early.clone());
    }

    // R48 — DaemonStats for /bot_stats command + observability.
    let stats = Arc::new(liquidator_rs::stats::DaemonStats::new(telemetry.clone()));


    // ---- Cyclic ARB (R28 Q2) — second filter on the same gRPC stream ----
    // R64 A2.3 BLOCKING fix — Force TOML config. CYCLIC_POOLS env legacy path REMOVED.
    // R64 A4.1 BLOCKING fix — pyth_cache + tier_lookup wired into cyclic worker.
    // R65 C.3 BLOCKING fix — isolated wallet (LIQ_CYCLIC_WALLET_PRIVATE_KEY)
    // for cyclic execute path, NEVER reuses master WALLET_PRIVATE_KEY.
    let cyclic_wallet: Option<Arc<liquidator_rs::wallet::HotWallet>> =
        match liquidator_rs::wallet::HotWallet::from_env_var("LIQ_CYCLIC_WALLET_PRIVATE_KEY") {
            Ok(w) => {
                if w.pubkey == wallet.pubkey {
                    anyhow::bail!(
                        "R65 C.3: LIQ_CYCLIC_WALLET_PRIVATE_KEY must be DIFFERENT \
                         from master WALLET_PRIVATE_KEY. Pubkeys match: {}",
                        w.pubkey
                    );
                }
                info!(cyclic_pubkey = %w.pubkey, master_pubkey = %wallet.pubkey,
                      "R65 C.3: cyclic isolated wallet loaded (pubkey != master)");
                Some(Arc::new(w))
            }
            Err(_) => None,
        };

    let (cyclic_tx, cyclic_pool_addrs) =
        match build_cyclic(
            &rpc_url,
            current_slot.clone(),
            fee_manager.clone(),
            circuit_breaker.clone(),
            stats.clone(),
            telemetry.clone(),
            pyth_cache_early.clone(),
            cyclic_wallet,
        ) {
            Ok(Some((tx, addrs))) => (Some(tx), addrs),
            Ok(None) => {
                info!("cyclic disabled (LIQ_POOL_REGISTRY_TOML not set)");
                (None, Vec::new())
            }
            Err(e) => {
                warn!(error=?e, "cyclic init failed; running Kamino-only");
                (None, Vec::new())
            }
        };

    grpc::run(
        cfg, logger, rpc_client, wallet,
        cyclic_tx, cyclic_pool_addrs,
        current_slot,
        telemetry,
        pyth_cache_for_grpc,
        pyth_addrs,
    ).await?;
    Ok(())
}

/// R64 A2.3 BLOCKING fix — Build the cyclic worker from TOML registry only.
/// Returns (tx, pool_addrs) on success, None when LIQ_POOL_REGISTRY_TOML is not
/// set (cyclic disabled), Err on misconfiguration. Legacy CYCLIC_POOLS env path
/// is REMOVED — TOML is the single source of truth.
///
/// R64 A4.1 BLOCKING fix — wires pyth_cache + per-pool tier_lookup so that
/// cyclic_dispatch can call evaluate_depeg_for_tier with the right threshold
/// (Major=40bps, MidCap=100bps, LongTail=200bps) per quote.
fn build_cyclic(
    rpc_url: &str,
    current_slot: std::sync::Arc<std::sync::atomic::AtomicU64>,
    fee_manager: Arc<FeeManager>,
    circuit_breaker: Arc<CircuitBreaker>,
    stats: Arc<liquidator_rs::stats::DaemonStats>,
    telemetry: Arc<liquidator_rs::telemetry::Telemetry>,
    pyth_cache: Arc<liquidator_rs::pyth_oracle::PythCache>,
    cyclic_wallet: Option<Arc<liquidator_rs::wallet::HotWallet>>,
// R74 Ventana 2 Fase 2 (Path C) — bounded Sender (was UnboundedSender).
) -> Result<Option<(tokio::sync::mpsc::Sender<liquidator_rs::cyclic_dispatch::CyclicAccountUpdate>, Vec<String>)>> {
    let toml_path = match std::env::var("LIQ_POOL_REGISTRY_TOML") {
        Ok(s) if !s.trim().is_empty() => s,
        _ => {
            // R64 A2.3: legacy CYCLIC_POOLS path removed; if user still has it set,
            // refuse to start instead of silently falling back to a config-less path.
            if std::env::var("CYCLIC_POOLS").is_ok() {
                anyhow::bail!(
                    "R64 A2.3: legacy CYCLIC_POOLS env var is no longer supported. \
                     Set LIQ_POOL_REGISTRY_TOML to a pools.toml path instead."
                );
            }
            return Ok(None);
        }
    };

    let registry = liquidator_rs::pool_registry::PoolRegistry::load_from_toml(&toml_path)
        .with_context(|| format!("loading pool registry TOML from {toml_path}"))?;
    let snapshot = registry.snapshot();

    if snapshot.pools.is_empty() {
        anyhow::bail!("pool registry {toml_path} has zero enabled pools");
    }

    // Build PoolEntry list (compat with cyclic_rs::config) + tier_lookup map.
    let mut pools: Vec<PoolEntry> = Vec::with_capacity(snapshot.pools.len());
    let mut tier_lookup: std::collections::HashMap<Pubkey, liquidator_rs::pyth_oracle::PoolTier> =
        std::collections::HashMap::with_capacity(snapshot.pools.len());
    for p in snapshot.pools.iter() {
        pools.push(PoolEntry {
            label: p.label.clone(),
            address: p.address,
            kind: p.kind,
        });
        tier_lookup.insert(p.address, p.tier);
    }
    let pool_addrs: Vec<String> = pools.iter().map(|p| p.address.to_string()).collect();

    // R64 A4.1: Pyth feed for the intermediate token of the cycle. With cycle
    // path USDC→SOL→USDC, the intermediate is SOL; subscribe PYTH_SOL_USD.
    // If LIQ_PYTH_ORACLE_ENABLE is off, the gate auto-disables (Pubkey::default()).
    let pyth_enabled = std::env::var("LIQ_PYTH_ORACLE_ENABLE")
        .map(|v| v == "true")
        .unwrap_or(false);
    let pyth_feed_intermediate = if pyth_enabled {
        Pubkey::from_str(liquidator_rs::pyth_oracle::PYTH_SOL_USD)
            .context("parsing PYTH_SOL_USD constant")?
    } else {
        warn!("R64 A4.1: LIQ_PYTH_ORACLE_ENABLE=false → cyclic depeg gate DISABLED (would_send not protected by oracle)");
        Pubkey::default()
    };

    // Allow operators to override per-deployment via env, default TOML-driven.
    let log_path = std::env::var("CYCLIC_LOG_PATH")
        .unwrap_or_else(|_| "/home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl".into());
    let probe_base_units: u128 = (snapshot.global.probe_usd * 1e6) as u128;
    let input_decimals: u32 = std::env::var("CYCLIC_INPUT_DECIMALS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(6);
    let oracle_max_staleness_secs: u64 = std::env::var("LIQ_PYTH_MAX_STALENESS_SECS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(30);
    // SOL/USDC: 10^(9-6) = 1000. Configurable for non-SOL pools later.
    let price_decimal_adjustment: f64 = std::env::var("CYCLIC_PRICE_DECIMAL_ADJUSTMENT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1000.0);

    // r144 firma Gemma Q1 — leer envs del profit floor dinámico.
    // El boot fail-safe en config.rs ya validó (anyhow::bail!) que si
    // LIVE flag está activo entonces LIVE floor >= 1.00. Aquí solo
    // recomputamos el effective sin re-validar.
    let q1_live_flag = std::env::var("LIQ_CYCLIC_EXECUTE_LIVE")
        .map(|v| v == "true" || v == "1")
        .unwrap_or(false);
    let q1_floor_shadow: f64 = std::env::var("LIQ_MIN_PROFIT_USD_SHADOW")
        .unwrap_or_else(|_| "0.10".into())
        .parse()
        .unwrap_or(0.10);
    let q1_floor_live: f64 = std::env::var("LIQ_MIN_PROFIT_USD_LIVE")
        .unwrap_or_else(|_| "1.00".into())
        .parse()
        .unwrap_or(1.00);
    let effective_min_profit_usd = if q1_live_flag { q1_floor_live } else { q1_floor_shadow };
    info!(
        cyclic_execute_live = q1_live_flag,
        effective_min_profit_usd,
        cyclic_min_profit_usd_shadow = q1_floor_shadow,
        cyclic_min_profit_usd_live = q1_floor_live,
        "r144 Q1: cyclic dynamic profit floor activo"
    );

    let cfg = CyclicConfig {
        pools,
        log_path,
        rpc_url: rpc_url.to_string(),
        probe_base_units,
        input_decimals,
        cycle_path_tokens: snapshot.global.cycle_path.clone(),
        scan_interval_ms: snapshot.global.scan_interval_ms,
        tier_lookup: Arc::new(tier_lookup),
        pyth_cache,
        pyth_feed_intermediate,
        // r116 Item #3 + r118 Q1: cycles 2-leg actuales no usan extras (Vec vacío).
        // Cuando se añadan cycles N-leg, populate desde TOML config.
        pyth_feeds_extra_legs: Vec::new(),
        price_decimal_adjustment,
        oracle_max_staleness_secs,
        cyclic_wallet,
        effective_min_profit_usd,
    };
    let tx = spawn_worker(cfg, current_slot, fee_manager, circuit_breaker, stats, telemetry)?;
    info!(
        toml = %toml_path,
        pools = pool_addrs.len(),
        total_cap_usd = snapshot.total_cap_usd(),
        depeg_gate_active = pyth_enabled,
        "R64 A2.3+A4.1: cyclic worker spawned from TOML registry with tier-aware depeg gate"
    );
    Ok(Some((tx, pool_addrs)))
}
