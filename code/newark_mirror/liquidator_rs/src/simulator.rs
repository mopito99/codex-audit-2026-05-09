//! Liquidation simulator + executor pipeline.
//!
//! Per Gemma R12 final approval, the bundle now includes:
//!   1. refresh_reserve(repay)     — uses scope_prices + switchboard placeholder
//!   2. refresh_reserve(withdraw)
//!   3. refresh_obligation
//!   4. liquidate_obligation_and_redeem_reserve_collateral
//!
//! Per Gemma R12-Q4: skips Token-2022 reserves on first probe to avoid T22 risk.
//! ATAs are NOT created here (per Gemma R11-Q5: pre-created via setup_atas binary).

use anyhow::{bail, Context, Result};
use base64::Engine;
use solana_sdk::{
    instruction::Instruction, message::v0::Message, message::VersionedMessage,
    pubkey::Pubkey, transaction::VersionedTransaction,
};
use tracing::{info, warn};

use crate::ata::{create_ata_idempotent_ix, derive_ata, SPL_TOKEN_PROGRAM};
use crate::config::{SCOPE_PRICES, SWITCHBOARD_PROGRAM, TOKEN_2022_PROGRAM};
use crate::kamino::{accounts as obl, ix as kix, reserve as kres};
use crate::rpc::{RpcClient, SimulationResult};
use crate::wallet::HotWallet;

#[derive(Debug)]
pub struct LiquidationPlan {
    pub obligation: Pubkey,
    pub repay_reserve: Pubkey,
    pub withdraw_reserve: Pubkey,
    pub repay_mint: Pubkey,
    pub withdraw_mint: Pubkey,
    pub liquidator_repay_ata: Pubkey,
    pub liquidator_collateral_ata: Pubkey,
    pub liquidator_withdraw_ata: Pubkey,
    pub liquidity_amount: u64,
    pub repay_scope_prices: Pubkey,
    pub withdraw_scope_prices: Pubkey,
    pub repay_farm_debt: Pubkey,
    pub withdraw_farm_collateral: Pubkey,
}

