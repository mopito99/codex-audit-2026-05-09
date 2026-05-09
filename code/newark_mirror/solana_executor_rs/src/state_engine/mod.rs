// State engine — cache de estado CLMM completo via Helius accountSubscribe.
// Cada update de pool parsea: price, sqrt_price_x64, liquidity, tick_current, tick_spacing.

use crate::dex::{self, DexType, FullPoolState};
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio_tungstenite::{connect_async, tungstenite::Message};

#[derive(Clone, Copy, Debug)]
pub struct PoolPriceState {
    pub price: f64,
    pub sqrt_price_x64: u128,
    pub liquidity: u128,
    pub tick_current: i32,
    pub tick_spacing: i32,
    pub last_update: Instant,
    pub dex: DexType,
}

pub type PriceCache = Arc<DashMap<String, PoolPriceState>>;

pub struct PoolWatch {
    pub pubkey: &'static str,
    pub dex: DexType,
    pub dec0: u8,
    pub dec1: u8,
    pub label: &'static str,
}

#[derive(Deserialize, Debug)]
struct WsMsg {
    params: Option<WsParams>,
}
#[derive(Deserialize, Debug)]
struct WsParams {
    result: Option<WsResult>,
}
#[derive(Deserialize, Debug)]
struct WsResult {
    value: Option<WsValue>,
}
#[derive(Deserialize, Debug)]
struct WsValue {
    data: Option<(String, String)>,
}

pub fn new_cache() -> PriceCache {
    Arc::new(DashMap::new())
}

pub fn spawn(cache: PriceCache, helius_ws: String, watches: Vec<PoolWatch>) {
    tokio::spawn(async move {
        loop {
            match run(cache.clone(), &helius_ws, &watches).await {
                Ok(_) => println!("[state_engine] loop terminó, reconnect en 3s"),
                Err(e) => eprintln!("[state_engine] error: {}, reconnect en 3s", e),
            }
            tokio::time::sleep(Duration::from_secs(3)).await;
        }
    });
}

async fn run(cache: PriceCache, ws_url: &str, watches: &[PoolWatch]) -> anyhow::Result<()> {
    println!("[state_engine] conectando a {} | watching {} pools", ws_url, watches.len());
    let (ws, _) = connect_async(ws_url).await?;
    let (mut write, mut read) = ws.split();

    let mut sub_to_idx: std::collections::HashMap<u64, usize> = std::collections::HashMap::new();

    for (i, w) in watches.iter().enumerate() {
        let sub = serde_json::json!({
            "jsonrpc": "2.0",
            "id": i + 1,
            "method": "accountSubscribe",
            "params": [w.pubkey, {"encoding": "base64", "commitment": "processed"}]
        });
        write.send(Message::Text(sub.to_string())).await?;
        println!("[state_engine] subscribed pool={} dex={:?} label={}", w.pubkey, w.dex, w.label);
    }

    while let Some(msg) = read.next().await {
        match msg? {
            Message::Text(t) => {
                let v: serde_json::Value = match serde_json::from_str(&t) {
                    Ok(v) => v, Err(_) => continue,
                };

                if let (Some(req_id), Some(sub_id)) = (
                    v.get("id").and_then(|x| x.as_u64()),
                    v.get("result").and_then(|x| x.as_u64()),
                ) {
                    sub_to_idx.insert(sub_id, (req_id as usize).saturating_sub(1));
                    continue;
                }

                let sub_id = match v.pointer("/params/subscription").and_then(|x| x.as_u64()) {
                    Some(s) => s, None => continue,
                };
                let idx = match sub_to_idx.get(&sub_id) { Some(i) => *i, None => continue };
                if idx >= watches.len() { continue; }
                let watch = &watches[idx];

                let b64 = match v.pointer("/params/result/value/data/0").and_then(|x| x.as_str()) {
                    Some(s) => s, None => continue,
                };
                use base64::Engine;
                let data = match base64::engine::general_purpose::STANDARD.decode(b64) {
                    Ok(d) => d, Err(_) => continue,
                };

                if let Some(fs) = dex::parse_full_state(watch.dex, &data, watch.dec0, watch.dec1) {
                    cache.insert(watch.pubkey.to_string(), PoolPriceState {
                        price:          fs.price,
                        sqrt_price_x64: fs.sqrt_price_x64,
                        liquidity:      fs.liquidity,
                        tick_current:   fs.tick_current,
                        tick_spacing:   fs.tick_spacing,
                        last_update:    Instant::now(),
                        dex:            watch.dex,
                    });
                }
            }
            Message::Ping(p) => { write.send(Message::Pong(p)).await?; }
            Message::Close(_) => break,
            _ => {}
        }
    }
    Ok(())
}
