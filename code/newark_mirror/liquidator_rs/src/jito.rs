//! Jito Block Engine bundle client.
//!
//! Endpoints (G3 — NY-only, EU/Frankfurt removed):
//!   https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles
//!
//! Bundle format: array of base58-encoded signed transactions.
//! Last tx in bundle MUST be a tip transfer to one of the 8 Jito tip accounts.
//!
//! Tip strategy: G40 — median(30s) × 2.5 of public tip stream is more robust
//! than p95 (avoids cross-pair tip wars). For M1 we hardcode a conservative
//! tip and add the dynamic stream in a follow-up commit.

use anyhow::{Context, Result};
use rand::seq::SliceRandom;
use serde::{Deserialize, Serialize};
use solana_sdk::{
    pubkey::Pubkey, signature::Signature, system_instruction,
    transaction::VersionedTransaction,
};
use std::str::FromStr;
use std::time::Duration;
use tracing::{debug, info, warn};

/// Jito Block Engine NY (closest to validators in NY4/NY5).
pub const JITO_NY_URL: &str = "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles";

/// 8 known Jito tip accounts on mainnet. Bundle must include a tip transfer
/// to ONE of these for the bundle to be eligible for inclusion.
pub const JITO_TIP_ACCOUNTS: &[&str] = &[
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pivKeVmKomrptTxuCvU3",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
];

/// Conservative tip floor in lamports. 50_000 lamports ≈ $0.0083 at $166/SOL.
/// Long-tail liquidations (G99) often get inclusion at this level since
/// institutional bots compete on bigger ops.
pub const TIP_FLOOR_LAMPORTS: u64 = 50_000;

/// Pick a random tip account (G3: spreads load and avoids being filtered).
pub fn random_tip_account() -> Result<Pubkey> {
    let s = JITO_TIP_ACCOUNTS
        .choose(&mut rand::thread_rng())
        .context("empty tip accounts")?;
    Pubkey::from_str(s).context("parse tip pubkey")
}

/// Build a system_program::transfer instruction sending `lamports` from
/// payer to a randomly-selected Jito tip account.
pub fn build_tip_instruction(
    payer: &Pubkey,
    lamports: u64,
) -> Result<solana_sdk::instruction::Instruction> {
    let tip_to = random_tip_account()?;
    Ok(system_instruction::transfer(payer, &tip_to, lamports))
}

#[derive(Debug, Serialize)]
struct BundleRequest<'a> {
    jsonrpc: &'a str,
    id: u64,
    method: &'a str,
    params: Vec<Vec<String>>,
}

#[derive(Debug, Deserialize)]
struct BundleResponse {
    jsonrpc: String,
    id: u64,
    #[serde(default)]
    result: Option<String>,
    #[serde(default)]
    error: Option<serde_json::Value>,
}

/// Send a bundle of signed VersionedTransactions to Jito NY Block Engine.
///
/// Returns the bundle UUID on success — use it to query getBundleStatuses
/// later to check landing status.
pub async fn send_bundle(
    client: &reqwest::Client,
    txs: &[VersionedTransaction],
) -> Result<String> {
    if txs.is_empty() {
        anyhow::bail!("bundle is empty");
    }
    if txs.len() > 5 {
        anyhow::bail!("bundle exceeds Jito 5-tx limit: got {}", txs.len());
    }

    // Encode each tx as base58 (Jito requires base58, NOT base64)
    let encoded: Vec<String> = txs
        .iter()
        .map(|tx| {
            let bytes = bincode::serialize(tx).expect("tx serialize");
            bs58::encode(bytes).into_string()
        })
        .collect();

    let req = BundleRequest {
        jsonrpc: "2.0",
        id: 1,
        method: "sendBundle",
        params: vec![encoded],
    };

    debug!(n_txs = txs.len(), "sending bundle to Jito NY");
    let resp = client
        .post(JITO_NY_URL)
        .json(&req)
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .context("POST sendBundle")?;

    let status = resp.status();
    let body: BundleResponse = resp.json().await.context("parse Jito response")?;

    if let Some(err) = body.error {
        anyhow::bail!("Jito sendBundle error: {err} (http={status})");
    }
    body.result.context("Jito returned no result")
}

/// Query the landing status of a bundle by UUID.
/// Returns Some(slot) if landed, None if still pending, Err if dropped.
pub async fn get_bundle_status(
    client: &reqwest::Client,
    bundle_id: &str,
) -> Result<Option<u64>> {
    let req = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBundleStatuses",
        "params": [[bundle_id]],
    });

    let resp = client
        .post(JITO_NY_URL)
        .json(&req)
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .context("POST getBundleStatuses")?;

    let body: serde_json::Value = resp.json().await.context("parse response")?;

    let statuses = body
        .pointer("/result/value")
        .and_then(|v| v.as_array())
        .context("missing result.value")?;

    if statuses.is_empty() {
        return Ok(None);
    }
    let s0 = &statuses[0];
    if s0.is_null() {
        return Ok(None);
    }
    let confirmation = s0.get("confirmation_status").and_then(|v| v.as_str());
    let slot = s0.get("slot").and_then(|v| v.as_u64());
    if matches!(confirmation, Some("confirmed") | Some("finalized")) {
        Ok(slot)
    } else if let Some(err) = s0.get("err") {
        if !err.is_null() {
            anyhow::bail!("bundle errored: {err}");
        }
        Ok(None)
    } else {
        Ok(None)
    }
}
