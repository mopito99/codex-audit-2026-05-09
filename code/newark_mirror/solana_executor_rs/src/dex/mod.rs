// Módulo dex — parsers nativos + traversal exacto + loader TickArrays.

pub mod raydium_clmm;
pub mod orca_whirlpool;
pub mod clmm_tick_traversal;
pub mod tickarray_loader;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DexType {
    RaydiumClmm,
    OrcaWhirlpool,
}

pub struct FullPoolState {
    pub price: f64,
    pub sqrt_price_x64: u128,
    pub liquidity: u128,
    pub tick_current: i32,
    pub tick_spacing: i32,
}

pub fn parse_price(dex: DexType, data: &[u8], dec0: u8, dec1: u8) -> Option<f64> {
    Some(parse_full_state(dex, data, dec0, dec1)?.price)
}

pub fn parse_full_state(dex: DexType, data: &[u8], dec0: u8, dec1: u8) -> Option<FullPoolState> {
    let (price, sqrt_price_x64, liquidity, tick_current, tick_spacing) = match dex {
        DexType::RaydiumClmm  => raydium_clmm::full_state_from_pool(data, dec0, dec1)?,
        DexType::OrcaWhirlpool => orca_whirlpool::full_state_from_pool(data, dec0, dec1)?,
    };
    Some(FullPoolState { price, sqrt_price_x64, liquidity, tick_current, tick_spacing })
}

pub fn pool_size(dex: DexType) -> usize {
    match dex {
        DexType::RaydiumClmm  => raydium_clmm::POOL_ACCOUNT_SIZE,
        DexType::OrcaWhirlpool => orca_whirlpool::POOL_ACCOUNT_SIZE,
    }
}
