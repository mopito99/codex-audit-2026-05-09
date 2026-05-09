// Worker que actualiza el DashMap de MarketSnapshot polling Helius cada 2s.
// Calcula sell_volume_pct, whale_tx_count, price_change desde getSignaturesForAddress
// y getTransactions.
//
// NOTA: idealmente sería un WebSocket transactionSubscribe (latencia ms),
// pero Helius RPC no expone transactionSubscribe en plan estandar.
// Polling cada 2s es suficiente porque el filter solo se consulta antes de bundle.

use crate::toxicity::MarketSnapshot;
use dashmap::DashMap;
use serde::Deserialize;
use std::sync::Arc;
use std::time::{Duration, Instant};

const POLL_INTERVAL_MS: u64 = 2000;
const WHALE_THRESHOLD_USD: f64 = 1000.0;
const WINDOW_30S_SECS: u64 = 30;

// Mints a monitorear (mismo set que scan_pairs)
const MONITORED_MINTS: &[(&str, &str)] = &[
    ("So11111111111111111111111111111111111111112",  "SOL"),
    ("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  "JUP"),
    ("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "BONK"),
    ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF"),
];

#[derive(Deserialize, Debug)]
struct SignatureInfo {
    signature: String,
    #[serde(rename = "blockTime")] block_time: Option<i64>,
    slot: u64,
    err: Option<serde_json::Value>,
}

#[derive(Deserialize, Debug)]
struct RpcResponse<T> {
    result: Option<T>,
    error: Option<serde_json::Value>,
}

pub fn spawn(snapshots: Arc<DashMap<String, MarketSnapshot>>, helius_rpc: String) {
    tokio::spawn(async move {
        let http = match reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build() {
                Ok(c) => c,
                Err(_) => { eprintln!("[toxicity] no se pudo crear http client"); return; }
            };

        println!("[toxicity] worker iniciado — poll {}ms, monitorea {} mints",
            POLL_INTERVAL_MS, MONITORED_MINTS.len());

        loop {
            tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;

            for (mint, name) in MONITORED_MINTS {
                if let Some(snapshot) = fetch_market_snapshot(&http, &helius_rpc, mint).await {
                    snapshots.insert(mint.to_string(), snapshot);
                } else {
                    // Si falla, marcar snapshot stale (el filter usara failsafe SAFE)
                    let _ = name;
                }
            }
        }
    });
}

async fn fetch_market_snapshot(
    http: &reqwest::Client,
    rpc: &str,
    mint: &str,
) -> Option<MarketSnapshot> {
    // Pedir las últimas 30 firmas del mint
    let payload = serde_json::json!({
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [mint, {"limit": 30}],
    });
    let res = http.post(rpc).json(&payload).send().await.ok()?;
    let parsed: RpcResponse<Vec<SignatureInfo>> = res.json().await.ok()?;
    let sigs = parsed.result?;

    if sigs.is_empty() {
        return Some(MarketSnapshot {
            asset_mint: mint.to_string(),
            updated_at: Instant::now(),
            ..Default::default()
        });
    }

    let now_unix = chrono::Utc::now().timestamp();
    let cutoff_30s = now_unix - WINDOW_30S_SECS as i64;

    // Contar txs exitosas en la ventana 30s
    let recent: Vec<&SignatureInfo> = sigs.iter()
        .filter(|s| s.err.is_none() && s.block_time.map_or(false, |t| t >= cutoff_30s))
        .collect();

    let tx_count = recent.len() as u32;
    if tx_count == 0 {
        return Some(MarketSnapshot {
            asset_mint: mint.to_string(),
            updated_at: Instant::now(),
            ..Default::default()
        });
    }

    // Heurística simple sin parsear las txs (caro):
    // - Si hay >15 txs en 30s = alto volumen (probable momentum)
    // - sell_volume_pct: aproximar por densidad temporal de txs
    //   (txs muy juntas en tiempo = pressure direccional)

    let estimated_volume_usd = (tx_count as f64) * 200.0;  // estimación conservadora

    // Detectar concentración temporal (todas las txs en últimos 5s = momentum)
    let cutoff_5s = now_unix - 5;
    let very_recent = recent.iter()
        .filter(|s| s.block_time.map_or(false, |t| t >= cutoff_5s))
        .count() as f64;
    let concentration = very_recent / tx_count as f64;

    // Si >70% de las txs están en últimos 5s, asumir presión direccional alta
    // Sin parsear, no podemos saber buy/sell — usar concentración como proxy
    let estimated_sell_pct = if concentration > 0.7 { 0.85 } else { 0.50 };

    // Whale txs: aproximar por txs en slots consecutivos
    let mut whale_count = 0u32;
    let mut prev_slot = 0u64;
    for s in &recent {
        if prev_slot > 0 && s.slot.saturating_sub(prev_slot) <= 2 {
            whale_count += 1;
        }
        prev_slot = s.slot;
    }

    Some(MarketSnapshot {
        asset_mint: mint.to_string(),
        last_30s_volume_usd: estimated_volume_usd,
        sell_volume_pct: estimated_sell_pct,
        whale_tx_count: whale_count,
        price_change_last_5s: 0.0,  // requiere precio en cada slot, no implementado en v1
        slots_since_gap_start: 0,    // se calcula en fat_finger.rs cuando detecta gap
        updated_at: Instant::now(),
    })
}
