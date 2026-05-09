//! Pyth Hermes HTTP poller — R67 (c1) fix per Gemma verdict.
//!
//! Background task that polls https://hermes.pyth.network/v2/updates/price/latest
//! every POLL_INTERVAL_MS and upserts results into PythCache using V1-compatible
//! Pubkeys as cache keys (so the depeg gate code doesn't need to change).
//!
//! Why HTTP and why this is NOT a Principio #1 violation:
//!   - The cyclic execute hot path reads PythCache::get() in O(1) from RAM.
//!   - This poller runs in a separate tokio task, OUT of the hot path.
//!   - Pyth V1 push oracles were decommissioned ~14 months ago. Yellowstone
//!     gRPC has nothing to push for those accounts. Hermes is the only
//!     up-to-date source for Pyth v2 prices on Solana mainnet without going
//!     through the on-chain Pyth Receiver V2 (which requires VAA verification
//!     and ephemeral PriceUpdateV2 accounts — significantly heavier).
//!   - Acceptable per Gemma R67 D.2 explicit verdict.

use crate::pyth_oracle::{OraclePrice, PythCache, PYTH_SOL_USD, PYTH_USDC_USD, PYTH_USDT_USD};
use anyhow::{Context, Result};
use serde::Deserialize;
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, info, warn};

const HERMES_BASE_URL: &str = "https://hermes.pyth.network/v2/updates/price/latest";
const POLL_INTERVAL_MS: u64 = 1500;

/// Pyth Hermes price feed IDs (32-byte hex, NOT V1 on-chain pubkeys).
/// Source: https://www.pyth.network/developers/price-feed-ids → Solana > Crypto.
const FEED_SOL_USD: &str = "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d";
const FEED_USDC_USD: &str = "eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a";
const FEED_USDT_USD: &str = "2b89b9dc8fdf9f34709a5b106b472f0f39bb6ca9ce04b0fd7f2e971688e2e53b";

fn feed_to_v1_pubkey(feed_id: &str) -> Option<&'static str> {
    match feed_id.trim_start_matches("0x") {
        FEED_SOL_USD => Some(PYTH_SOL_USD),
        FEED_USDC_USD => Some(PYTH_USDC_USD),
        FEED_USDT_USD => Some(PYTH_USDT_USD),
        _ => None,
    }
}

#[derive(Deserialize, Debug)]
struct HermesResponse {
    parsed: Vec<HermesPriceFeed>,
}

#[derive(Deserialize, Debug)]
struct HermesPriceFeed {
    id: String,
    price: HermesPrice,
}

#[derive(Deserialize, Debug)]
struct HermesPrice {
    price: String,
    conf: String,
    expo: i32,
    publish_time: i64,
}

pub fn spawn_poller(cache: Arc<PythCache>) {
    tokio::spawn(async move {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                tracing::error!(error=?e, "R67: Hermes client build failed; poller exiting");
                return;
            }
        };

        let url = format!(
            "{}?ids[]=0x{}&ids[]=0x{}&ids[]=0x{}",
            HERMES_BASE_URL, FEED_SOL_USD, FEED_USDC_USD, FEED_USDT_USD
        );
        info!(
            poll_ms = POLL_INTERVAL_MS,
            n_feeds = 3,
            "R67 (c1): Pyth Hermes poller spawned (V1 deprecated → HTTP fallback)"
        );

        let mut interval = tokio::time::interval(Duration::from_millis(POLL_INTERVAL_MS));
        let mut consecutive_errors: u32 = 0;
        loop {
            interval.tick().await;
            match fetch_once(&client, &url, &cache).await {
                Ok(n) => {
                    consecutive_errors = 0;
                    debug!(n_updated = n, "R67 Hermes poll OK");
                }
                Err(e) => {
                    cache.record_error();
                    consecutive_errors = consecutive_errors.saturating_add(1);
                    if consecutive_errors == 1 || consecutive_errors % 20 == 0 {
                        warn!(error=?e, consecutive_errors, "R67 Hermes poll failed");
                    }
                }
            }
        }
    });
}

async fn fetch_once(client: &reqwest::Client, url: &str, cache: &PythCache) -> Result<usize> {
    let resp: HermesResponse = client
        .get(url)
        .send()
        .await
        .context("hermes GET")?
        .json()
        .await
        .context("hermes JSON parse")?;
    let mut n = 0;
    for feed in &resp.parsed {
        let Some(pk_str) = feed_to_v1_pubkey(&feed.id) else {
            continue;
        };
        let pubkey = Pubkey::from_str(pk_str).context("parse v1 pubkey")?;
        let scale = 10f64.powi(feed.price.expo);
        let price_raw: i64 = feed.price.price.parse().context("parse price")?;
        let conf_raw: u64 = feed.price.conf.parse().context("parse conf")?;
        let price_usd = price_raw as f64 * scale;
        let confidence = conf_raw as f64 * scale;
        if price_usd <= 0.0 || feed.price.publish_time <= 0 {
            cache.record_error();
            continue;
        }
        cache.upsert(OraclePrice {
            mint: pubkey,
            price_usd,
            confidence,
            publish_time: feed.price.publish_time,
            slot: 0,
        });
        n += 1;
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn feed_to_pubkey_maps_known_feeds() {
        assert_eq!(feed_to_v1_pubkey(FEED_SOL_USD), Some(PYTH_SOL_USD));
        assert_eq!(
            feed_to_v1_pubkey(&format!("0x{}", FEED_SOL_USD)),
            Some(PYTH_SOL_USD)
        );
        assert_eq!(feed_to_v1_pubkey(FEED_USDC_USD), Some(PYTH_USDC_USD));
        assert_eq!(feed_to_v1_pubkey("dead0000"), None);
    }
}
