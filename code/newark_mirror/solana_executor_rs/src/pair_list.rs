// pair_list.rs — Dynamic Pair Scanner consumer.
//
// Lee active_pairs.json desde Dallas (via HTTPS) cada 10 min y proporciona
// una lista dinámica de tokens intermedios para el cyclic arb scanner.
//
// Los pares dinámicos se SUMAN a los estáticos de config.rs::scan_pairs().
// Probe conservadora: $300 para tokens desconocidos (ajustable por par).

use serde::Deserialize;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;

const REFRESH_INTERVAL: Duration = Duration::from_secs(600); // 10 min
const FETCH_TIMEOUT:    Duration = Duration::from_secs(10);

#[derive(Debug, Deserialize, Clone)]
pub struct DynamicPair {
    pub mint:           String,
    pub symbol:         String,
    pub liquidity_usd:  u64,
    pub volume_24h_usd: u64,
    pub rotation:       f64,
    pub probe_usdc:     f64,
}

#[derive(Debug, Deserialize)]
struct ActivePairsFile {
    pairs: Vec<DynamicPair>,
}

pub type SharedPairList = Arc<RwLock<Vec<(String, Vec<f64>)>>>;

pub fn new_list() -> SharedPairList {
    Arc::new(RwLock::new(Vec::new()))
}

pub fn spawn(list: SharedPairList, url: String, http: reqwest::Client) {
    tokio::spawn(async move {
        loop {
            match fetch_pairs(&http, &url).await {
                Ok(pairs) => {
                    let count = pairs.len();
                    let mut guard = list.write().await;
                    *guard = pairs;
                    println!("[pair_list] {} pares dinámicos cargados desde scanner", count);
                }
                Err(e) => {
                    println!("[pair_list] fetch failed: {e} — manteniendo lista anterior");
                }
            }
            tokio::time::sleep(REFRESH_INTERVAL).await;
        }
    });
}

async fn fetch_pairs(http: &reqwest::Client, url: &str) -> anyhow::Result<Vec<(String, Vec<f64>)>> {
    let resp = http
        .get(url)
        .timeout(FETCH_TIMEOUT)
        .send()
        .await?
        .error_for_status()?
        .json::<ActivePairsFile>()
        .await?;

    let pairs = resp.pairs
        .into_iter()
        .map(|p| (p.mint, vec![p.probe_usdc]))
        .collect();

    Ok(pairs)
}

/// Devuelve la lista actual de pares dinámicos (copia, no bloquea lector).
pub async fn get(list: &SharedPairList) -> Vec<(String, Vec<f64>)> {
    list.read().await.clone()
}
