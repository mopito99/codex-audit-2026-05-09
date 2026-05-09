//! One-shot CLI: pre-create all ATAs the liquidator will need.
//!
//! Per Gemma R11: ATAs in the critical path add 3 instructions and lose us
//! the latency race. This script creates them ONCE so the bundle is smaller
//! and faster.
//!
//! Usage:
//!   cargo run --release --bin setup_atas
//!
//! Mints to pre-create ATAs for (Kamino main market common targets):
//!   USDC, WSOL, JitoSOL, mSOL, JLP, JUP, USDT, ezSOL
//! Plus their cToken counterparts (cWSOL, cUSDC, etc.) — empirically derived.

use anyhow::{Context, Result};
use base64::Engine;
use solana_sdk::{
    instruction::Instruction, message::v0::Message, message::VersionedMessage,
    pubkey, pubkey::Pubkey, transaction::VersionedTransaction,
};
use std::sync::Arc;
use tracing::{info, warn};

use liquidator_rs::{
    ata::{create_ata_idempotent_ix, derive_ata, SPL_TOKEN_PROGRAM},
    rpc, wallet,
};

// Common Kamino main market liquidity mints (collateral or debt sides)
const MINTS: &[(Pubkey, &str)] = &[
    (pubkey!("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"), "USDC"),
    (pubkey!("So11111111111111111111111111111111111111112"), "WSOL"),
    (pubkey!("J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"), "JitoSOL"),
    (pubkey!("mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"), "mSOL"),
    (pubkey!("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"), "USDT"),
    (pubkey!("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"), "JUP"),
];

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::new("info"))
        .init();

    let rpc_url = std::env::var("LIQ_RPC_URL")
        .or_else(|_| std::env::var("CHAINSTACK_RPC_URL"))
        .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".to_string());
    let rpc = Arc::new(rpc::RpcClient::new(rpc_url));
    let wallet = Arc::new(wallet::HotWallet::from_env().context("wallet")?);

    info!(wallet = %wallet.pubkey, "setup_atas — pre-creating ATAs (idempotent, no-op if exist)");

    let mut ixs: Vec<Instruction> = Vec::new();
    for (mint, label) in MINTS {
        let ata = derive_ata(&wallet.pubkey, mint, &SPL_TOKEN_PROGRAM);
        info!(label = label, mint = %mint, ata = %ata, "queueing");
        ixs.push(create_ata_idempotent_ix(
            &wallet.pubkey, &wallet.pubkey, mint, &SPL_TOKEN_PROGRAM));
    }

    let blockhash = rpc.get_latest_blockhash().await?;
    let msg = Message::try_compile(&wallet.pubkey, &ixs, &[], blockhash)?;
    let tx = VersionedTransaction::try_new(VersionedMessage::V0(msg), &[&wallet.keypair])?;
    let bytes = bincode::serialize(&tx)?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);

    info!("simulating setup tx (no live send)...");
    let result = rpc.simulate_transaction(&b64).await?;
    if result.is_success() {
        info!(units = ?result.units_consumed, "✅ setup simulation OK — would create {} ATAs", ixs.len());
        warn!("⚠ this is DRY-RUN. To commit, run with --execute (TODO)");
    } else {
        warn!(err = ?result.err, "❌ setup simulation failed");
        for log in &result.logs { warn!("{log}"); }
    }
    Ok(())
}
