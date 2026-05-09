//! Kamino Obligation account parser.
//!
//! Offsets empirically validated against mainnet account dumps (2026-05-01):
//!   Obligation pubkey: HNr8xya411TAFf23m5CjuwrVzQKGUVGhZtHmmsgrqBVw
//!   Size: 3344 bytes (constant for KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD)
//!
//! Header offsets (confirmed):
//!   [0..8]   discriminator = a8ce8d6a584caca7
//!   [8..16]  tag (u64)
//!   [16..24] last_update.slot (u64)
//!   [32..64] lending_market (Pubkey)
//!   [64..96] owner (Pubkey)
//!
//! Aggregate USD offsets (validated via scan of real account, scale = 2^60):
//!   [2208..2224] deposited_value_sf
//!   [2224..2240] borrowed_value_sf
//!   [2240..2256] borrow_factor_adjusted_debt_sf
//!   [2256..2272] allowed_borrow_value_sf
//!   [2272..2288] unhealthy_borrow_value_sf
//!
//! NOTE: offsets may shift if Kamino upgrades the program and changes struct layout.
//! INVARIANT: discriminator is checked on each parse. If it changes -> Err.

use anyhow::{bail, Context, Result};
use solana_sdk::pubkey::Pubkey;

const EXPECTED_SIZE: usize = 3344;
const DISCRIMINATOR: [u8; 8] = [0xa8, 0xce, 0x8d, 0x6a, 0x58, 0x4c, 0xac, 0xa7];

// Fraction scale: Kamino uses BigFraction = U128 / 2^60
const FRAC_SCALE: f64 = 1.152921504606847e18; // 2_f64.powi(60)

// Aggregate value offsets (empirically validated 2026-05-01)
const OFF_DEPOSITED_VALUE: usize = 2208;
const OFF_BORROWED_VALUE: usize = 2224;
const OFF_BORROW_FACTOR_DEBT: usize = 2240;
const OFF_ALLOWED_BORROW: usize = 2256;
const OFF_UNHEALTHY_BORROW: usize = 2272;

#[derive(Debug, Clone)]
pub struct ParsedObligation {
    pub owner: Pubkey,
    pub owner_b58: String,
    pub lending_market: Pubkey,
    pub last_update_slot: u64,
    pub deposited_value_usd: f64,
    pub borrowed_value_usd: f64,
    pub borrow_factor_adjusted_debt_usd: f64,
    pub allowed_borrow_value_usd: f64,
    pub unhealthy_borrow_value_usd: f64,
    /// HF = allowed_borrow_value / max(borrowed_value, ε).
    /// < 1.0 → liquidatable immediately.
    pub health_factor: f64,
}

pub fn parse_obligation(data: &[u8]) -> Result<ParsedObligation> {
    if data.len() != EXPECTED_SIZE {
        bail!("size mismatch: got {} expected {EXPECTED_SIZE}", data.len());
    }

    // Discriminator guard — if Kamino upgrades layout we fail fast instead of computing garbage.
    if &data[..8] != DISCRIMINATOR {
        bail!("discriminator mismatch: {:x?}", &data[..8]);
    }

    let last_update_slot = u64::from_le_bytes(
        data[16..24].try_into().context("slot slice")?
    );
    let lending_market = Pubkey::new_from_array(
        data[32..64].try_into().context("lending_market slice")?
    );
    let owner_bytes: [u8; 32] = data[64..96].try_into().context("owner slice")?;
    let owner = Pubkey::new_from_array(owner_bytes);
    let owner_b58 = owner.to_string();

    let deposited_value_usd  = sf_to_f64(read_u128(data, OFF_DEPOSITED_VALUE)?);
    let borrowed_value_usd   = sf_to_f64(read_u128(data, OFF_BORROWED_VALUE)?);
    let borrow_factor_adjusted_debt_usd = sf_to_f64(read_u128(data, OFF_BORROW_FACTOR_DEBT)?);
    let allowed_borrow_value_usd = sf_to_f64(read_u128(data, OFF_ALLOWED_BORROW)?);
    let unhealthy_borrow_value_usd = sf_to_f64(read_u128(data, OFF_UNHEALTHY_BORROW)?);

    // Use borrow_factor_adjusted_debt for health factor (matches Kamino's protocol math).
    let health_factor = if borrow_factor_adjusted_debt_usd <= 1e-9 {
        f64::INFINITY
    } else {
        allowed_borrow_value_usd / borrow_factor_adjusted_debt_usd
    };

    Ok(ParsedObligation {
        owner, owner_b58, lending_market, last_update_slot,
        deposited_value_usd, borrowed_value_usd,
        borrow_factor_adjusted_debt_usd,
        allowed_borrow_value_usd, unhealthy_borrow_value_usd,
        health_factor,
    })
}

