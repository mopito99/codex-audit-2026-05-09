// Tipos compartidos del pipeline event-driven
use solana_sdk::pubkey::Pubkey;

#[derive(Clone, Copy, Debug)]
pub struct PoolState {
    pub price: f64,
    pub liquidity: u128,
    pub last_update_slot: u64,
    pub last_update_at: std::time::Instant,
}

#[derive(Clone, Debug)]
pub struct PoolUpdate {
    pub pool: Pubkey,
    pub data: Vec<u8>,
    pub slot: u64,
}

#[derive(Clone, Debug)]
pub struct Opportunity {
    pub route_id: u32,
    pub expected_profit_usdc: f64,
    pub detected_at: std::time::Instant,
}
