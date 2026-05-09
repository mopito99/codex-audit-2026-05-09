// Tip stream v2: usa endpoint publico oficial de Jito (bundles.jito.wtf/api/v1/bundles/tip_floor)
// que devuelve los percentiles reales de los TIPS QUE LANDEAN. No requiere whitelist.
// Polling cada 1.5s en vez de 60s — Jito auctions corren a 50ms ticks.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use serde::Deserialize;
use tokio::time::Duration;

const JITO_TIP_FLOOR_URL: &str = "https://bundles.jito.wtf/api/v1/bundles/tip_floor";
const POLL_INTERVAL_MS: u64 = 1500; // 1.5s — vs 60s anterior

#[derive(Deserialize, Debug)]
struct TipFloor {
    landed_tips_25th_percentile: f64,
    landed_tips_50th_percentile: f64,
    landed_tips_75th_percentile: f64,
    landed_tips_95th_percentile: f64,
    landed_tips_99th_percentile: f64,
    ema_landed_tips_50th_percentile: f64,
}

pub fn spawn(tip: Arc<AtomicU64>, _helius_rpc: String) {
    tokio::spawn(async move {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .unwrap();

        println!("[tip_stream] iniciando con Jito public tip_floor — poll {}ms", POLL_INTERVAL_MS);

        loop {
            match fetch_tip_floor(&client).await {
                Ok(floor) => {
                    // Targeteamos p95 — para arbs cortos donde queremos UN landing
                    // (advisor: "p90 cuando edge corto, p99 solo si profit grande")
                    let target_lam = (floor.landed_tips_95th_percentile * 1e9) as u64;
                    // Clamp [200k, 5M] — proteccion contra spikes anomalos
                    let clamped = target_lam.clamp(200_000, 25_000_000);
                    tip.store(clamped, Ordering::Relaxed);
                    println!(
                        "[tip_stream] floor: p50={:.0} p75={:.0} p95={:.0} p99={:.0} lam | usamos p95={} lam (${:.4})",
                        floor.landed_tips_50th_percentile * 1e9,
                        floor.landed_tips_75th_percentile * 1e9,
                        floor.landed_tips_95th_percentile * 1e9,
                        floor.landed_tips_99th_percentile * 1e9,
                        clamped,
                        clamped as f64 / 1e9 * 175.0
                    );
                }
                Err(e) => eprintln!("[tip_stream] fetch fallido: {e}"),
            }
            tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
        }
    });
}

async fn fetch_tip_floor(client: &reqwest::Client) -> anyhow::Result<TipFloor> {
    let resp: Vec<TipFloor> = client.get(JITO_TIP_FLOOR_URL).send().await?.json().await?;
    resp.into_iter().next().ok_or_else(|| anyhow::anyhow!("empty tip_floor response"))
}
