//! Env + pool registry config for Phase 1 gRPC subscriber.

use anyhow::{Context, Result};
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;

#[derive(Debug, Clone)]
pub struct PoolEntry {
    pub label: String,
    pub address: Pubkey,
    pub kind: PoolKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PoolKind {
    OrcaWhirlpool,
    RaydiumClmm,
}

#[derive(Debug, Clone)]
pub struct Config {
    pub grpc_url: String,
    pub grpc_token: Option<String>,
    pub rpc_url: String,
    pub pools: Vec<PoolEntry>,
    pub log_path: String,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let _ = dotenvy::dotenv();

        let grpc_url = std::env::var("CYCLIC_GRPC_URL")
            .or_else(|_| std::env::var("LIQ_GRPC_URL"))
            .context("CYCLIC_GRPC_URL or LIQ_GRPC_URL must be set")?;
        let grpc_token = std::env::var("CYCLIC_GRPC_TOKEN")
            .or_else(|_| std::env::var("LIQ_GRPC_TOKEN"))
            .ok();
        let rpc_url = std::env::var("CYCLIC_RPC_URL")
            .or_else(|_| std::env::var("LIQ_RPC_URL"))
            .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".into());

        // Default pool set: Orca SOL/USDC (validated G33).
        // Override via CYCLIC_POOLS="label1=addr1:orca,label2=addr2:raydium"
        let pools = if let Ok(s) = std::env::var("CYCLIC_POOLS") {
            parse_pools(&s)?
        } else {
            vec![PoolEntry {
                label: "orca_sol_usdc".to_string(),
                address: Pubkey::from_str("Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE")?,
                kind: PoolKind::OrcaWhirlpool,
            }]
        };

        let log_path = std::env::var("CYCLIC_LOG_PATH")
            .unwrap_or_else(|_| "/home/ubuntu/cyclic_rs/data/pool_updates.jsonl".into());

        Ok(Self { grpc_url, grpc_token, rpc_url, pools, log_path })
    }
}

fn parse_pools(s: &str) -> Result<Vec<PoolEntry>> {
    s.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|chunk| {
            let (label, rest) = chunk.split_once('=').context("missing '=' in pool entry")?;
            let (addr, kind) = rest.split_once(':').context("missing ':' in pool entry")?;
            let kind = match kind.trim().to_ascii_lowercase().as_str() {
                "orca" => PoolKind::OrcaWhirlpool,
                "raydium" => PoolKind::RaydiumClmm,
                other => anyhow::bail!("unknown pool kind: {other}"),
            };
            Ok(PoolEntry {
                label: label.trim().to_string(),
                address: Pubkey::from_str(addr.trim())?,
                kind,
            })
        })
        .collect()
}