pub async fn plan_liquidation(
    rpc: &RpcClient,
    wallet: &HotWallet,
    obligation_pubkey: Pubkey,
    obligation_data: &[u8],
) -> Result<(LiquidationPlan, kix::LiquidateAccounts, kres::ParsedReserve, kres::ParsedReserve)> {
    let (deposit_reserve_pk, borrow_reserve_pk) = obl::extract_first_reserves(obligation_data)
        .context("extracting first reserves from obligation")?;

    info!(deposit = %deposit_reserve_pk, borrow = %borrow_reserve_pk, "extracted reserves from obligation");

    let withdraw_reserve_pk = deposit_reserve_pk;
    let repay_reserve_pk    = borrow_reserve_pk;

    let (rep_data, wd_data) = tokio::join!(
        rpc.get_account_data(&repay_reserve_pk),
        rpc.get_account_data(&withdraw_reserve_pk),
    );
    let rep_data = rep_data?.context("repay reserve not found on-chain")?;
    let wd_data  = wd_data?.context("withdraw reserve not found on-chain")?;

    let repay = kres::parse_reserve(&rep_data).context("parse repay reserve")?;
    let withdraw = kres::parse_reserve(&wd_data).context("parse withdraw reserve")?;

    // Gemma R12-Q4: skip Token-2022 mints on first probe
    if repay.liquidity_token_program == TOKEN_2022_PROGRAM
        || withdraw.liquidity_token_program == TOKEN_2022_PROGRAM {
        bail!("Token-2022 reserve detected — skipping per Gemma R12-Q4 first-probe policy");
    }

    let (lma, _bump) = kix::derive_lending_market_authority(&repay.lending_market);

    let liquidator_repay_ata = derive_ata(
        &wallet.pubkey, &repay.liquidity_mint, &repay.liquidity_token_program);
    let liquidator_collateral_ata = derive_ata(
        &wallet.pubkey, &withdraw.collateral_mint, &SPL_TOKEN_PROGRAM);
    let liquidator_withdraw_ata = derive_ata(
        &wallet.pubkey, &withdraw.liquidity_mint, &withdraw.liquidity_token_program);

    let plan = LiquidationPlan {
        obligation: obligation_pubkey,
        repay_reserve: repay_reserve_pk,
        withdraw_reserve: withdraw_reserve_pk,
        repay_mint: repay.liquidity_mint,
        withdraw_mint: withdraw.liquidity_mint,
        liquidator_repay_ata,
        liquidator_collateral_ata,
        liquidator_withdraw_ata,
        liquidity_amount: u64::MAX,
        repay_scope_prices: repay.scope_prices,
        withdraw_scope_prices: withdraw.scope_prices,
        repay_farm_debt: repay.farm_debt,
        withdraw_farm_collateral: withdraw.farm_collateral,
    };

    let accounts = kix::LiquidateAccounts {
        liquidator: wallet.pubkey,
        obligation: obligation_pubkey,
        lending_market: repay.lending_market,
        lending_market_authority: lma,
        repay_reserve: repay_reserve_pk,
        repay_reserve_liquidity_mint: repay.liquidity_mint,
        repay_reserve_liquidity_supply: repay.liquidity_supply_vault,
        withdraw_reserve: withdraw_reserve_pk,
        withdraw_reserve_liquidity_mint: withdraw.liquidity_mint,
        withdraw_reserve_collateral_mint: withdraw.collateral_mint,
        withdraw_reserve_collateral_supply: withdraw.collateral_supply_vault,
        withdraw_reserve_liquidity_supply: withdraw.liquidity_supply_vault,
        withdraw_reserve_liquidity_fee_receiver: withdraw.liquidity_fee_vault,
        user_source_liquidity: liquidator_repay_ata,
        user_destination_collateral: liquidator_collateral_ata,
        user_destination_liquidity: liquidator_withdraw_ata,
        collateral_token_program: SPL_TOKEN_PROGRAM,
        repay_liquidity_token_program: repay.liquidity_token_program,
        withdraw_liquidity_token_program: withdraw.liquidity_token_program,
    };

    Ok((plan, accounts, repay, withdraw))
}

