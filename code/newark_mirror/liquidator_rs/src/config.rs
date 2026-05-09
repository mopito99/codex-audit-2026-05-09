//! Config loaded from env vars.

use anyhow::{Context, Result};
use solana_sdk::pubkey::Pubkey;
use std::path::PathBuf;
use std::str::FromStr;

#[derive(Debug, Clone)]
pub struct Config {
    /// Yellowstone gRPC endpoint (Chainstack)
    pub grpc_url: String,
    /// gRPC token (sent as x-token header)
    pub grpc_token: Option<String>,
    /// Kamino main lending program ID
    pub kamino_program_id: Pubkey,
    /// JSONL path for unhealthy obligation events
    pub log_path: PathBuf,
    /// Health factor threshold below which we log (1.0 = liquidatable, 1.05 = early warn)
    pub health_threshold_warn: f64,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let grpc_url = std::env::var("LIQ_GRPC_URL")
            .or_else(|_| std::env::var("CHAINSTACK_GRPC_URL"))
            .context("LIQ_GRPC_URL or CHAINSTACK_GRPC_URL must be set")?;

        let grpc_token = std::env::var("LIQ_GRPC_TOKEN")
            .ok()
            .or_else(|| std::env::var("CHAINSTACK_GRPC_TOKEN").ok());

        let kamino_program_id_str = std::env::var("LIQ_KAMINO_PROGRAM_ID")
            .unwrap_or_else(|_| "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD".to_string());
        let kamino_program_id = Pubkey::from_str(&kamino_program_id_str)
            .context("parsing kamino program id")?;

        let log_path = PathBuf::from(
            std::env::var("LIQ_LOG_PATH")
                .unwrap_or_else(|_| "/home/ubuntu/liquidator_rs/data/unhealthy_positions.jsonl".to_string()),
        );

        let health_threshold_warn: f64 = std::env::var("LIQ_HEALTH_THRESHOLD_WARN")
            .unwrap_or_else(|_| "1.05".to_string())
            .parse()
            .unwrap_or(1.05);

        Ok(Self {
            grpc_url,
            grpc_token,
            kamino_program_id,
            log_path,
            health_threshold_warn,
        })
    }
}


// Per Gemma R12-Q1: scope_prices pubkey for Kamino main market
// (lending_market 7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF)
pub const SCOPE_PRICES: solana_sdk::pubkey::Pubkey =
    solana_sdk::pubkey!("3NJYftD5sjVfxSnUdZ1wVML8f3aC6mp1CXCL6L7TnU8C");

// Switchboard program (used as placeholder for unused switchboard slots
// per Gemma R12-Q2: System Program would trigger Constraint error)
pub const SWITCHBOARD_PROGRAM: solana_sdk::pubkey::Pubkey =
    solana_sdk::pubkey!("SW1TCH7qEPTdLsDHRgPuMQjbQxKdH2aBStViMFnt64f");

// Token-2022 program ID — used to detect/skip T22 reserves on first probe (Gemma R12-Q4)
pub const TOKEN_2022_PROGRAM: solana_sdk::pubkey::Pubkey =
    solana_sdk::pubkey!("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");
