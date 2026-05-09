//! CLI: simulate liquidation against a single known Obligation.
//! Usage: cargo run --release --bin simulate_once -- <obligation_pubkey>

use anyhow::{bail, Context, Result};
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;
use std::sync::Arc;
use tracing::info;

use liquidator_rs::{kamino, rpc, simulator, wallet};

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info,liquidator_rs=debug")),
        )
        .init();

    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        bail!("usage: {} <obligation_pubkey>", args[0]);
    }
    let obligation_pk = Pubkey::from_str(&args[1]).context("parse pubkey")?;

    let rpc_url = std::env::var("LIQ_RPC_URL")
        .or_else(|_| std::env::var("CHAINSTACK_RPC_URL"))
        .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".to_string());
    let rpc = Arc::new(rpc::RpcClient::new(rpc_url));

    let wallet = Arc::new(wallet::HotWallet::from_env().context("wallet")?);
    info!(wallet = %wallet.pubkey, "wallet loaded");

    info!(obligation = %obligation_pk, "fetching obligation account...");
    let obl_data = rpc.get_account_data(&obligation_pk).await?
        .context("obligation not found")?;
    info!(size = obl_data.len(), "obligation fetched");

    let parsed = kamino::parse_obligation(&obl_data).context("parse obligation")?;
    info!(
        owner = %parsed.owner_b58,
        deposited = parsed.deposited_value_usd,
        borrowed = parsed.borrowed_value_usd,
        allowed = parsed.allowed_borrow_value_usd,
        hf = parsed.health_factor,
        "obligation parsed"
    );

    info!("running simulate_liquidation()...");
    let result = simulator::simulate_liquidation(&rpc, &wallet, obligation_pk, &obl_data).await?;

    if result.is_success() {
        info!(units = ?result.units_consumed, "✅ SIMULATION OK");
    } else {
        info!(err = ?result.err, "❌ simulation failed (expected if obligation healthy)");
    }
    info!("=== logs ===");
    for log in &result.logs {
        info!("{}", log);
    }
    Ok(())
}
