// Tip stream v3 — Jito public tip_floor poll cada 1.5s.
// R34 Q2: TipStream para FeeManager via get_rolling_median().
// R59 fix (G47 legacy bug): se almacena la MEDIANA (p50) real, no p95.
// Razón: p95 sobrepagaba sistemáticamente (Gemma confidence 100%).
// Comportamiento previo (p95) generaba cost p95 = $0.17 vs p50 = $0.021,
// inflando "would_send" rejection rate en datos shadow run.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use serde::Deserialize;
use tokio::time::Duration;

const JITO_TIP_FLOOR_URL: &str = "https://bundles.jito.wtf/api/v1/bundles/tip_floor";
const POLL_INTERVAL_MS: u64 = 1500;

#[derive(Deserialize, Debug)]
struct TipFloor {
    landed_tips_25th_percentile: f64,
    landed_tips_50th_percentile: f64,
    landed_tips_75th_percentile: f64,
    landed_tips_95th_percentile: f64,
    landed_tips_99th_percentile: f64,
    ema_landed_tips_50th_percentile: f64,
}

/// R34 Q2 wrapper for FeeManager.
#[derive(Clone)]
pub struct TipStream {
    inner: Arc<AtomicU64>,
}

impl Default for TipStream {
    fn default() -> Self {
        Self::new()
    }
}

impl TipStream {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(AtomicU64::new(200_000)),
        }
    }

    pub fn handle(&self) -> Arc<AtomicU64> {
        self.inner.clone()
    }

    /// Returns the latest stored tip floor (p50/median lamports, clamped).
    /// R59 fix: ahora retorna la MEDIANA real, no p95.
    pub fn get_rolling_median(&self) -> u64 {
        self.inner.load(Ordering::Relaxed)
    }
}

pub fn spawn(tip: Arc<AtomicU64>, _helius_rpc: String) {
    tokio::spawn(async move {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .unwrap();

        tracing::info!(poll_ms = POLL_INTERVAL_MS, "tip_stream: spawn Jito public tip_floor");

        loop {
            match fetch_tip_floor(&client).await {
                Ok(floor) => {
                    // R59 fix (G47 legacy bug): usar p50 (mediana) en lugar de p95.
                    // p95 sobrepagaba sistemáticamente. Gemma confidence 100%.
                    let target_lam = (floor.landed_tips_50th_percentile * 1e9) as u64;
                    // R64 fix (A1.1 + A1.2): clamp floor 50k → 20k.
                    // Bear 2026 p50 real ~1-5k lamports. 50k era overpay 10-50x
                    // y nos hacia "sandwich profile" visible. 20k cubre bot
                    // detection minimum sin ser desperate.
                    let clamped = target_lam.clamp(20_000, 25_000_000);
                    tip.store(clamped, Ordering::Relaxed);
                    tracing::debug!(
                        p25 = (floor.landed_tips_25th_percentile * 1e9) as u64,
                        p50 = (floor.landed_tips_50th_percentile * 1e9) as u64,
                        p75 = (floor.landed_tips_75th_percentile * 1e9) as u64,
                        p95 = (floor.landed_tips_95th_percentile * 1e9) as u64,
                        target_p50 = clamped,
                        "tip_stream floor (R59 median)"
                    );
                }
                Err(e) => tracing::warn!(error=?e, "tip_stream fetch failed"),
            }
            tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
        }
    });
}

async fn fetch_tip_floor(client: &reqwest::Client) -> anyhow::Result<TipFloor> {
    let resp: Vec<TipFloor> = client.get(JITO_TIP_FLOOR_URL).send().await?.json().await?;
    resp.into_iter().next().ok_or_else(|| anyhow::anyhow!("empty tip_floor response"))
}
