use crate::sandwich_executor::SandwichGap;
use crate::state_engine::PriceCache;
use serde::Serialize;
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::mpsc;

const MIN_GAP_PCT: f64 = 0.0001; // 0.01% (1 bps) — usado solo para gaps_above_threshold y log de v2_state
const POLL_MS: u64 = 100;
const STATE_FILE: &str = "./data/v2_state.json";
const HISTORY_SIZE: usize = 50;
const ALERT_COOLDOWN_SECS: u64 = 5;

#[derive(Serialize, Clone, Debug)]
struct GapEvent {
    ts: String,
    gap_pct: f64,
    orca_price: f64,
    raydium_price: f64,
    cheap_dex: String,
    expensive_dex: String,
}

#[derive(Serialize, Clone, Debug, Default)]
struct V2State {
    started_at: String,
    paper_mode: bool,
    state_engine_pools_active: usize,
    orca_price: Option<f64>,
    orca_last_update_secs_ago: Option<u64>,
    raydium_price: Option<f64>,
    raydium_last_update_secs_ago: Option<u64>,
    current_gap_pct: f64,
    gaps_detected_total: u64,
    gaps_above_threshold: u64,
    max_gap_seen_pct: f64,
    last_gap_at: Option<String>,
    gap_history: Vec<GapEvent>,
}

pub fn spawn(
    cache: PriceCache,
    paper_mode: bool,
    sandwich_tx: mpsc::Sender<SandwichGap>,
    dynamic_tip: Arc<AtomicU64>,
) {
    tokio::spawn(async move {
        println!(
            "[opportunity_engine] iniciado — gap_min={:.3}% poll={}ms paper={} sandwich_channel=on",
            MIN_GAP_PCT * 100.0,
            POLL_MS,
            paper_mode
        );

        let state = Arc::new(Mutex::new(V2State {
            started_at: chrono::Utc::now().to_rfc3339(),
            paper_mode,
            ..Default::default()
        }));

        // Background flusher: cada 1s escribe v2_state.json
        {
            let state = state.clone();
            tokio::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    let snapshot = { state.lock().unwrap().clone() };
                    if let Ok(json) = serde_json::to_string_pretty(&snapshot) {
                        let path = PathBuf::from(STATE_FILE);
                        if let Some(parent) = path.parent() {
                            let _ = std::fs::create_dir_all(parent);
                        }
                        let _ = std::fs::write(&path, json);
                    }
                }
            });
        }

        let mut last_alert: Option<Instant> = None;

        loop {
            tokio::time::sleep(Duration::from_millis(POLL_MS)).await;

            let orca_pk = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE";
            let raydium_pk = "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj";

            let orca = cache.get(orca_pk).map(|s| *s);
            let ray = cache.get(raydium_pk).map(|s| *s);

            // Update state metrics
            {
                let mut s = state.lock().unwrap();
                s.state_engine_pools_active = cache.len();
                s.orca_price = orca.map(|o| o.price);
                s.orca_last_update_secs_ago = orca.map(|o| o.last_update.elapsed().as_secs());
                s.raydium_price = ray.map(|r| r.price);
                s.raydium_last_update_secs_ago = ray.map(|r| r.last_update.elapsed().as_secs());
            }

            let (orca, ray) = match (orca, ray) {
                (Some(a), Some(b)) => (a, b),
                _ => continue,
            };
            if orca.last_update.elapsed().as_secs() > 5 || ray.last_update.elapsed().as_secs() > 5 {
                continue;
            }
            if orca.price <= 0.0 || ray.price <= 0.0 {
                continue;
            }

            let (cheap, expensive, p_cheap, p_expensive) = if orca.price < ray.price {
                ("Orca", "Raydium", orca.price, ray.price)
            } else {
                ("Raydium", "Orca", ray.price, orca.price)
            };
            let gap = (p_expensive - p_cheap) / p_cheap;

            {
                let mut s = state.lock().unwrap();
                s.current_gap_pct = gap;
                s.gaps_detected_total += 1;
                if gap > s.max_gap_seen_pct {
                    s.max_gap_seen_pct = gap;
                }
            }

            // ── EMITIR AL SANDWICH EXECUTOR (antes del cooldown de log) ──
            // Mandamos TODOS los gaps positivos. El executor decide con su propio threshold + cooldown.
            if gap > 0.0 {
                let now_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_millis() as u64)
                    .unwrap_or(0);
                let tip_now = dynamic_tip.load(Ordering::Relaxed);
                let sg = SandwichGap {
                    gap_pct: gap,
                    cheap_dex: cheap.to_string(),
                    expensive_dex: expensive.to_string(),
                    cheap_price: p_cheap,
                    expensive_price: p_expensive,
                    current_tip_lamports: tip_now,
                    ts_ms: now_ms,
                    pair: "SOL/USDC".to_string(),
                };
                // try_send no bloquea: si el canal esta lleno, dropea silenciosamente.
                let _ = sandwich_tx.try_send(sg);
            }

            // ── LOG / V2_STATE: cooldown de 5s para no inundar el dashboard ──
            if gap < MIN_GAP_PCT {
                continue;
            }
            if let Some(t) = last_alert {
                if t.elapsed().as_secs() < ALERT_COOLDOWN_SECS {
                    continue;
                }
            }
            last_alert = Some(Instant::now());

            println!(
                "[opportunity_engine] GAP {:.3}% | Orca={:.4} Raydium={:.4} | comprar en {} vender en {}",
                gap * 100.0,
                orca.price,
                ray.price,
                cheap,
                expensive
            );

            let event = GapEvent {
                ts: chrono::Utc::now().to_rfc3339(),
                gap_pct: gap,
                orca_price: orca.price,
                raydium_price: ray.price,
                cheap_dex: cheap.to_string(),
                expensive_dex: expensive.to_string(),
            };
            {
                let mut s = state.lock().unwrap();
                s.gaps_above_threshold += 1;
                s.last_gap_at = Some(event.ts.clone());
                s.gap_history.insert(0, event);
                if s.gap_history.len() > HISTORY_SIZE {
                    s.gap_history.truncate(HISTORY_SIZE);
                }
            }

            if !paper_mode {
                // TODO: ejecutar bundle (siguiente paso del pipeline)
            }
        }
    });
}
