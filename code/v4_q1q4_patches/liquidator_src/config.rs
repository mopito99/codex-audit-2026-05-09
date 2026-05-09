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
    /// Audit r116 Item #2: max debt cap USD for LIVE liquidations (was hardcoded 200.0).
    /// Configurable via LIQ_MAX_DEBT_CAP_USD env var, default 200.0.
    pub max_debt_cap_usd: f64,
    /// Audit r116 Item #2: min estimated profit USD to attempt LIVE liquidation
    /// (was hardcoded 2.0). Configurable via LIQ_MIN_PROFIT_USD, default 2.0.
    /// NOTA r144 Q1: este campo aplica al path LIQUIDATOR (safety/grpc).
    /// Para CYCLIC arb usar `effective_cyclic_min_profit_usd()`.
    pub min_profit_usd: f64,
    /// Audit r116 Item #2: max Jito tip lamports per bundle (was hardcoded 5_000_000).
    /// Configurable via LIQ_MAX_TIP_LAMPORTS, default 5_000_000.
    pub max_tip_lamports: u64,
    /// r144 firma Gemma Q1 — Cyclic LIVE flag (centralizado del env read inline).
    pub cyclic_execute_live: bool,
    /// r144 Q1 — floor profit USD para cyclic SHADOW. Default 0.10
    /// (filtrar ruido, medir universo amplio).
    pub cyclic_min_profit_usd_shadow: f64,
    /// r144 Q1 — floor profit USD para cyclic LIVE. Default 1.00
    /// (Gemma firmó: rechaza CUALQUIER live trade con profit < 1.0).
    pub cyclic_min_profit_usd_live: f64,
}

impl Config {
    /// r144 Q1 — devuelve el floor profit USD efectivo según el modo activo.
    pub fn effective_cyclic_min_profit_usd(&self) -> f64 {
        if self.cyclic_execute_live {
            self.cyclic_min_profit_usd_live
        } else {
            self.cyclic_min_profit_usd_shadow
        }
    }
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

        // r116 Item #2: read configurable risk params (defaults preserve V3.5 behavior)
        let max_debt_cap_usd: f64 = std::env::var("LIQ_MAX_DEBT_CAP_USD")
            .unwrap_or_else(|_| "200.0".to_string())
            .parse()
            .unwrap_or(200.0);
        let min_profit_usd: f64 = std::env::var("LIQ_MIN_PROFIT_USD")
            .unwrap_or_else(|_| "2.0".to_string())
            .parse()
            .unwrap_or(2.0);
        let max_tip_lamports: u64 = std::env::var("LIQ_MAX_TIP_LAMPORTS")
            .unwrap_or_else(|_| "5000000".to_string())
            .parse()
            .unwrap_or(5_000_000);

        // r144 firma Gemma Q1 — Cyclic dynamic profit floor.
        let cyclic_execute_live: bool = std::env::var("LIQ_CYCLIC_EXECUTE_LIVE")
            .map(|v| v == "true" || v == "1")
            .unwrap_or(false);
        let cyclic_min_profit_usd_shadow: f64 = std::env::var("LIQ_MIN_PROFIT_USD_SHADOW")
            .unwrap_or_else(|_| "0.10".to_string())
            .parse()
            .unwrap_or(0.10);
        let cyclic_min_profit_usd_live: f64 = std::env::var("LIQ_MIN_PROFIT_USD_LIVE")
            .unwrap_or_else(|_| "1.00".to_string())
            .parse()
            .unwrap_or(1.00);

        // r144 Q1 FAIL-SAFE: si LIVE flag está activo pero el floor LIVE es <1.00
        // → ABORT boot. Bloqueado por firma Gemma r144.
        if cyclic_execute_live && cyclic_min_profit_usd_live < 1.00 {
            anyhow::bail!(
                "LIQ_MIN_PROFIT_USD_LIVE={:.4} < 1.00 mientras LIQ_CYCLIC_EXECUTE_LIVE=true. \
                 Cambio bloqueado por firma Gemma r144 §Q1. Setear LIQ_MIN_PROFIT_USD_LIVE>=1.00 \
                 o desactivar LIQ_CYCLIC_EXECUTE_LIVE.",
                cyclic_min_profit_usd_live
            );
        }
        // Warning si SHADOW > 1.0 (probablemente confusión de envs).
        if !cyclic_execute_live && cyclic_min_profit_usd_shadow > 1.00 {
            tracing::warn!(
                cyclic_min_profit_usd_shadow,
                "r144 Q1: LIQ_MIN_PROFIT_USD_SHADOW > 1.00 — ¿cambio intencional? \
                 SHADOW debería medir universo amplio."
            );
        }

        Ok(Self {
            grpc_url,
            grpc_token,
            kamino_program_id,
            log_path,
            health_threshold_warn,
            max_debt_cap_usd,
            min_profit_usd,
            max_tip_lamports,
            cyclic_execute_live,
            cyclic_min_profit_usd_shadow,
            cyclic_min_profit_usd_live,
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