/// Build the full bundle of instructions: refresh_reserve(repay) +
/// refresh_reserve(withdraw) + refresh_obligation + liquidate.
/// ATAs are NOT pre-pended (must be pre-created via setup_atas binary).
pub fn build_liquidation_ixs(
    wallet: &HotWallet,
    plan: &LiquidationPlan,
    accounts: &kix::LiquidateAccounts,
    args: &kix::LiquidateArgs,
    obligation_data: &[u8],
    extra_reserve_scopes: &std::collections::HashMap<solana_sdk::pubkey::Pubkey, solana_sdk::pubkey::Pubkey>,
) -> Vec<Instruction> {
    let lending_market = accounts.lending_market;
    let lma = accounts.lending_market_authority;

    info!(
        repay_farm_debt=%plan.repay_farm_debt,
        withdraw_farm_collateral=%plan.withdraw_farm_collateral,
        "farm states"
    );

    // R19 Q5: order matters. refresh_reserve BEFORE refresh_obligation.
    let mut ixs = Vec::with_capacity(8);

    // Get all reserves of this obligation (deposits + borrows)
    let (all_deposits, all_borrows) = match obl::extract_all_reserves(obligation_data) {
        Ok(t) => t,
        Err(_) => (vec![plan.withdraw_reserve], vec![plan.repay_reserve]),
    };
    info!(n_deposits=all_deposits.len(), n_borrows=all_borrows.len(), "refresh_obligation reserves");

    // R20 final: refresh order WITHDRAW FIRST, REPAY SECOND.
    // Kamino's refresh_ix_utils.rs:115 RequireKeysEqViolated showed Left=deposit Right=borrow,
    // suggesting the check expects withdraw at first position and repay at second.
    use crate::config::SCOPE_PRICES;
    let _ = extra_reserve_scopes;
    ixs.push(kix::build_refresh_reserve_ix(
        plan.withdraw_reserve, lending_market,
        None, None, None,
        Some(plan.withdraw_scope_prices),
    ));
    ixs.push(kix::build_refresh_reserve_ix(
        plan.repay_reserve, lending_market,
        None, None, None,
        Some(plan.repay_scope_prices),
    ));

    // [N+1] refresh_farms (if applicable, Null Farm Trap)
    if plan.repay_farm_debt != solana_sdk::pubkey::Pubkey::default() {
        let (repay_pda, _) = kix::derive_obligation_farm_user_state(&plan.repay_farm_debt, &plan.obligation);
        ixs.push(kix::build_refresh_farms_for_obligation_for_reserve_ix(
            wallet.pubkey, lending_market, plan.obligation,
            plan.repay_reserve, plan.repay_farm_debt, repay_pda, lma, 1,
        ));
    }
    if plan.withdraw_farm_collateral != solana_sdk::pubkey::Pubkey::default() {
        let (wd_pda, _) = kix::derive_obligation_farm_user_state(&plan.withdraw_farm_collateral, &plan.obligation);
        ixs.push(kix::build_refresh_farms_for_obligation_for_reserve_ix(
            wallet.pubkey, lending_market, plan.obligation,
            plan.withdraw_reserve, plan.withdraw_farm_collateral, wd_pda, lma, 0,
        ));
    }

    // [N+M+1] refresh_obligation
    ixs.push(kix::build_refresh_obligation_ix(
        lending_market, plan.obligation,
        &[plan.withdraw_reserve],
        &[plan.repay_reserve],
    ));

    // [last] liquidate
    ixs.push(kix::build_liquidate_ix(accounts, args));
    ixs
}

/// Simulate the liquidation tx via RPC. Includes ATA creates as a fallback for
/// the test mode (production should rely on setup_atas pre-creation).
pub async fn simulate_liquidation(
    rpc: &RpcClient,
    wallet: &HotWallet,
    obligation_pubkey: Pubkey,
    obligation_data: &[u8],
) -> Result<SimulationResult> {
    let (plan, accounts, _repay, _withdraw) =
        plan_liquidation(rpc, wallet, obligation_pubkey, obligation_data).await?;

    info!(?plan, "simulating liquidation (refresh + liquidate)");

    let args = kix::LiquidateArgs {
        liquidity_amount: plan.liquidity_amount,
        min_acceptable_received_collateral_amount: 0,
        max_allowed_ltv_override_pct: 0,
    };

    let mut ixs: Vec<Instruction> = Vec::new();
    // ATAs idempotent — needed for non-WSOL pair where scope check passes
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &plan.repay_mint, &accounts.repay_liquidity_token_program));
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &plan.withdraw_mint, &accounts.withdraw_liquidity_token_program));
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &accounts.withdraw_reserve_collateral_mint, &accounts.collateral_token_program));
    // Fetch scope_prices for any extra reserves beyond repay+withdraw
    let (all_deps, all_bors) = obl::extract_all_reserves(obligation_data).unwrap_or_default();
    let mut extra_scopes = std::collections::HashMap::new();
    for r in all_deps.iter().chain(all_bors.iter()) {
        if *r == plan.repay_reserve || *r == plan.withdraw_reserve { continue; }
        if extra_scopes.contains_key(r) { continue; }
        if let Ok(Some(rdata)) = rpc.get_account_data(r).await {
            if let Ok(parsed) = kres::parse_reserve(&rdata) {
                extra_scopes.insert(*r, parsed.scope_prices);
            }
        }
    }
    ixs.extend(build_liquidation_ixs(wallet, &plan, &accounts, &args, obligation_data, &extra_scopes));

    let blockhash = rpc.get_latest_blockhash().await.context("blockhash")?;
    let msg = Message::try_compile(&wallet.pubkey, &ixs, &[], blockhash)
        .context("compile message v0")?;
    let tx = VersionedTransaction::try_new(VersionedMessage::V0(msg), &[&wallet.keypair])
        .context("sign tx")?;

    let bytes = bincode::serialize(&tx).context("serialize tx")?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);

    let result = rpc.simulate_transaction(&b64).await.context("rpc simulate")?;
    if result.is_success() {
        info!(units = ?result.units_consumed, "✅ simulation succeeded");
    } else {
        warn!(err = ?result.err, "❌ simulation failed");
        for log in result.logs.iter().take(40) {
            warn!("log: {}", log);
        }
    }
    Ok(result)
}