#[inline]
fn read_u128(data: &[u8], off: usize) -> Result<u128> {
    let s = data.get(off..off+16).with_context(|| format!("u128 oob at {off}"))?;
    Ok(u128::from_le_bytes(s.try_into()?))
}

#[inline]
fn sf_to_f64(v: u128) -> f64 {
    v as f64 / FRAC_SCALE
}


// Empirically validated against Obligation kgpZaovQNKALCNyxUFuoPj4kSqm6YQz5H4qXgM5p61d:
//   deposits[0].deposit_reserve at offset 96
//   borrows[0].borrow_reserve   at offset 1208
// MAX_OBLIGATION_DEPOSITS = 8, sizeof(ObligationCollateral) = 139 bytes
// MAX_OBLIGATION_BORROWS  = 5  (deduced)
const OFF_DEPOSITS_ARRAY_START: usize = 96;
const OBLIGATION_COLLATERAL_SIZE: usize = 139;
const MAX_DEPOSITS: usize = 8;
const OFF_BORROWS_ARRAY_START: usize = 1208;
const OBLIGATION_LIQUIDITY_SIZE: usize = 200; // tentative — to validate
const MAX_BORROWS: usize = 5;

/// Extract the first non-empty (deposit_reserve, borrow_reserve) tuple.
/// For most positions this is the only deposit and only borrow; multi-asset
/// obligations will need a richer scanner in M2.
pub fn extract_first_reserves(data: &[u8]) -> Result<(Pubkey, Pubkey)> {
    if data.len() != EXPECTED_SIZE {
        bail!("size mismatch");
    }

    let mut deposit_reserve = None;
    for i in 0..MAX_DEPOSITS {
        let off = OFF_DEPOSITS_ARRAY_START + i * OBLIGATION_COLLATERAL_SIZE;
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            deposit_reserve = Some(Pubkey::new_from_array(bytes));
            break;
        }
    }

    let mut borrow_reserve = None;
    for i in 0..MAX_BORROWS {
        let off = OFF_BORROWS_ARRAY_START + i * OBLIGATION_LIQUIDITY_SIZE;
        if off + 32 > data.len() { break; }
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            borrow_reserve = Some(Pubkey::new_from_array(bytes));
            break;
        }
    }

    let dr = deposit_reserve.context("no deposit reserve found in obligation")?;
    let br = borrow_reserve.context("no borrow reserve found in obligation")?;
    Ok((dr, br))
}


/// Count the number of non-zero deposits and borrows in an Obligation.
/// Used by the probe-mode filter to skip multi-asset obligations
/// (Gemma R17 CRITICAL #3 — extract_first_reserves only handles 1+1).
pub fn count_deposits_borrows(data: &[u8]) -> Result<(usize, usize)> {
    if data.len() != EXPECTED_SIZE {
        bail!("size mismatch");
    }
    let mut deposits = 0;
    for i in 0..MAX_DEPOSITS {
        let off = OFF_DEPOSITS_ARRAY_START + i * OBLIGATION_COLLATERAL_SIZE;
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            deposits += 1;
        }
    }
    let mut borrows = 0;
    for i in 0..MAX_BORROWS {
        let off = OFF_BORROWS_ARRAY_START + i * OBLIGATION_LIQUIDITY_SIZE;
        if off + 32 > data.len() { break; }
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            borrows += 1;
        }
    }
    Ok((deposits, borrows))
}


/// Extract ALL non-zero deposit and borrow reserves from an Obligation.
/// Required by refresh_obligation which expects exact match with obligation state.
pub fn extract_all_reserves(data: &[u8]) -> Result<(Vec<Pubkey>, Vec<Pubkey>)> {
    if data.len() != EXPECTED_SIZE {
        bail!("size mismatch");
    }
    let mut deposits = Vec::new();
    for i in 0..MAX_DEPOSITS {
        let off = OFF_DEPOSITS_ARRAY_START + i * OBLIGATION_COLLATERAL_SIZE;
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            deposits.push(Pubkey::new_from_array(bytes));
        }
    }
    let mut borrows = Vec::new();
    for i in 0..MAX_BORROWS {
        let off = OFF_BORROWS_ARRAY_START + i * OBLIGATION_LIQUIDITY_SIZE;
        if off + 32 > data.len() { break; }
        let bytes: [u8; 32] = data[off..off+32].try_into().unwrap();
        if bytes != [0u8; 32] {
            borrows.push(Pubkey::new_from_array(bytes));
        }
    }
    Ok((deposits, borrows))
}
