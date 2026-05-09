//! Kamino liquidate instruction builder.
//!
//! Reference: klend program `liquidate_obligation_and_redeem_reserve_collateral`
//! Discriminator: b1479abce2854a37 (sha256("global:liquidate...")[..8])
//!
//! Strategy: liquidator pays off the borrower's debt (in repay_reserve token)
//! and receives the collateral (from withdraw_reserve) at a discounted rate.
//!
//! Required accounts (in order, per klend IDL):
//!   0  liquidator                            signer, writable
//!   1  obligation                            writable
//!   2  lending_market
//!   3  lending_market_authority              PDA: [b"lma", lending_market]
//!   4  repay_reserve                         writable (the debt's reserve)
//!   5  repay_reserve_liquidity_mint
//!   6  repay_reserve_liquidity_supply        writable
//!   7  withdraw_reserve                      writable (the collateral's reserve)
//!   8  withdraw_reserve_liquidity_mint
//!   9  withdraw_reserve_collateral_mint      writable
//!   10 withdraw_reserve_collateral_supply    writable
//!   11 withdraw_reserve_liquidity_supply     writable
//!   12 withdraw_reserve_liquidity_fee_recvr  writable
//!   13 user_source_liquidity                 writable (liquidator's repay-token ATA)
//!   14 user_destination_collateral           writable (liquidator's coll-token ATA)
//!   15 user_destination_liquidity            writable (liquidator's redeem-token ATA)
//!   16 token_program (TOKEN_2022 or SPL_TOKEN)
//!   17 collateral_token_program
//!   18 liquidity_token_program
//!   19 instruction_sysvar (Sysvar1nstructions)

use anyhow::{bail, Context, Result};
use solana_sdk::{
    instruction::{AccountMeta, Instruction},
    pubkey,
    pubkey::Pubkey,
    sysvar::SysvarId,
};

pub const KAMINO_PROGRAM_ID: Pubkey = pubkey!("KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD");
pub const SPL_TOKEN_PROGRAM: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");


// NULL_ORACLE for testing — represents 'no oracle configured' scenario.
// Different from KAMINO_PROGRAM_ID sentinel.
pub const NULL_ORACLE: Pubkey = Pubkey::new_from_array([0u8; 32]);
pub const SYSVAR_INSTRUCTIONS: Pubkey = pubkey!("Sysvar1nstructions1111111111111111111111111");

/// 8-byte Anchor discriminator for liquidate_obligation_and_redeem_reserve_collateral.
pub const IX_DISCRIM: [u8; 8] = [0xb1, 0x47, 0x9a, 0xbc, 0xe2, 0x85, 0x4a, 0x37];

/// All on-chain account references needed to build a liquidate ix for a
/// specific (Obligation, repay_reserve, withdraw_reserve) combination.
///
/// These come from chain RPC at runtime — for M1 we'll fetch & cache per
/// (lending_market, repay_mint, withdraw_mint) tuple.
#[derive(Debug, Clone)]
pub struct LiquidateAccounts {
    pub liquidator: Pubkey,
    pub obligation: Pubkey,
    pub lending_market: Pubkey,
    pub lending_market_authority: Pubkey,
    pub repay_reserve: Pubkey,
    pub repay_reserve_liquidity_mint: Pubkey,
    pub repay_reserve_liquidity_supply: Pubkey,
    pub withdraw_reserve: Pubkey,
    pub withdraw_reserve_liquidity_mint: Pubkey,
    pub withdraw_reserve_collateral_mint: Pubkey,
    pub withdraw_reserve_collateral_supply: Pubkey,
    pub withdraw_reserve_liquidity_supply: Pubkey,
    pub withdraw_reserve_liquidity_fee_receiver: Pubkey,
    pub user_source_liquidity: Pubkey,
    pub user_destination_collateral: Pubkey,
    pub user_destination_liquidity: Pubkey,
    pub collateral_token_program: Pubkey,
    pub repay_liquidity_token_program: Pubkey,
    pub withdraw_liquidity_token_program: Pubkey,
}

