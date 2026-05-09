//! p75 priority-fee helper using getRecentPrioritizationFees.
//! Cached for 2s to avoid hammering RPC inside the hot loop.
//! R28 Q5: PriorityFeeConfig wraps the threshold formula
//! `base_fee + p75_per_cu * cu_estimate`.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;

#[derive(Debug, Deserialize)]
struct PrioFeeRpcResponse {
    result: Vec<PrioFeeEntry>,
}

#[derive(Debug, Deserialize)]
struct PrioFeeEntry {
    #[allow(dead_code)]
    slot: u64,
    #[serde(rename = "prioritizationFee")]
    prioritization_fee: u64,
}

#[derive(Debug, Serialize)]
struct RpcReq<'a> {
    jsonrpc: &'static str,
    id: u32,
    method: &'static str,
    params: Vec<Vec<&'a str>>,
}

#[derive(Clone)]
pub struct PriorityFeeCache {
    rpc_url: String,
    inner: Arc<RwLock<Option<(Instant, u64)>>>,
    ttl: Duration,
}

impl PriorityFeeCache {
    pub fn new(rpc_url: String) -> Self {
        Self {
            rpc_url,
            inner: Arc::new(RwLock::new(None)),
            ttl: Duration::from_millis(2_000),
        }
    }

    /// Returns the p75 of recent prioritization fees (lamports per CU) over the
    /// last 150 slots, optionally filtered by writable accounts (`pool_pubkeys`).
    pub async fn get_p75(&self, pool_pubkeys: &[Pubkey]) -> Result<u64> {
        if let Some((ts, val)) = *self.inner.read().await {
            if ts.elapsed() < self.ttl {
                return Ok(val);
            }
        }

        let pubkey_strs: Vec<String> = pool_pubkeys.iter().map(|p| p.to_string()).collect();
        let pubkey_refs: Vec<&str> = pubkey_strs.iter().map(String::as_str).collect();
        let body = RpcReq {
            jsonrpc: "2.0",
            id: 1,
            method: "getRecentPrioritizationFees",
            params: if pool_pubkeys.is_empty() {
                vec![]
            } else {
                vec![pubkey_refs]
            },
        };

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()?;
        let resp: PrioFeeRpcResponse = client
            .post(&self.rpc_url)
            .json(&body)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;

        if resp.result.is_empty() {
            return Err(anyhow!("empty getRecentPrioritizationFees response"));
        }

        let mut fees: Vec<u64> = resp.result.iter().map(|e| e.prioritization_fee).collect();
        fees.sort_unstable();
        let idx = ((fees.len() as f64) * 0.75).floor() as usize;
        let p75 = fees[idx.min(fees.len() - 1)];

        *self.inner.write().await = Some((Instant::now(), p75));
        Ok(p75)
    }
}

// === R28 Q5: threshold formula with CU multiplier =============================

#[derive(Debug, Clone, Copy)]
pub struct PriorityFeeConfig {
    pub base_fee_lamports: u64, // 5000 * signatures
    pub cu_estimate: u64,       // 100k for 2-leg swap, 150k for 3-leg
}

impl Default for PriorityFeeConfig {
    fn default() -> Self {
        Self::new()
    }
}

impl PriorityFeeConfig {
    pub fn new() -> Self {
        Self {
            base_fee_lamports: 10_000, // 2 signatures typical for 2-leg arb
            cu_estimate: 100_000,
        }
    }

    pub fn calculate_threshold(&self, p75_per_cu: u64) -> u64 {
        let total_priority_fee = p75_per_cu.saturating_mul(self.cu_estimate);
        self.base_fee_lamports.saturating_add(total_priority_fee)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn cache_returns_same_value_within_ttl() {
        let cache = PriorityFeeCache::new("http://localhost:0".into());
        *cache.inner.write().await = Some((Instant::now(), 1234));
        assert_eq!(cache.get_p75(&[]).await.unwrap(), 1234);
    }

    #[test]
    fn threshold_includes_cu_multiplier() {
        let cfg = PriorityFeeConfig::new();
        // p75 = 100 lamports/CU, cu = 100k → priority = 10M, plus 10k base = 10_010_000
        assert_eq!(cfg.calculate_threshold(100), 10_010_000);
    }

    #[test]
    fn threshold_saturates_on_overflow() {
        let cfg = PriorityFeeConfig::new();
        let huge = cfg.calculate_threshold(u64::MAX);
        assert!(huge > 0);
    }
}
