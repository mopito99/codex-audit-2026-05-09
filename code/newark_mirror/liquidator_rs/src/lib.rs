//! liquidator_rs library — exposes modules for use by binaries.

pub mod ata;
pub mod config;
pub mod jito;
pub mod kamino;
pub mod logger;
pub mod rpc;
pub mod safety;
pub mod simulator;
pub mod wallet;
pub mod cyclic_dispatch;
pub mod alt_cache;
pub mod bot_detector;
pub mod circuit_breaker;
pub mod tip_stream;
pub mod priority_fee;
pub mod tip_manager;
pub mod wallet_rotator;
pub mod telegram_listener;
pub mod stats;
pub mod telemetry;
pub mod lr_tracker;
pub mod wallet_monitor;
pub mod rugcheck;
pub mod pool_registry;
pub mod safety_worker;
pub mod pyth_oracle;
pub mod pyth_hermes;
pub mod observability;
pub mod wallet_query;

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ObligationEvent {
    pub ts: chrono::DateTime<chrono::Utc>,
    pub slot: u64,
    pub pubkey: String,
    pub owner: String,
    pub deposited_value_usd: f64,
    pub borrowed_value_usd: f64,
    pub allowed_borrow_value_usd: f64,
    pub unhealthy_borrow_value_usd: f64,
    pub health_factor: f64,
    pub liquidatable: bool,
}