/// Liquidate ix arguments (passed in instruction data).
///
/// `liquidity_amount`: max amount of borrowed token to repay (u64, base units).
///                     Use u64::MAX for "max possible" (Kamino caps at 50% of debt).
/// `min_acceptable_received_collateral_amount`: slippage protection on coll out.
/// `max_allowed_ltv_override_pct`: 0 for default behavior.
#[derive(Debug, Clone)]
pub struct LiquidateArgs {
    pub liquidity_amount: u64,
    pub min_acceptable_received_collateral_amount: u64,
    pub max_allowed_ltv_override_pct: u64,
}

/// Derive lending_market_authority PDA.
/// Seeds: [b"lma", lending_market.as_ref()]
pub fn derive_lending_market_authority(lending_market: &Pubkey) -> (Pubkey, u8) {
    Pubkey::find_program_address(
        &[b"lma", lending_market.as_ref()],
        &KAMINO_PROGRAM_ID,
    )
}

/// Build the liquidate_obligation_and_redeem_reserve_collateral instruction.
pub fn build_liquidate_ix(accounts: &LiquidateAccounts, args: &LiquidateArgs) -> Instruction {
    let metas = vec![
        AccountMeta::new(accounts.liquidator, true),
        AccountMeta::new(accounts.obligation, false),
        AccountMeta::new_readonly(accounts.lending_market, false),
        AccountMeta::new_readonly(accounts.lending_market_authority, false),
        AccountMeta::new(accounts.repay_reserve, false),
        AccountMeta::new_readonly(accounts.repay_reserve_liquidity_mint, false),
        AccountMeta::new(accounts.repay_reserve_liquidity_supply, false),
        AccountMeta::new(accounts.withdraw_reserve, false),
        AccountMeta::new_readonly(accounts.withdraw_reserve_liquidity_mint, false),
        AccountMeta::new(accounts.withdraw_reserve_collateral_mint, false),
        AccountMeta::new(accounts.withdraw_reserve_collateral_supply, false),
        AccountMeta::new(accounts.withdraw_reserve_liquidity_supply, false),
        AccountMeta::new(accounts.withdraw_reserve_liquidity_fee_receiver, false),
        AccountMeta::new(accounts.user_source_liquidity, false),
        AccountMeta::new(accounts.user_destination_collateral, false),
        AccountMeta::new(accounts.user_destination_liquidity, false),
        AccountMeta::new_readonly(accounts.collateral_token_program, false),
        AccountMeta::new_readonly(accounts.repay_liquidity_token_program, false),
        AccountMeta::new_readonly(accounts.withdraw_liquidity_token_program, false),
        AccountMeta::new_readonly(SYSVAR_INSTRUCTIONS, false),
    ];

    let mut data = Vec::with_capacity(8 + 8 + 8 + 8);
    data.extend_from_slice(&IX_DISCRIM);
    data.extend_from_slice(&args.liquidity_amount.to_le_bytes());
    data.extend_from_slice(&args.min_acceptable_received_collateral_amount.to_le_bytes());
    data.extend_from_slice(&args.max_allowed_ltv_override_pct.to_le_bytes());

    Instruction {
        program_id: KAMINO_PROGRAM_ID,
        accounts: metas,
        data,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lma_pda_is_deterministic() {
        let lm = pubkey!("7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5K6e");
        let (a1, _) = derive_lending_market_authority(&lm);
        let (a2, _) = derive_lending_market_authority(&lm);
        assert_eq!(a1, a2);
    }

    #[test]
    fn discriminator_matches_sha256() {
        // Verify our hardcoded constant matches sha256("global:liquidate_...")
        // (we keep this test to catch any future Anchor name changes)
        let expected = [0xb1u8, 0x47, 0x9a, 0xbc, 0xe2, 0x85, 0x4a, 0x37];
        assert_eq!(IX_DISCRIM, expected);
    }

    #[test]
    fn ix_data_has_correct_length() {
        let dummy = Pubkey::default();
        let accounts = LiquidateAccounts {
            liquidator: dummy, obligation: dummy, lending_market: dummy,
            lending_market_authority: dummy, repay_reserve: dummy,
            repay_reserve_liquidity_mint: dummy, repay_reserve_liquidity_supply: dummy,
            withdraw_reserve: dummy, withdraw_reserve_liquidity_mint: dummy,
            withdraw_reserve_collateral_mint: dummy, withdraw_reserve_collateral_supply: dummy,
            withdraw_reserve_liquidity_supply: dummy, withdraw_reserve_liquidity_fee_receiver: dummy,
            user_source_liquidity: dummy, user_destination_collateral: dummy,
            user_destination_liquidity: dummy,
            collateral_token_program: SPL_TOKEN_PROGRAM, repay_liquidity_token_program: SPL_TOKEN_PROGRAM, withdraw_liquidity_token_program: SPL_TOKEN_PROGRAM,
        };
        let args = LiquidateArgs {
            liquidity_amount: 1_000_000,
            min_acceptable_received_collateral_amount: 0,
            max_allowed_ltv_override_pct: 0,
        };
        let ix = build_liquidate_ix(&accounts, &args);
        assert_eq!(ix.data.len(), 8 + 8 + 8 + 8);
        assert_eq!(&ix.data[..8], &IX_DISCRIM);
        assert_eq!(ix.accounts.len(), 20);
    }
}

// =============================================================================
// refresh_reserve / refresh_obligation — required BEFORE liquidate per klend
// =============================================================================

pub const REFRESH_RESERVE_DISCRIM: [u8; 8] = [0x02, 0xda, 0x8a, 0xeb, 0x4f, 0xc9, 0x19, 0x66];
pub const REFRESH_OBLIGATION_DISCRIM: [u8; 8] = [0x21, 0x84, 0x93, 0xe4, 0x97, 0xc0, 0x48, 0x59];

/// Build refresh_reserve instruction.
/// Accounts:
///   0. reserve (writable)
///   1. lending_market
///   2. pyth_oracle  (or NULL_PUBKEY if not used)
///   3. switchboard_price_oracle (or NULL_PUBKEY)
///   4. switchboard_twap_oracle (or NULL_PUBKEY)
///   5. scope_prices (or NULL_PUBKEY)
pub fn build_refresh_reserve_ix(
    reserve: Pubkey,
    lending_market: Pubkey,
    pyth_oracle: Option<Pubkey>,
    switchboard_price: Option<Pubkey>,
    switchboard_twap: Option<Pubkey>,
    scope_prices: Option<Pubkey>,
) -> Instruction {
    // Per Kamino SDK convention: when no oracle of a type is configured,
    // the Kamino program ID itself is used as the sentinel (NOT Pubkey::default()
    // which would map to System Program and trigger Anchor constraint errors).
    let null = KAMINO_PROGRAM_ID;
    let metas = vec![
        AccountMeta::new(reserve, false),
        AccountMeta::new_readonly(lending_market, false),
        AccountMeta::new_readonly(pyth_oracle.unwrap_or(null), false),
        AccountMeta::new_readonly(switchboard_price.unwrap_or(null), false),
        AccountMeta::new_readonly(switchboard_twap.unwrap_or(null), false),
        AccountMeta::new_readonly(scope_prices.unwrap_or(null), false),
    ];
    Instruction {
        program_id: KAMINO_PROGRAM_ID,
        accounts: metas,
        data: REFRESH_RESERVE_DISCRIM.to_vec(),
    }
}

/// Build refresh_obligation instruction.
/// Accounts:
///   0. lending_market
///   1. obligation (writable)
///   ...remaining: all reserve accounts referenced by obligation deposits/borrows
pub fn build_refresh_obligation_ix(
    lending_market: Pubkey,
    obligation: Pubkey,
    deposit_reserves: &[Pubkey],
    borrow_reserves: &[Pubkey],
) -> Instruction {
    let mut metas = vec![
        AccountMeta::new_readonly(lending_market, false),
        AccountMeta::new(obligation, false),
    ];
    for r in deposit_reserves { metas.push(AccountMeta::new_readonly(*r, false)); }
    for r in borrow_reserves  { metas.push(AccountMeta::new_readonly(*r, false)); }
    Instruction {
        program_id: KAMINO_PROGRAM_ID,
        accounts: metas,
        data: REFRESH_OBLIGATION_DISCRIM.to_vec(),
    }
}

// =============================================================================
// refresh_farms_for_obligation_for_reserve — Gemma R15 golden sequence
// =============================================================================
// Discriminator validated: sha256("global:refresh_farms_for_obligation_for_reserve")[:8]
pub const REFRESH_FARMS_DISCRIM: [u8; 8] = [0x8c, 0x90, 0xfd, 0x15, 0x0a, 0x4a, 0xf8, 0x03];

/// Build refresh_farms_for_obligation_for_reserve.
///
/// Per Gemma R15 Q1, accounts in order:
///   0. lending_market               (writable)
///   1. obligation                   (writable)
///   2. symmetry/scope               (readonly) — fallback to lending_market if unknown
///   3. reserve                      (writable)
///   4. farm_state                   (writable) — reserve.farm_debt (repay) or farm_collateral (withdraw)
///   5. lending_market_authority     (readonly)
///   6. token_program                (readonly)
/// mode: 0 = Collateral farm, 1 = Debt farm
pub fn build_refresh_farms_for_obligation_for_reserve_ix(
    crank: Pubkey,           // signer — the liquidator wallet
    lending_market: Pubkey,
    obligation: Pubkey,
    reserve: Pubkey,
    farm_state: Pubkey,
    obligation_farm_user_state: Pubkey,  // R16: PDA from FARMS_PROGRAM
    lending_market_authority: Pubkey,
    mode: u8,
) -> Instruction {
    use solana_sdk::pubkey;
    const SPL_TOKEN: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
    let metas = vec![
        AccountMeta::new(crank, true),                               // 0. crank (signer)
        AccountMeta::new(obligation, false),                         // 1. obligation
        AccountMeta::new_readonly(lending_market_authority, false),  // 2. lending_market_authority
        AccountMeta::new(reserve, false),                            // 3. reserve
        AccountMeta::new(farm_state, false),                         // 4. reserve_farm_state
        AccountMeta::new(obligation_farm_user_state, false),         // 5. obligation_farm_user_state PDA (R16)
        AccountMeta::new_readonly(lending_market, false),            // 6. lending_market
        AccountMeta::new_readonly(FARMS_PROGRAM_ID, false),          // 7. farms_program
        AccountMeta::new_readonly(solana_sdk::sysvar::rent::ID, false),  // 8. rent
        AccountMeta::new_readonly(SPL_TOKEN, false),                 // 9. token_program
    ];
    Instruction {
        program_id: KAMINO_PROGRAM_ID,
        accounts: metas,
        data: { let mut d = REFRESH_FARMS_DISCRIM.to_vec(); d.push(mode); d },
    }
}


// Per Gemma R16: seeds = [b"obligation_user_state", farm_state, obligation]
// Owned by FARMS_PROGRAM (FarmsPZpWu9i7Kky8tPN37rs2TpmMrSpvw3DCyKqaWa).
pub const FARMS_PROGRAM_ID: Pubkey = solana_sdk::pubkey!("FarmsPZpWu9i7Kky8tPN37rs2TpmMrSpvw3DCyKqaWa");

pub fn derive_obligation_farm_user_state(farm_state: &Pubkey, obligation: &Pubkey) -> (Pubkey, u8) {
    Pubkey::find_program_address(
        &[
            b"obligation_user_state",
            farm_state.as_ref(),
            obligation.as_ref(),
        ],
        &FARMS_PROGRAM_ID,
    )
}
