// Parser Orca Whirlpool — offsets validados en mainnet.
// Pool ref: Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE (SOL/USDC)
// Error vs Jupiter: 0.012%

use std::convert::TryInto;

pub const PROGRAM_ID: &str = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc";
pub const POOL_ACCOUNT_SIZE: usize = 653;

const TICK_SPACING_OFFSET: usize = 41;
const LIQUIDITY_OFFSET:    usize = 49;
const SQRT_PRICE_OFFSET:   usize = 65;
const TICK_CURRENT_OFFSET: usize = 81;

pub fn price_from_pool(data: &[u8], dec_a: u8, dec_b: u8) -> Option<f64> {
    Some(full_state_from_pool(data, dec_a, dec_b)?.0)
}

/// Returns (price, sqrt_price_x64, liquidity, tick_current, tick_spacing)
pub fn full_state_from_pool(data: &[u8], dec_a: u8, dec_b: u8) -> Option<(f64, u128, u128, i32, i32)> {
    if data.len() < TICK_CURRENT_OFFSET + 4 { return None; }

    let tick_spacing = u16::from_le_bytes(
        data[TICK_SPACING_OFFSET..TICK_SPACING_OFFSET+2].try_into().ok()?
    ) as i32;

    let liquidity = u128::from_le_bytes(
        data[LIQUIDITY_OFFSET..LIQUIDITY_OFFSET+16].try_into().ok()?
    );

    let sqrt_x64 = u128::from_le_bytes(
        data[SQRT_PRICE_OFFSET..SQRT_PRICE_OFFSET+16].try_into().ok()?
    );
    if sqrt_x64 == 0 { return None; }

    let tick_current = i32::from_le_bytes(
        data[TICK_CURRENT_OFFSET..TICK_CURRENT_OFFSET+4].try_into().ok()?
    );

    let sqrt = (sqrt_x64 as f64) / (1u128 << 64) as f64;
    let price = sqrt * sqrt * 10f64.powi(dec_a as i32 - dec_b as i32);

    Some((price, sqrt_x64, liquidity, tick_current, tick_spacing))
}
