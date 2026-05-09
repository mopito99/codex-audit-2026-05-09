//! pubkey_check — bonus utility delivered as Gemma R45 (off-topic from R44 C1).
//! Validates Solana pubkeys + checks they exist on-chain. Useful as a typo guard
//! for pool/program addresses before deploying changes that touch them.
//! NOT the Telegram ID discovery tool that R44 C1 actually requested.
//! Run with: cargo run --bin pubkey_check

use anyhow::Result;
use solana_client::rpc_client::RpcClient;
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;

fn main() -> Result<()> {
    let rpc_url = std::env::var("LIQ_RPC_URL")
        .or_else(|_| std::env::var("CHAINSTACK_RPC_URL"))
        .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".to_string());
    let client = RpcClient::new(rpc_url.clone());

    println!("--- pubkey_check ---");
    println!("RPC: {}\n", rpc_url);

    let targets = vec![
        ("Kamino Lend program", "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"),
        ("Orca Whirlpool program", "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"),
        ("Raydium CLMM program", "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"),
        ("Orca SOL/USDC pool (G33)", "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"),
        ("Raydium SOL/USDC pool", "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj"),
        ("Hot wallet (R17 op)", "<REDACTED-WALLET-MASTER>"),
    ];

    for (name, addr) in targets {
        match Pubkey::from_str(addr) {
            Ok(pubkey) => match client.get_account(&pubkey) {
                Ok(acc) => println!("[OK] {}: {} (owner={}, size={})", name, pubkey, acc.owner, acc.data.len()),
                Err(e) => println!("[!!] {}: {} (rpc err: {})", name, pubkey, e),
            },
            Err(_) => println!("[XX] {}: invalid pubkey format: {}", name, addr),
        }
    }

    println!("\n--- end ---");
    Ok(())
}
