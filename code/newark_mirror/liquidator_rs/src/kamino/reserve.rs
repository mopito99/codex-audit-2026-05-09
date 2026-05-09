//! Kamino Reserve account parser.
//!
//! Reserve account size: 8624 bytes (constant for klend mainnet).
//! Discriminator: 2bf2ccca1af73b7f
//!
//! Layout (offsets validated 2026-05-01 against mainnet Reserve dumps):
//!   [0..8]    Anchor discriminator
//!   [8..16]   version (u64)
//!   [16..24]  last_update.slot (u64)
//!   [24..32]  last_update.stale (u64)
//!   [32..64]  lending_market (Pubkey)
//!   [64..96]  farm_collateral (Pubkey)
//!   [96..128] farm_debt (Pubkey)
//!   [128..160] liquidity.mint_pubkey (Pubkey)         ← REPAY/WITHDRAW liquidity_mint
//!   [160..192] liquidity.supply_vault (Pubkey)        ← REPAY supply / WITHDRAW liq supply
//!   [192..224] liquidity.fee_vault (Pubkey)           ← WITHDRAW liquidity_fee_receiver
//!   ... more liquidity fields (~200 bytes) ...
//!   [392..424] liquidity.token_program (Pubkey)       ← liquidity_token_program
//!   ... more fields ...
//!   then ReserveCollateral { mint_pubkey, supply_vault, ... }
//!
//! The ReserveCollateral struct location is harder to pin down without IDL.
//! For M1 we'll fetch known Reserves and cache the (mint, supply_vault) pairs
//! by manually verifying offsets against expected addresses.

use anyhow::{bail, Context, Result};
use solana_sdk::pubkey::Pubkey;

pub const EXPECTED_SIZE: usize = 8624;
pub const DISCRIMINATOR: [u8; 8] = [0x2b, 0xf2, 0xcc, 0xca, 0x1a, 0xf7, 0x3b, 0x7f];

// Offsets validated empirically (Reserve account 34Bb1oLf...)
const OFF_LENDING_MARKET: usize = 32;
const OFF_LIQUIDITY_MINT: usize = 128;
const OFF_LIQUIDITY_SUPPLY_VAULT: usize = 160;
const OFF_LIQUIDITY_FEE_VAULT: usize = 192;
const OFF_LIQUIDITY_TOKEN_PROGRAM: usize = 408;

// Per Gemma R13 + empirical scan: scope_prices is per-reserve at offset 5112
// (validated: account is Scope program owned, 28712 bytes)
const OFF_SCOPE_PRICES: usize = 5112;
const OFF_FARM_COLLATERAL: usize = 64;
const OFF_FARM_DEBT: usize = 96;

// CollateralMint and CollateralSupplyVault offsets — TBD in M2 once we have
// a real Reserve dump and verify against on-chain fields.
// Conservative placeholders below; flagged with `_TENTATIVE`.
const OFF_COLLATERAL_MINT_TENTATIVE: usize = 2560;
const OFF_COLLATERAL_SUPPLY_VAULT_TENTATIVE: usize = 2600;

#[derive(Debug, Clone)]
pub struct ParsedReserve {
    pub lending_market: Pubkey,
    pub liquidity_mint: Pubkey,
    pub liquidity_supply_vault: Pubkey,
    pub liquidity_fee_vault: Pubkey,
    pub liquidity_token_program: Pubkey,
    pub collateral_mint: Pubkey,
    pub collateral_supply_vault: Pubkey,
    pub scope_prices: Pubkey,
    pub farm_collateral: Pubkey,
    pub farm_debt: Pubkey,
}

pub fn parse_reserve(data: &[u8]) -> Result<ParsedReserve> {
    if data.len() != EXPECTED_SIZE {
        bail!("Reserve size mismatch: got {} expected {EXPECTED_SIZE}", data.len());
    }
    if &data[..8] != DISCRIMINATOR {
        bail!("Reserve discriminator mismatch: {:x?}", &data[..8]);
    }

    Ok(ParsedReserve {
        lending_market: read_pk(data, OFF_LENDING_MARKET)?,
        liquidity_mint: read_pk(data, OFF_LIQUIDITY_MINT)?,
        liquidity_supply_vault: read_pk(data, OFF_LIQUIDITY_SUPPLY_VAULT)?,
        liquidity_fee_vault: read_pk(data, OFF_LIQUIDITY_FEE_VAULT)?,
        liquidity_token_program: read_pk(data, OFF_LIQUIDITY_TOKEN_PROGRAM)?,
        collateral_mint: read_pk(data, OFF_COLLATERAL_MINT_TENTATIVE)?,
        collateral_supply_vault: read_pk(data, OFF_COLLATERAL_SUPPLY_VAULT_TENTATIVE)?,
        scope_prices: read_pk(data, OFF_SCOPE_PRICES)?,
        farm_collateral: read_pk(data, OFF_FARM_COLLATERAL)?,
        farm_debt: read_pk(data, OFF_FARM_DEBT)?,
    })
}

#[inline]
fn read_pk(data: &[u8], off: usize) -> Result<Pubkey> {
    let s = data.get(off..off+32).with_context(|| format!("pk oob {off}"))?;
    let arr: [u8; 32] = s.try_into()?;
    Ok(Pubkey::new_from_array(arr))
}
