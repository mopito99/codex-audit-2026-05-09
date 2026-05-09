// Polling asíncrono de cuentas de pool Orca+Raydium vía Helius JSON-RPC.
// Actualiza Arc<RwLock<Option<PoolPrices>>> cada POLL_MS milisegundos.
// El main loop lee el estado compartido sin latencia de red.

use crate::pool_state::{decode_orca_price, decode_raydium_price, PoolPrices,
                         ORCA_SOL_USDC, RAYDIUM_SOL_USDC};
use anyhow::Result;
use base64::{engine::general_purpose, Engine as _};
use serde_json::Value;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;

pub type SharedPrices = Arc<RwLock<Option<PoolPrices>>>;

const POLL_MS: u64 = 50; // polling cada 50ms → detección gap en <50ms

pub fn new_shared_prices() -> SharedPrices {
    Arc::new(RwLock::new(None))
}

/// Fetch raw account data via Helius getAccountInfo (base64 encoding).
async fn fetch_account_data(
    http: &reqwest::Client,
    rpc_url: &str,
    pubkey: &str,
) -> Result<Vec<u8>> {
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [pubkey, {"encoding": "base64", "commitment": "processed"}]
    });
    let resp = http
        .post(rpc_url)
        .json(&payload)
        .timeout(Duration::from_secs(3))
        .send()
        .await?;
    let v: Value = resp.json().await?;
    let b64 = v
        .pointer("/result/value/data/0")
        .and_then(|x| x.as_str())
        .ok_or_else(|| anyhow::anyhow!("no account data for {pubkey}"))?;
    Ok(general_purpose::STANDARD.decode(b64)?)
}

/// Tarea de fondo: actualiza SharedPrices cada POLL_MS ms.
/// No termina — se cancela con el proceso principal.
pub async fn run_pool_watcher(
    http: reqwest::Client,
    rpc_url: String,
    prices: SharedPrices,
) {
    println!("[pool_watcher] iniciando — polling Orca+Raydium SOL/USDC cada {POLL_MS}ms");
    let mut consecutive_errors = 0u32;

    loop {
        let t0 = Instant::now();

        let (orca_res, ray_res) = tokio::join!(
            fetch_account_data(&http, &rpc_url, ORCA_SOL_USDC),
            fetch_account_data(&http, &rpc_url, RAYDIUM_SOL_USDC),
        );

        match (orca_res, ray_res) {
            (Ok(orca_data), Ok(ray_data)) => {
                let op = decode_orca_price(&orca_data);
                let rp = decode_raydium_price(&ray_data);

                if let (Some(orca), Some(raydium)) = (op, rp) {
                    let pp = PoolPrices { orca, raydium, updated_at: Instant::now() };
                    *prices.write().await = Some(pp);
                    consecutive_errors = 0;
                } else {
                    eprintln!("[pool_watcher] decode failed: orca={op:?} raydium={rp:?}");
                    consecutive_errors += 1;
                }
            }
            (Err(e1), _) => {
                eprintln!("[pool_watcher] orca fetch error: {e1}");
                consecutive_errors += 1;
            }
            (_, Err(e2)) => {
                eprintln!("[pool_watcher] raydium fetch error: {e2}");
                consecutive_errors += 1;
            }
        }

        // Backoff exponencial si hay errores consecutivos (max 2s)
        let backoff = if consecutive_errors > 0 {
            Duration::from_millis(POLL_MS * (1 << consecutive_errors.min(5)))
        } else {
            Duration::from_millis(POLL_MS)
        };

        let elapsed = t0.elapsed();
        if backoff > elapsed {
            tokio::time::sleep(backoff - elapsed).await;
        }
    }
}
