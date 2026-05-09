//! Solana JSON-RPC client wrapper.
//!
//! Used for getAccountInfo (fetch Reserves on-demand) and simulateTransaction
//! (validate liquidate ix before sending live).

use anyhow::{anyhow, Context, Result};
use base64::Engine;
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;
use std::time::Duration;
use tracing::debug;

#[derive(Debug, Clone)]
pub struct RpcClient {
    pub url: String,
    pub http: reqwest::Client,
}

impl RpcClient {
    pub fn new(url: String) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(8))
            .pool_max_idle_per_host(4)
            .build()
            .expect("reqwest client");
        Self { url, http }
    }

    /// Fetch raw account data via getAccountInfo.
    pub async fn get_account_data(&self, pubkey: &Pubkey) -> Result<Option<Vec<u8>>> {
        let req = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                pubkey.to_string(),
                { "encoding": "base64", "commitment": "confirmed" }
            ]
        });
        let resp: serde_json::Value = self.http
            .post(&self.url)
            .json(&req)
            .send().await.context("getAccountInfo POST")?
            .json().await.context("getAccountInfo decode")?;

        if let Some(err) = resp.get("error") {
            return Err(anyhow!("RPC error: {err}"));
        }
        let val = resp.pointer("/result/value");
        match val {
            Some(v) if v.is_null() => Ok(None),
            Some(v) => {
                let arr = v.pointer("/data")
                    .and_then(|d| d.as_array())
                    .context("missing data array")?;
                let b64 = arr.first()
                    .and_then(|s| s.as_str())
                    .context("data[0] not string")?;
                let bytes = base64::engine::general_purpose::STANDARD
                    .decode(b64)
                    .context("base64 decode")?;
                debug!(pubkey = %pubkey, len = bytes.len(), "fetched account");
                Ok(Some(bytes))
            }
            None => Err(anyhow!("no result.value")),
        }
    }

    /// Simulate a base64-encoded signed transaction.
    /// Returns Ok(()) if simulation succeeded, Err with detail if not.
    pub async fn simulate_transaction(&self, tx_b64: &str) -> Result<SimulationResult> {
        let req = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [
                tx_b64,
                {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "replaceRecentBlockhash": true,
                    "sigVerify": false
                }
            ]
        });
        let resp: serde_json::Value = self.http
            .post(&self.url)
            .json(&req)
            .send().await.context("simulateTransaction POST")?
            .json().await.context("simulateTransaction decode")?;

        if let Some(err) = resp.get("error") {
            return Err(anyhow!("RPC error: {err}"));
        }
        let val = resp.pointer("/result/value")
            .context("missing result.value")?;
        let err = val.get("err").cloned();
        let logs: Vec<String> = val.get("logs")
            .and_then(|l| l.as_array())
            .map(|a| a.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect())
            .unwrap_or_default();
        let units_consumed = val.get("unitsConsumed").and_then(|u| u.as_u64());

        Ok(SimulationResult { err, logs, units_consumed })
    }

    /// Get the latest blockhash for tx assembly.
    pub async fn get_latest_blockhash(&self) -> Result<solana_sdk::hash::Hash> {
        let req = serde_json::json!({
            "jsonrpc": "2.0", "id": 1,
            "method": "getLatestBlockhash",
            "params": [{ "commitment": "confirmed" }]
        });
        let resp: serde_json::Value = self.http
            .post(&self.url).json(&req).send().await?
            .json().await?;
        let s = resp.pointer("/result/value/blockhash")
            .and_then(|v| v.as_str())
            .context("missing blockhash")?;
        s.parse::<solana_sdk::hash::Hash>().context("parse blockhash")
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SimulationResult {
    pub err: Option<serde_json::Value>,
    pub logs: Vec<String>,
    pub units_consumed: Option<u64>,
}

impl SimulationResult {
    pub fn is_success(&self) -> bool {
        self.err.is_none() || self.err.as_ref().map(|v| v.is_null()).unwrap_or(true)
    }
}
