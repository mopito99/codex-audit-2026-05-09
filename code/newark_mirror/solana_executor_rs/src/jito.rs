#![allow(deprecated)] // solana_sdk::system_instruction deprecated en 2.0 — migrar a solana_system_interface en Phase 3
// Jito bundle building + send + status polling.
// Espejo de src/jito.ts del bot Node.

use crate::config::{JITO_ENDPOINTS, JITO_TIP_ACCOUNTS};
use anyhow::Result;
use base64::{engine::general_purpose, Engine as _};
use rand::seq::SliceRandom;
use serde::Deserialize;
use solana_sdk::{
    hash::Hash,
    instruction::Instruction,
    message::{v0::Message as V0Message, VersionedMessage},
    pubkey::Pubkey,
    signature::{Keypair, Signer},
    system_instruction,
    transaction::VersionedTransaction,
};
use std::collections::HashSet;
use std::str::FromStr;
use std::sync::{Arc, Mutex};

#[derive(Clone, Default)]
pub struct VoteAccountBlacklist(Arc<Mutex<HashSet<String>>>);

impl VoteAccountBlacklist {
    pub fn new() -> Self { Self::default() }
    pub fn has_conflict(&self, tx: &VersionedTransaction) -> bool {
        let bl = self.0.lock().unwrap();
        tx.message.static_account_keys().iter().any(|k| bl.contains(&k.to_string()))
    }
    pub fn add_from_txs(&self, txs: &[VersionedTransaction]) -> usize {
        let mut bl = self.0.lock().unwrap();
        let mut added = 0;
        for tx in txs {
            for k in tx.message.static_account_keys() {
                bl.insert(k.to_string());
                added += 1;
            }
        }
        added
    }
    pub fn len(&self) -> usize { self.0.lock().unwrap().len() }
}

pub fn random_tip_account() -> Pubkey {
    let mut rng = rand::thread_rng();
    let acc = JITO_TIP_ACCOUNTS.choose(&mut rng).unwrap();
    Pubkey::from_str(acc).unwrap()
}

pub fn deserialize_and_sign(b64: &str, signer: &Keypair) -> Result<VersionedTransaction> {
    let bytes = general_purpose::STANDARD.decode(b64)?;
    let mut tx: VersionedTransaction = bincode::deserialize(&bytes)?;
    let sigs = tx.message.serialize();
    tx.signatures[0] = signer.sign_message(&sigs);
    Ok(tx)
}

pub fn build_tip_tx(payer: &Keypair, blockhash: Hash, tip_lamports: u64) -> VersionedTransaction {
    let to = random_tip_account();
    let ix: Instruction = system_instruction::transfer(&payer.pubkey(), &to, tip_lamports);
    let msg = V0Message::try_compile(&payer.pubkey(), &[ix], &[], blockhash).unwrap();
    let vmsg = VersionedMessage::V0(msg);
    VersionedTransaction::try_new(vmsg, &[payer]).unwrap()
}

pub fn tx_to_b58(tx: &VersionedTransaction) -> String {
    let bytes = bincode::serialize(tx).unwrap();
    bs58::encode(bytes).into_string()
}

pub struct BuiltBundle {
    pub bundle: Vec<String>,                  // base58 txs (swap1, swap2, tip)
    pub swap_txs: Vec<VersionedTransaction>, // para blacklist en caso de fallo vote-account
}

pub async fn build_bundle(
    rpc: &solana_client::rpc_client::RpcClient,
    tx1_b64: &str,
    tx2_b64: &str,
    keypair: &Keypair,
    tip_lamports: u64,
    blacklist: &VoteAccountBlacklist,
    blockhash_cache: &Arc<tokio::sync::RwLock<Option<Hash>>>,
) -> Result<Option<BuiltBundle>> {
    let blockhash = match *blockhash_cache.read().await {
        Some(bh) => bh,
        None     => rpc.get_latest_blockhash()?,  // fallback si el cache aún no tiene valor
    };
    let swap1 = deserialize_and_sign(tx1_b64, keypair)?;
    let swap2 = deserialize_and_sign(tx2_b64, keypair)?;

    if blacklist.has_conflict(&swap1) || blacklist.has_conflict(&swap2) {
        return Ok(None);
    }

    let tip_tx = build_tip_tx(keypair, blockhash, tip_lamports);
    let bundle = vec![tx_to_b58(&swap1), tx_to_b58(&swap2), tx_to_b58(&tip_tx)];
    Ok(Some(BuiltBundle { bundle, swap_txs: vec![swap1, swap2] }))
}

#[derive(Deserialize)]
struct JsonRpcErr { code: Option<i32>, message: String }

#[derive(Deserialize)]
struct JsonRpcResp { result: Option<String>, error: Option<JsonRpcErr> }

pub async fn send_bundle(
    client: &reqwest::Client,
    bundle: &[String],
    swap_txs: &[VersionedTransaction],
    blacklist: &VoteAccountBlacklist,
) -> Option<(String, String)> {
    let mut endpoints: Vec<&&str> = JITO_ENDPOINTS.iter().collect();
    let mut rng = rand::thread_rng();
    endpoints.shuffle(&mut rng);

    for endpoint in endpoints {
        let payload = serde_json::json!({
            "jsonrpc": "2.0", "id": 1,
            "method": "sendBundle",
            "params": [bundle],
        });
        let res = match client.post(*endpoint)
            .json(&payload)
            .timeout(std::time::Duration::from_secs(8))
            .send().await
        {
            Ok(r) => r,
            Err(_) => continue,
        };
        let text = res.text().await.unwrap_or_default();
        let parsed: serde_json::Result<JsonRpcResp> = serde_json::from_str(&text);
        if let Ok(p) = parsed {
            if let Some(e) = p.error {
                if e.message.contains("vote account") {
                    let added = blacklist.add_from_txs(swap_txs);
                    eprintln!("    [jito] blacklist +{added} cuentas (total: {})", blacklist.len());
                    return None;
                }
                if e.code == Some(-32097) || text.contains("429") {
                    eprintln!("    [jito] 429 — siguiente");
                    continue;
                }
                eprintln!("    [jito] error {} — {}", e.code.unwrap_or(0), e.message);
                continue;
            }
            if let Some(bid) = p.result {
                return Some((bid, endpoint.to_string()));
            }
        }
    }
    None
}

pub async fn poll_bundle_status(
    client: &reqwest::Client,
    bundle_id: &str,
    endpoint: &str,
    max_wait_ms: u64,
) -> &'static str {
    let status_url = endpoint.replace("/api/v1/bundles", "/api/v1/getBundleStatuses");
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(max_wait_ms);

    while std::time::Instant::now() < deadline {
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        let payload = serde_json::json!({
            "jsonrpc": "2.0", "id": 1,
            "method": "getBundleStatuses",
            "params": [[bundle_id]],
        });
        if let Ok(res) = client.post(&status_url)
            .json(&payload)
            .timeout(std::time::Duration::from_secs(4))
            .send().await
        {
            if let Ok(v) = res.json::<serde_json::Value>().await {
                if let Some(entries) = v.pointer("/result/value").and_then(|x| x.as_array()) {
                    if let Some(entry) = entries.first().and_then(|x| x.as_object()) {
                        if !entry.get("err").map_or(true, |e| e.is_null()) {
                            return "failed";
                        }
                        if let Some(s) = entry.get("confirmation_status").and_then(|x| x.as_str()) {
                            if s == "confirmed" || s == "finalized" {
                                return "landed";
                            }
                        }
                    }
                }
            }
        }
    }
    "timeout"
}
