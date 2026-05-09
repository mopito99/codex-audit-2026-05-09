//! PoolState: in-memory mirror of CLMM pools, decoded from on-chain account data.
//!
//! Orca Whirlpool offsets validated empirically (G33):
//!   liquidity     (u128) at bytes [49..65]
//!   sqrt_price_x64 (u128) at bytes [65..81]
//!   tick_current   (i32)  at bytes [81..85]
//!
//! Raydium CLMM offsets are TODO (different layout, requires validation against
//! a real account dump before going live).

use crate::config::PoolKind;
use anyhow::{anyhow, Result};
use solana_sdk::pubkey::Pubkey;

#[derive(Debug, Clone)]
pub struct PoolState {
    pub address: Pubkey,
    pub kind: PoolKind,
    pub label: String,
    pub liquidity: u128,
    pub sqrt_price_x64: u128,
    pub tick_current: i32,
    pub slot: u64,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl PoolState {
    /// price (token_b per token_a) = (sqrt_price_x64 / 2^64)^2
    pub fn price_raw_f64(&self) -> f64 {
        let q = (self.sqrt_price_x64 as f64) / (1u128 << 64) as f64;
        q * q
    }
}

pub fn decode(
    address: Pubkey,
    label: &str,
    kind: PoolKind,
    data: &[u8],
    slot: u64,
) -> Result<PoolState> {
    match kind {
        PoolKind::OrcaWhirlpool => decode_orca(address, label, data, slot),
        PoolKind::RaydiumClmm => decode_raydium(address, label, data, slot),
    }
}

fn read_u128_le(data: &[u8], off: usize) -> Result<u128> {
    let bytes: [u8; 16] = data
        .get(off..off + 16)
        .ok_or_else(|| anyhow!("short data at offset {off}"))?
        .try_into()
        .map_err(|_| anyhow!("u128 slice convert"))?;
    Ok(u128::from_le_bytes(bytes))
}

fn read_i32_le(data: &[u8], off: usize) -> Result<i32> {
    let bytes: [u8; 4] = data
        .get(off..off + 4)
        .ok_or_else(|| anyhow!("short data at offset {off}"))?
        .try_into()
        .map_err(|_| anyhow!("i32 slice convert"))?;
    Ok(i32::from_le_bytes(bytes))
}

fn decode_orca(
    address: Pubkey,
    label: &str,
    data: &[u8],
    slot: u64,
) -> Result<PoolState> {
    // Orca Whirlpool account is ~653 bytes; reject anything obviously wrong.
    if data.len() < 261 {
        return Err(anyhow!("orca whirlpool data too short: {}", data.len()));
    }
    let liquidity = read_u128_le(data, 49)?;
    let sqrt_price_x64 = read_u128_le(data, 65)?;
    let tick_current = read_i32_le(data, 81)?;
    Ok(PoolState {
        address,
        kind: PoolKind::OrcaWhirlpool,
        label: label.to_string(),
        liquidity,
        sqrt_price_x64,
        tick_current,
        slot,
        updated_at: chrono::Utc::now(),
    })
}

fn decode_raydium(
    address: Pubkey,
    label: &str,
    data: &[u8],
    slot: u64,
) -> Result<PoolState> {
    // Raydium CLMM PoolState layout (R27 Q7 confirmed by Gemma):
    //   disc(8) + bump(1) + amm_config(32) + owner(32) +
    //   token_mint_0(32) + token_mint_1(32) +
    //   token_vault_0(32) + token_vault_1(32) + observation_key(32) +
    //   mint_decimals_0(1) + mint_decimals_1(1) + tick_spacing(2)
    //   = 237 byte header
    //   liquidity      (u128) at offset 237
    //   sqrt_price_x64 (u128) at offset 253
    //   tick_current   (i32)  at offset 269
    if data.len() < 273 {
        return Err(anyhow!("raydium clmm data too short: {}", data.len()));
    }
    let liquidity      = read_u128_le(data, 237)?;
    let sqrt_price_x64 = read_u128_le(data, 253)?;
    let tick_current   = read_i32_le (data, 269)?;
    Ok(PoolState {
        address,
        kind: PoolKind::RaydiumClmm,
        label: label.to_string(),
        liquidity,
        sqrt_price_x64,
        tick_current,
        slot,
        updated_at: chrono::Utc::now(),
    })
}

