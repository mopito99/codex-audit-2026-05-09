//! Yellowstone gRPC subscriber + liquidation simulator dispatcher.

use liquidator_rs::config::Config;
use liquidator_rs::cyclic_dispatch::CyclicAccountUpdate;
use liquidator_rs::kamino;
use liquidator_rs::logger::JsonlLogger;
use liquidator_rs::rpc::RpcClient;
use liquidator_rs::simulator;
use liquidator_rs::wallet::HotWallet;
use liquidator_rs::ObligationEvent;
use anyhow::{Context, Result};
use futures::{SinkExt, StreamExt};
use solana_sdk::pubkey::Pubkey;
use std::collections::HashMap;
use dashmap::DashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
use tracing::{debug, error, info, warn};
use std::sync::atomic::{AtomicU64, Ordering};
use yellowstone_grpc_client::GeyserGrpcClient;
use yellowstone_grpc_proto::geyser::{
    SubscribeRequest, SubscribeRequestFilterAccounts, SubscribeRequestFilterSlots,
    SubscribeRequestPing, SubscribeUpdate, subscribe_update::UpdateOneof, CommitmentLevel,
};

pub async fn run(
    cfg: Config,
    logger: Arc<Mutex<JsonlLogger>>,
    rpc: Arc<RpcClient>,
    wallet: Arc<HotWallet>,
    // R74 Ventana 2 Fase 2 — bounded mpsc::Sender (Path C). Sender side uses
    // try_send → non-blocking; if channel saturated, log WARN and drop the
    // update (Gemma R74 v3 constraint #2: blocked ingest > dropped update).
    cyclic_tx: Option<mpsc::Sender<CyclicAccountUpdate>>,
    cyclic_pool_addrs: Vec<String>,
    current_slot: Arc<AtomicU64>,
    telemetry: Arc<liquidator_rs::telemetry::Telemetry>,
    // R62 A4 + Principio #1: PythCache + addresses to subscribe via gRPC push.
    // Si pyth_cache.is_none() o pyth_addrs.is_empty() → no se añade filter.
    pyth_cache: Option<Arc<liquidator_rs::pyth_oracle::PythCache>>,
    pyth_addrs: Vec<String>,
) -> Result<()> {
    info!("connecting to Yellowstone gRPC...");

    // R74 Ventana 1 Fase 1.1 — TCP_NODELAY=true: kill Nagle algorithm so packets
    // ship immediately instead of buffering, cutting tens of ms off the gRPC RTT
    // on the hot path (Gemma R74 v2 pick V1.3 = builder native option, no fallback
    // needed because yellowstone-grpc-client 12.2 exposes it directly).
    let mut client_builder = GeyserGrpcClient::build_from_shared(cfg.grpc_url.clone())?
        .tls_config(yellowstone_grpc_client::ClientTlsConfig::new().with_native_roots())?
        .tcp_nodelay(true);
    if let Some(token) = cfg.grpc_token.as_deref() {
        client_builder = client_builder.x_token(Some(token.to_string()))?;
    }
    let mut client = client_builder.connect().await
        .context("connecting Yellowstone gRPC")?;
    info!("Yellowstone gRPC connected");

    let mut accounts_filter = HashMap::new();
    // R62: LIQ_KAMINO_DISABLE=true → skip suscripción Kamino (Liquidator F2 OFF).
    // Marco /stop'd liquidator F2 manualmente; este flag asegura que tras restart
    // no se rearma. Para reactivar: unset env var + restart + /manual_reset.
    let kamino_disabled = std::env::var("LIQ_KAMINO_DISABLE")
        .map(|v| v == "true").unwrap_or(false);
    if !kamino_disabled {
        accounts_filter.insert(
            "kamino".to_string(),
            SubscribeRequestFilterAccounts {
                account: vec![],
                owner: vec![cfg.kamino_program_id.to_string()],
                filters: vec![],
                nonempty_txn_signature: None,
            },
        );
    } else {
        info!("LIQ_KAMINO_DISABLE=true — skipping Kamino subscription (Liquidator F2 OFF)");
    }
    if !cyclic_pool_addrs.is_empty() {
        accounts_filter.insert(
            "clmm_pools".to_string(),
            SubscribeRequestFilterAccounts {
                account: cyclic_pool_addrs.clone(),
                owner: vec![],
                filters: vec![],
                nonempty_txn_signature: None,
            },
        );
    }
    // R62 A4 + Principio #1: Pyth oracle accounts via push gRPC (no HTTP poll).
    // Latencia ganada: ~1.97s peor caso poll → ~10-30ms push.
    if pyth_cache.is_some() && !pyth_addrs.is_empty() {
        accounts_filter.insert(
            "pyth_oracles".to_string(),
            SubscribeRequestFilterAccounts {
                account: pyth_addrs.clone(),
                owner: vec![],
                filters: vec![],
                nonempty_txn_signature: None,
            },
        );
    }
    // R31 Q2: subscribe to slot updates so cyclic worker can compute slot_lag.
    let mut slots_filter = HashMap::new();
    slots_filter.insert(
        "slot_sub".to_string(),
        SubscribeRequestFilterSlots::default(),
    );
    let req = SubscribeRequest {
        accounts: accounts_filter,
        slots: slots_filter,
        // R68 Gemma E.5: Confirmed→Processed -400ms baseline
        commitment: Some(CommitmentLevel::Processed as i32),
        ..Default::default()
    };
    let (mut subscribe_tx, mut stream) = client.subscribe_with_request(Some(req)).await
        .context("subscribe_with_request")?;
    info!(
        kamino = true,
        clmm_pools = cyclic_pool_addrs.len(),
        pyth_oracles = pyth_addrs.len(),
        "subscribed (Kamino owner + CLMM pools + Pyth oracles multi-filter R62 A4)"
    );

    let mut update_count: u64 = 0;
    let mut unhealthy_count: u64 = 0;
    let mut sim_attempts: u64 = 0;
    let mut sim_successes: u64 = 0;
    // Throttle: don't simulate the same Obligation more than once per 30s
    let recent_sim: std::sync::Arc<DashMap<Pubkey, std::time::Instant>> = std::sync::Arc::new(DashMap::new());

    while let Some(message) = stream.next().await {
        match message {
            Ok(msg) => {
                let filters = msg.filters.clone();
                let Some(uo) = msg.update_oneof else { continue };

                // R62 A4 + Principio #1: Pyth oracle update push → PythCache.upsert
                // Hot path safety: handler O(1), no spawns. Usa pyth-sdk-solana
                // proper (no manual offset parsing — más seguro contra layout changes).
                if filters.iter().any(|f| f == "pyth_oracles") {
                    if let UpdateOneof::Account(acc_update) = uo {
                        if let Some(acc) = acc_update.account {
                            if let (Ok(bytes), Some(cache)) = (
                                <[u8; 32]>::try_from(acc.pubkey.as_slice()),
                                pyth_cache.as_ref(),
                            ) {
                                let pubkey = Pubkey::new_from_array(bytes);
                                match pyth_sdk_solana::state::load_price_account::<
                                    32, (),
                                >(&acc.data) {
                                    Ok(price_account) => {
                                        // R63 A8.1 fix: validar status == Trading.
                                        // Si Halted/Auction/Unknown → record_error (NO upsert
                                        // precio stale "last known" durante crash).
                                        use pyth_sdk_solana::state::PriceStatus;
                                        let agg_status = price_account.agg.status;
                                        if agg_status != PriceStatus::Trading {
                                            cache.record_error();
                                            warn!(
                                                ?pubkey,
                                                ?agg_status,
                                                "Pyth status NOT Trading (R63 A8.1) — skip upsert"
                                            );
                                            continue;
                                        }
                                        let feed = price_account.to_price_feed(&pubkey);
                                        let price = feed.get_price_unchecked();
                                        let scale = 10f64.powi(price.expo);
                                        let price_usd = price.price as f64 * scale;
                                        let confidence = price.conf as f64 * scale;
                                        if price_usd > 0.0 && price.publish_time > 0 {
                                            cache.upsert(
                                                liquidator_rs::pyth_oracle::OraclePrice {
                                                    mint: pubkey,
                                                    price_usd,
                                                    confidence,
                                                    publish_time: price.publish_time,
                                                    slot: acc_update.slot,
                                                }
                                            );
                                        } else {
                                            cache.record_error();
                                        }
                                    }
                                    Err(e) => {
                                        cache.record_error();
                                        debug!(error=?e, ?pubkey, "Pyth load_price_account failed");
                                    }
                                }
                            }
                        }
                    }
                    continue;
                }

                // R28 Q2 dispatch: CLMM pool updates → cyclic worker, NEVER touch Kamino path.
                if filters.iter().any(|f| f == "clmm_pools") {
                    if let UpdateOneof::Account(acc_update) = uo {
                        if let Some(acc) = acc_update.account {
                            if let Ok(bytes) = <[u8; 32]>::try_from(acc.pubkey.as_slice()) {
                                if let Some(tx) = cyclic_tx.as_ref() {
                                    // R74 Ventana 2 Fase 2 (Path C, Gemma R74 v3 constraint #2)
                                    // — try_send is non-blocking; if channel saturated we
                                    // drop and warn rather than block the ingest hot path.
                                    use tokio::sync::mpsc::error::TrySendError;
                                    match tx.try_send(CyclicAccountUpdate {
                                        pubkey: Pubkey::new_from_array(bytes),
                                        data: acc.data,
                                        slot: acc_update.slot,
                                    }) {
                                        Ok(()) => telemetry.inc_pending(),
                                        Err(TrySendError::Full(_)) => {
                                            warn!("Channel saturated, dropping update");
                                        }
                                        Err(TrySendError::Closed(_)) => {
                                            warn!("Cyclic channel closed (worker dead?), dropping update");
                                        }
                                    }
                                }
                            }
                        }
                    }
                    continue;
                }

                match uo {
                    UpdateOneof::Account(acc_update) => {
                    update_count += 1;
                    let Some(acc) = acc_update.account else { continue };
                    let pubkey_bytes: [u8; 32] = match acc.pubkey.as_slice().try_into() {
                        Ok(a) => a, Err(_) => continue,
                    };
                    let pubkey = Pubkey::new_from_array(pubkey_bytes);
                    let pubkey_b58 = pubkey.to_string();
                    let slot = acc_update.slot;
                    let size = acc.data.len();

                    if size != 3344 { continue; }

                    // R17 CRITICAL #3: skip multi-asset obligations for first probe
                    // (extract_first_reserves only handles 1+1)
                    if let Ok((deposits, borrows)) = kamino::accounts::count_deposits_borrows(&acc.data) {
                        if deposits != 1 || borrows != 1 {
                            continue;
                        }
                    } else {
                        continue;
                    }

                    let parsed = match kamino::parse_obligation(&acc.data) {
                        Ok(p) => p,
                        Err(e) => { debug!(error=?e, %pubkey_b58, "parse failed"); continue; }
                    };

                    let evt = ObligationEvent {
                        ts: chrono::Utc::now(),
                        slot,
                        pubkey: pubkey_b58.clone(),
                        owner: parsed.owner_b58.clone(),
                        deposited_value_usd: parsed.deposited_value_usd,
                        borrowed_value_usd: parsed.borrowed_value_usd,
                        allowed_borrow_value_usd: parsed.allowed_borrow_value_usd,
                        unhealthy_borrow_value_usd: parsed.unhealthy_borrow_value_usd,
                        health_factor: parsed.health_factor,
                        liquidatable: parsed.health_factor < 1.0,
                    };

                    if evt.health_factor >= cfg.health_threshold_warn || evt.borrowed_value_usd <= 1.0 {
                        continue;
                    }

                    unhealthy_count += 1;
                    {
                        let mut lg = logger.lock().await;
                        if let Err(e) = lg.write(&evt) { error!(error=?e, "log write"); }
                    }

                    // Trigger simulator for genuinely liquidatable positions
                    if evt.health_factor < 1.05 {
                        warn!(
                            slot, %pubkey_b58, hf = evt.health_factor,
                            borrowed_usd = evt.borrowed_value_usd,
                            "🔴 LIQUIDATABLE detected"
                        );

                        let now = std::time::Instant::now();
                        let recent = recent_sim.get(&pubkey).map(|r| *r);
                        if recent.map_or(true, |t| now.duration_since(t).as_secs() >= 30) {
                            recent_sim.insert(pubkey, now);
                            sim_attempts += 1;
                            let rpc_c = rpc.clone();
                            let wallet_c = wallet.clone();
                            let data = acc.data.clone();
                            let _recent_sim_keepalive = recent_sim.clone();  // Arc clone for spawned task safety
                            let evt_clone = evt.clone();
                            tokio::spawn(async move {
                                match simulator::simulate_liquidation(
                                    &rpc_c, &wallet_c, pubkey, &data
                                ).await {
                                    Ok(r) if r.is_success() => {
                                        info!(units = ?r.units_consumed,
                                            %pubkey_b58, hf=evt_clone.health_factor,
                                            "🟢 simulation OK");
                                        // LIVE GATE: HF must be <1.0 (truly liquidatable)
                                        // AND debt must be <= 00 (probe cap)
                                        // AND profit estimate >=  (Gemma R12-Q6)
                                        let live_mode = std::env::var("LIQ_LIVE_MODE").map(|v| v == "true").unwrap_or(false);
                                        if live_mode
                                           && evt_clone.health_factor < 1.0
                                           && evt_clone.borrowed_value_usd <= 200.0
                                        {
                                            // Estimate profit conservatively: 5% liquidation bonus on debt
                                            let estimated_profit = evt_clone.borrowed_value_usd * 0.05;
                                            if estimated_profit >= 2.0 {
                                                info!(estimated_profit, "🚀 LIVE GATE OPEN — attempting bundle send");
                                                let live_log_path = std::path::PathBuf::from("/home/ubuntu/liquidator_rs/data/live_attempts.jsonl");
                                                let mut live_logger = liquidator_rs::logger::JsonlLogger::open(&live_log_path).ok();
                                                let attempt_record = serde_json::json!({
                                                    "ts": chrono::Utc::now().to_rfc3339(),
                                                    "obligation": pubkey_b58,
                                                    "hf": evt_clone.health_factor,
                                                    "borrowed_usd": evt_clone.borrowed_value_usd,
                                                    "deposited_usd": evt_clone.deposited_value_usd,
                                                    "estimated_profit": estimated_profit,
                                                    "max_debt_cap": 200.0,
                                                    "tip_lamports": 50000u64
                                                });
                                                match simulator::execute_live_liquidation(
                                                    &rpc_c, &wallet_c, pubkey, &data,
                                                    200.0, 2.0, 5_000_000,
                                                ).await {
                                                    Ok(bundle_id) => {
                                                        info!(%bundle_id, %pubkey_b58,
                                                            "🚀🚀 BUNDLE SENT TO JITO");
                                                        let mut rec = attempt_record.clone();
                                                        rec["status"] = serde_json::json!("SENT");
                                                        rec["bundle_id"] = serde_json::json!(bundle_id);
                                                        if let Some(l) = live_logger.as_mut() { let _ = l.write(&rec); }
                                                    }
                                                    Err(e) => {
                                                        error!(error=?e, %pubkey_b58, "❌ LIVE bundle send FAILED");
                                                        let mut rec = attempt_record.clone();
                                                        rec["status"] = serde_json::json!("FAILED");
                                                        rec["error"] = serde_json::json!(format!("{:?}", e));
                                                        if let Some(l) = live_logger.as_mut() { let _ = l.write(&rec); }
                                                    }
                                                }
                                            } else {
                                                info!(estimated_profit, "profit too low, skip");
                                            }
                                        } else {
                                            info!(live_mode, hf=evt_clone.health_factor,
                                                debt=evt_clone.borrowed_value_usd,
                                                "LIVE gate closed (paper-only or filter)");
                                        }
                                    }
                                    Ok(r) => {
                                        warn!(err=?r.err, %pubkey_b58, "🟡 simulation rejected (paper safe)");
                                    }
                                    Err(e) => {
                                        warn!(error=?e, %pubkey_b58, "simulator error");
                                    }
                                }
                            });
                        }
                    }
                }
                UpdateOneof::Slot(slot_update) => {
                    // R31 Q2: latest confirmed slot for slot_lag computation.
                    current_slot.store(slot_update.slot, Ordering::Relaxed);
                }
                UpdateOneof::Ping(_) => {
                    let _ = subscribe_tx.send(SubscribeRequest {
                        ping: Some(SubscribeRequestPing { id: 1 }),
                        ..Default::default()
                    }).await;
                }
                    _ => {}
                }
            }
            Err(e) => {
                error!(error=?e, "stream error");
                return Err(anyhow::anyhow!("gRPC stream: {e}"));
            }
        }

        if update_count % 1000 == 0 {
            info!(updates = update_count, unhealthy = unhealthy_count,
                  sim_attempts, sim_successes, "stream stats");
        }
    }
    warn!("gRPC stream ended");
    Ok(())
}