/// LIVE mode: build the same liquidation bundle and SEND it to Jito.
/// Returns bundle_uuid if accepted by Jito.
pub async fn execute_live_liquidation(
    rpc: &RpcClient,
    wallet: &HotWallet,
    obligation_pubkey: Pubkey,
    obligation_data: &[u8],
    max_debt_usd: f64,
    min_profit_usd: f64,
    max_tip_lamports: u64,
) -> Result<String> {
    use crate::jito;
    let (plan, accounts, _repay, _withdraw) =
        plan_liquidation(rpc, wallet, obligation_pubkey, obligation_data).await?;

    info!(?plan, max_debt_usd, min_profit_usd, max_tip_lamports, "LIVE liquidation building");

    let args = kix::LiquidateArgs {
        liquidity_amount: u64::MAX, // Kamino caps to close_factor%
        min_acceptable_received_collateral_amount: 0,
        max_allowed_ltv_override_pct: 0,
    };

    // Re-fetch extra reserves for full refresh_obligation
    let (all_deps, all_bors) = obl::extract_all_reserves(obligation_data).unwrap_or_default();
    let mut extra_scopes = std::collections::HashMap::new();
    for r in all_deps.iter().chain(all_bors.iter()) {
        if *r == plan.repay_reserve || *r == plan.withdraw_reserve { continue; }
        if extra_scopes.contains_key(r) { continue; }
        if let Ok(Some(rdata)) = rpc.get_account_data(r).await {
            if let Ok(parsed) = kres::parse_reserve(&rdata) {
                extra_scopes.insert(*r, parsed.scope_prices);
            }
        }
    }

    // Build bundle (ATAs + refresh + liquidate)
    let mut ixs = Vec::new();
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &plan.repay_mint, &accounts.repay_liquidity_token_program));
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &plan.withdraw_mint, &accounts.withdraw_liquidity_token_program));
    ixs.push(create_ata_idempotent_ix(
        &wallet.pubkey, &wallet.pubkey, &accounts.withdraw_reserve_collateral_mint, &accounts.collateral_token_program));
    ixs.extend(build_liquidation_ixs(wallet, &plan, &accounts, &args, obligation_data, &extra_scopes));

    // Add Jito tip ix at the END
    let tip_lamports = std::cmp::min(jito::TIP_FLOOR_LAMPORTS, max_tip_lamports);
    let tip_ix = jito::build_tip_instruction(&wallet.pubkey, tip_lamports)?;
    ixs.push(tip_ix);

    let blockhash = rpc.get_latest_blockhash().await.context("blockhash")?;
    let msg = Message::try_compile(&wallet.pubkey, &ixs, &[], blockhash)?;
    let tx = VersionedTransaction::try_new(VersionedMessage::V0(msg), &[&wallet.keypair])?;

    // Build HTTP client for Jito (one-shot)
    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()?;

    info!(tip = tip_lamports, "sending bundle to Jito NY...");
    let bundle_id = jito::send_bundle(&http, &[tx]).await
        .context("jito send")?;
    info!(%bundle_id, "🚀 BUNDLE SENT — first live attempt");
    Ok(bundle_id)
}
