// Detector de Fat Finger trades via Pyth benchmark + Jupiter local price.
// Corre en paralelo al arb ciclico. Cuando detecta gap >1% entre precio
// Pyth y precio Jupiter en ruta directa, dispara bundle con tip agresivo.

use crate::config::{name_for, JUP, SOL, USDC};
use crate::jito::{build_bundle, send_bundle, VoteAccountBlacklist};
use crate::jupiter::get_swap_transaction;
use crate::logger::Logger;
use reqwest::Client;
use serde::Deserialize;
use solana_client::rpc_client::RpcClient;
use solana_sdk::signature::{Keypair, Signer};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::time::sleep;

const PYTH_SOL: &str = "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d";
const PYTH_JUP: &str = "0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996";

const GAP_THRESHOLD: f64 = 0.015; // 1%
const PROBE_USDC: f64 = 1000.0;
const FAT_FINGER_TIP: u64 = 2_000_000; // 2M lamports
const COOLDOWN_SECS: u64 = 10;

#[derive(Deserialize)]
struct PythResp {
    parsed: Vec<PythParsed>,
}
#[derive(Deserialize)]
struct PythParsed {
    id: String,
    price: PythPrice,
}
#[derive(Deserialize)]
struct PythPrice {
    price: String,
    expo: i32,
}

fn parse_pyth_price(p: &PythParsed) -> f64 {
    let raw: i64 = p.price.price.parse().unwrap_or(0);
    raw as f64 * 10f64.powi(p.price.expo)
}

async fn fetch_pyth_prices(client: &Client) -> Option<HashMap<String, f64>> {
    let url = format!(
        "https://hermes.pyth.network/v2/updates/price/latest?ids[]={}&ids[]={}",
        PYTH_SOL, PYTH_JUP
    );
    let resp = client.get(&url).timeout(Duration::from_secs(3)).send().await.ok()?;
    let data: PythResp = resp.json().await.ok()?;

    let mut prices = HashMap::new();
    for p in &data.parsed {
        let price = parse_pyth_price(p);
        if price > 0.0 {
            if p.id == PYTH_SOL {
                prices.insert(SOL.to_string(), price);
            } else if p.id == PYTH_JUP {
                prices.insert(JUP.to_string(), price);
            }
        }
    }
    Some(prices)
}

// Retorna precio en USD/token via Jupiter ruta directa
async fn fetch_jupiter_price(client: &Client, intermediate: &str, usdc_amount: u64) -> Option<f64> {
    let url = format!(
        "https://api.jup.ag/swap/v1/quote?inputMint={}&outputMint={}&amount={}&slippageBps=50&onlyDirectRoutes=true",
        USDC, intermediate, usdc_amount
    );
    crate::jup_rate::throttle().await;
    let resp = client.get(&url).timeout(Duration::from_secs(4)).send().await.ok()?;
    let v: serde_json::Value = resp.json().await.ok()?;

    let out_atomic: u64 = v.get("outAmount")?.as_str()?.parse().ok()?;
    let decimals: i32 = if intermediate == SOL { 9 } else { 6 };
    let out_tokens = out_atomic as f64 / 10f64.powi(decimals);
    let usdc_in = usdc_amount as f64 / 1e6;
    Some(usdc_in / out_tokens)
}

