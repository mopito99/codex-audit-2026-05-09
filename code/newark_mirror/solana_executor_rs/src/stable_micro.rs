// Bot stable_micro — primer bot del ecosistema (advisor 2026-04-29).
// Estrategia: cyclic USDC→USDT→USDC con probe pequeno, tip muy bajo, threshold tight.
//
// Por que funciona:
// - Stables casi nunca se mueven >1 bps
// - Ballenas no compiten por gaps de $0.05 en $500
// - Tip de p25 (~$0.001) = caemos cuando nadie quiere
//
// Comparte HTTP client, rate limiter, blockhash cache, logger con el bot principal.

use crate::blockhash_worker::{self, BlockhashCache};
use crate::config::{USDC, USDT};
use crate::jito::{build_bundle, send_bundle, VoteAccountBlacklist};
use crate::jupiter::{find_cyclic_arb, get_swap_transaction, ArbResult};
use crate::logger::Logger;
use reqwest::Client;
use solana_client::rpc_client::RpcClient;
use solana_sdk::signature::{Keypair, Signer};
use std::sync::Arc;
use std::time::Duration;

const PROBE_USDC: f64 = 500.0;
const POLL_INTERVAL_MS: u64 = 3000;
const TIP_LAMPORTS: u64 = 5_000;     // ~$0.001 (p25 zone)
const MIN_PROFIT_USDC: f64 = 0.04;   // $0.04 net minimo
const MIN_PROFIT_BPS: f64 = 0.5;     // 0.5 bps stables
const SLIPPAGE_BPS: u32 = 5;         // muy tight: stables no se mueven

pub fn spawn(
    http: Client,
    rpc: Arc<RpcClient>,
    wallet_private_key: Option<String>,
    blacklist: VoteAccountBlacklist,
    logger: Logger,
    blockhash_cache: BlockhashCache,
    paper_mode: bool,
    sol_price_usd: f64,
) {
    tokio::spawn(async move {
        let keypair: Option<Keypair> = wallet_private_key.as_ref().and_then(|s| {
            let bytes = bs58::decode(s).into_vec().ok()?;
            Keypair::from_bytes(&bytes).ok()
        });

        let base_fees_usdc = (5_000.0 * 2.0 / 1e9) * sol_price_usd;
        let tip_usdc = (TIP_LAMPORTS as f64 / 1e9) * sol_price_usd;
        let total_cost_usdc = tip_usdc + base_fees_usdc;

        println!(
            "[stable_micro] iniciado — USDC<->USDT probe=${} tip={} lam (${:.4}) min_net=${} min_bps={}",
            PROBE_USDC, TIP_LAMPORTS, tip_usdc, MIN_PROFIT_USDC, MIN_PROFIT_BPS
        );

        loop {
            tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;

            let result = find_cyclic_arb(
                &http,
                USDT,
                PROBE_USDC,
                total_cost_usdc,
                SLIPPAGE_BPS,
            ).await;

            match result {
                ArbResult::Ok(arb) | ArbResult::NoProfit(arb) => {
                    let profitable = arb.net_profit >= MIN_PROFIT_USDC
                        && arb.profit_bps >= MIN_PROFIT_BPS;

                    if !profitable { continue; }

                    println!(
                        "[stable_micro] ARB USDC->USDT->USDC | gross=${:.4} net=${:.4} ({:.2} bps) | {:?} -> {:?}",
                        arb.gross_profit, arb.net_profit, arb.profit_bps,
                        arb.leg1_dexes, arb.leg2_dexes
                    );

                    if paper_mode {
                        println!("    [paper] stable_micro net=${:.4}", arb.net_profit);
                        continue;
                    }

                    let kp = match keypair.as_ref() { Some(k) => k, None => continue };

                    let user = kp.pubkey().to_string();
                    let (tx1_res, tx2_res) = tokio::join!(
                        get_swap_transaction(&http, &arb.leg1_quote, &user),
                        get_swap_transaction(&http, &arb.leg2_quote, &user)
                    );
                    let (tx1, tx2) = match (tx1_res, tx2_res) {
                        (Ok(a), Ok(b)) => (a, b),
                        _ => { println!("    [stable_micro] swap tx fallo"); continue; }
                    };

                    let cached_bh = blockhash_worker::get(&blockhash_cache);
                    let built = match build_bundle(
                        &rpc, &tx1, &tx2, kp, TIP_LAMPORTS, &blacklist, cached_bh
                    ).await {
                        Ok(Some(b)) => b,
                        Ok(None)    => { println!("    [stable_micro] blacklist"); continue; }
                        Err(e)      => { println!("    [stable_micro] buildBundle err: {e}"); continue; }
                    };

                    match send_bundle(&http, &built.bundle, &built.swap_txs, &blacklist).await {
                        Some((id, ep)) => {
                            let host = ep.split('.').next().unwrap_or("?");
                            println!(
                                "    [stable_micro] bundle enviado: {} ({}) tip={} lam (${:.4})",
                                &id[..8.min(id.len())], host, TIP_LAMPORTS, tip_usdc
                            );
                        }
                        None => println!("    [stable_micro] todos endpoints fallaron"),
                    }
                }
                ArbResult::NoRoute  => {}
                ArbResult::ApiError => {}
            }
        }
    });
}