pub fn spawn(
    http: Client,
    rpc: Arc<RpcClient>,
    wallet_private_key: Option<String>,
    blacklist: VoteAccountBlacklist,
    logger: Logger,
    sol_price_usd: f64,
    toxicity_snapshots: std::sync::Arc<dashmap::DashMap<String, crate::toxicity::MarketSnapshot>>,
) {
    tokio::spawn(async move {
        let keypair: Option<Keypair> = wallet_private_key.as_ref().and_then(|s| {
            let bytes = bs58::decode(s).into_vec().ok()?;
            Keypair::from_bytes(&bytes).ok()
        });

        let toxicity_filter = crate::toxicity::ToxicityFilter::new(toxicity_snapshots.clone());

        let cooldowns: Arc<Mutex<HashMap<String, Instant>>> =
            Arc::new(Mutex::new(HashMap::new()));

        println!(
            "[fat_finger] iniciado — umbral={:.1}% tip={}M lam probe=${}",
            GAP_THRESHOLD * 100.0,
            FAT_FINGER_TIP / 1_000_000,
            PROBE_USDC
        );

        loop {
            sleep(Duration::from_millis(2000)).await;

            let pyth = match fetch_pyth_prices(&http).await {
                Some(p) => p,
                None => continue,
            };

            for (mint, pyth_price) in &pyth {
                {
                    let cd = cooldowns.lock().unwrap();
                    if let Some(&last) = cd.get(mint.as_str()) {
                        if last.elapsed().as_secs() < COOLDOWN_SECS {
                            continue;
                        }
                    }
                }

                let probe_atomic = (PROBE_USDC * 1e6) as u64;
                let jup_price = match fetch_jupiter_price(&http, mint, probe_atomic).await {
                    Some(p) => p,
                    None => continue,
                };

                let gap = (jup_price - pyth_price).abs() / pyth_price;
                if gap <= GAP_THRESHOLD {
                    continue;
                }

                let name = name_for(mint);
                println!(
                    "[fat_finger] GAP {:.2}% en {} | pyth=${:.4} jup=${:.4}",
                    gap * 100.0,
                    name,
                    pyth_price,
                    jup_price
                );
                cooldowns.lock().unwrap().insert(mint.clone(), Instant::now());

                // FILTRO TOXICIDAD: rechaza si momentum crash detectado (Gemma 2026-04-28)
                let (toxic, reason) = toxicity_filter.is_toxic(mint);
                if toxic {
                    println!("[fat_finger] gap {:.2}% en {} RECHAZADO por toxicidad: {}",
                        gap * 100.0, name, reason);
                    continue;
                }

                let kp = match keypair.as_ref() {
                    Some(k) => k,
                    None => {
                        println!("[fat_finger] paper — gap SAFE detectado {:.2}% en {}", gap * 100.0, name);
                        logger.record_fat_finger_paper(name, gap, PROBE_USDC);
                        continue;
                    }
                };

                // Obtener quote completo para el bundle
                let url_leg1 = format!(
                    "https://api.jup.ag/swap/v1/quote?inputMint={}&outputMint={}&amount={}&slippageBps=50&onlyDirectRoutes=true",
                    USDC, mint, probe_atomic
                );
                crate::jup_rate::throttle().await;
                let leg1_quote: serde_json::Value =
                    match http.get(&url_leg1).timeout(Duration::from_secs(4)).send().await {
                        Ok(r) => match r.json().await {
                            Ok(v) => v,
                            Err(_) => continue,
                        },
                        Err(_) => continue,
                    };

                let mid_atomic: u64 = match leg1_quote
                    .get("outAmount")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok())
                {
                    Some(v) => v,
                    None => continue,
                };

                let url_leg2 = format!(
                    "https://api.jup.ag/swap/v1/quote?inputMint={}&outputMint={}&amount={}&slippageBps=50",
                    mint, USDC, mid_atomic
                );
                crate::jup_rate::throttle().await;
                let leg2_quote: serde_json::Value =
                    match http.get(&url_leg2).timeout(Duration::from_secs(4)).send().await {
                        Ok(r) => match r.json().await {
                            Ok(v) => v,
                            Err(_) => continue,
                        },
                        Err(_) => continue,
                    };

                let out_atomic: u64 = match leg2_quote
                    .get("outAmount")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok())
                {
                    Some(v) => v,
                    None => continue,
                };

                let out_usdc = out_atomic as f64 / 1e6;
                let tip_usdc = FAT_FINGER_TIP as f64 / 1e9 * sol_price_usd;
                let net = out_usdc - PROBE_USDC - tip_usdc - 0.0018;

                if net < 2.00 {
                    println!(
                        "[fat_finger] gap {:.2}% net=${:.4} insuficiente — skip",
                        gap * 100.0,
                        net
                    );
                    continue;
                }

                println!(
                    "[fat_finger] DISPARANDO net=${:.4} tip={}M gap={:.2}%",
                    net,
                    FAT_FINGER_TIP / 1_000_000,
                    gap * 100.0
                );

                let user = kp.pubkey().to_string();
                let (tx1_res, tx2_res) = tokio::join!(
                    get_swap_transaction(&http, &leg1_quote, &user),
                    get_swap_transaction(&http, &leg2_quote, &user)
                );
                let (tx1, tx2) = match (tx1_res, tx2_res) {
                    (Ok(a), Ok(b)) => (a, b),
                    _ => {
                        println!("[fat_finger] fallo obteniendo swap tx");
                        continue;
                    }
                };

                let built = match build_bundle(&rpc, &tx1, &tx2, kp, FAT_FINGER_TIP, &blacklist, None).await {
                    Ok(Some(b)) => b,
                    Ok(None) => {
                        println!("[fat_finger] bundle descartado (blacklist)");
                        continue;
                    }
                    Err(e) => {
                        println!("[fat_finger] buildBundle error: {e}");
                        continue;
                    }
                };

                match send_bundle(&http, &built.bundle, &built.swap_txs, &blacklist).await {
                    Some((id, ep)) => {
                        let host = ep.split('.').next().unwrap_or("?");
                        println!(
                            "[fat_finger] bundle {} ({}) net=${:.4} gap={:.2}%",
                            &id[..8.min(id.len())],
                            host,
                            net,
                            gap * 100.0
                        );
                    }
                    None => println!("[fat_finger] todos endpoints fallaron"),
                }
            }
        }
    });
}
