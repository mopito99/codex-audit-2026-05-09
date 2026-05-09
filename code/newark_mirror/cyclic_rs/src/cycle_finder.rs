//! Phase 2 cycle finder: simulate two-leg cycles across CLMM pools and return
//! a CycleQuote with all the fields the shadow logger needs (R28 Q1+Q4).

use crate::clmm_math::{calculate_swap_out, SwapDirection};
use crate::pool_state::PoolState;
use ethnum::U256;
use solana_sdk::pubkey::Pubkey;

#[derive(Debug, Clone)]
pub struct CycleQuote {
    pub leg0_pool: Pubkey,
    pub leg1_pool: Pubkey,
    pub leg0_label: String,
    pub leg1_label: String,
    pub leg0_dir: SwapDirection,
    pub leg1_dir: SwapDirection,
    pub sqrt_price_0: u128,
    pub sqrt_price_1: u128,
    pub liquidity_0: u128,
    pub liquidity_1: u128,
    pub amount_in: u128,
    pub intermediate_out: u128,
    pub final_out: u128,
    pub net: i128,
    pub gross_bps: f64,
    pub stale_due_to_missing_ticks: bool,
    pub slippage_bps_0: u16,    // R35 Q3 dynamic slippage per leg
    pub slippage_bps_1: u16,
    pub min_intermediate_out: u128,
    pub min_final_out: u128,
}

pub fn dir_str(d: SwapDirection) -> &'static str {
    match d {
        SwapDirection::Upper => "A->B",
        SwapDirection::Lower => "B->A",
    }
}

/// R28 Q4 heuristic: max amount of token A movable inside the active tick
/// without crossing it. `(L * 0.001) / sqrt_price_normalized`.
pub fn max_amount_a_within_tick(liquidity_q64: u128, sqrt_price_x64: u128) -> f64 {
    let denom = sqrt_price_x64 as f64 / 2f64.powi(64);
    if denom == 0.0 {
        return f64::MAX;
    }
    (liquidity_q64 as f64 * 0.001) / denom
}

/// R35 Q3 — Dynamic slippage guard.
/// Returns slippage tolerance in bps based on `amount_in / liquidity` utilization.
/// `< 1%`  → 5 bps (tight)
/// `< 5%`  → 15 bps (moderate)
/// `< 10%` → 40 bps (conservative)
/// `≥ 10%` → 100 bps (high risk)
pub fn slippage_bps_from_utilization(amount_in: u128, liquidity: u128) -> u16 {
    if liquidity == 0 {
        return 100;
    }
    let utilization = amount_in as f64 / liquidity as f64;
    if utilization < 0.01 { 5 }
    else if utilization < 0.05 { 15 }
    else if utilization < 0.10 { 40 }
    else { 100 }
}

/// Returns the dynamic min_amount_out for a swap given expected_out and the
/// pool's liquidity at the active tick. Slippage tolerance is derived from
/// utilization (R35 Q3).
pub fn calculate_min_output(amount_in: u128, liquidity: u128, expected_out: u128) -> u128 {
    let bps = slippage_bps_from_utilization(amount_in, liquidity) as f64;
    let factor = 1.0 - (bps / 10_000.0);
    (expected_out as f64 * factor) as u128
}

pub fn simulate_two_leg_cycle(
    leg0_pool: &PoolState,
    dir0: SwapDirection,
    leg1_pool: &PoolState,
    dir1: SwapDirection,
    amount_in: u128,
) -> CycleQuote {
    let amount_in_u256 = U256::from(amount_in);

    // R30 Q1 fix: spot Q64.64 math, no tick traversal needed for shadow probes.
    let intermediate = calculate_swap_out(amount_in_u256, leg0_pool.sqrt_price_x64, dir0);
    let final_out = calculate_swap_out(intermediate, leg1_pool.sqrt_price_x64, dir1);

    let intermediate_u128 = intermediate.as_u128();
    let final_u128 = final_out.as_u128();
    let net = final_u128 as i128 - amount_in as i128;
    let gross_bps = if amount_in > 0 {
        (net as f64 / amount_in as f64) * 10_000.0
    } else {
        0.0
    };

    // R28 Q4: flag if probe amount could cross a tick on EITHER leg.
    let max0 = max_amount_a_within_tick(leg0_pool.liquidity, leg0_pool.sqrt_price_x64);
    let max1 = max_amount_a_within_tick(leg1_pool.liquidity, leg1_pool.sqrt_price_x64);
    let stale = (amount_in as f64) > max0 || (intermediate_u128 as f64) > max1;

    // R35 Q3 dynamic slippage guard per leg.
    let slippage_bps_0 = slippage_bps_from_utilization(amount_in, leg0_pool.liquidity);
    let slippage_bps_1 = slippage_bps_from_utilization(intermediate_u128, leg1_pool.liquidity);
    let min_intermediate_out = calculate_min_output(amount_in, leg0_pool.liquidity, intermediate_u128);
    let min_final_out = calculate_min_output(intermediate_u128, leg1_pool.liquidity, final_u128);

    CycleQuote {
        leg0_pool: leg0_pool.address,
        leg1_pool: leg1_pool.address,
        leg0_label: leg0_pool.label.clone(),
        leg1_label: leg1_pool.label.clone(),
        leg0_dir: dir0,
        leg1_dir: dir1,
        sqrt_price_0: leg0_pool.sqrt_price_x64,
        sqrt_price_1: leg1_pool.sqrt_price_x64,
        liquidity_0: leg0_pool.liquidity,
        liquidity_1: leg1_pool.liquidity,
        amount_in,
        intermediate_out: intermediate_u128,
        final_out: final_u128,
        net,
        gross_bps,
        stale_due_to_missing_ticks: stale,
        slippage_bps_0,
        slippage_bps_1,
        min_intermediate_out,
        min_final_out,
    }
}

pub fn scan_best_cycle(
    registry: &dashmap::DashMap<Pubkey, PoolState>,
    amount_in: u128,
) -> Option<CycleQuote> {
    let pools: Vec<PoolState> = registry.iter().map(|e| e.value().clone()).collect();
    if pools.len() < 2 {
        return None;
    }

    fn pair_key(label: &str) -> Option<&str> {
        label.split_once('_').map(|(_, rest)| rest)
    }

    let mut best: Option<CycleQuote> = None;
    for (i, a) in pools.iter().enumerate() {
        for b in pools.iter().skip(i + 1) {
            if pair_key(&a.label) != pair_key(&b.label) {
                continue;
            }
            for (d0, d1) in [
                (SwapDirection::Upper, SwapDirection::Lower),
                (SwapDirection::Lower, SwapDirection::Upper),
            ] {
                let q = simulate_two_leg_cycle(a, d0, b, d1, amount_in);
                if best.as_ref().map_or(true, |cur| q.net > cur.net) {
                    best = Some(q);
                }
            }
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::PoolKind;

    fn fake_pool(label: &str, sqrt_price: u128, liquidity: u128) -> PoolState {
        PoolState {
            address: Pubkey::new_unique(),
            kind: PoolKind::OrcaWhirlpool,
            label: label.to_string(),
            liquidity,
            sqrt_price_x64: sqrt_price,
            tick_current: 0,
            slot: 0,
            updated_at: chrono::Utc::now(),
        }
    }

    #[test]
    fn no_cycle_when_only_one_pool() {
        let reg = dashmap::DashMap::new();
        let p = fake_pool("orca_sol_usdc", 1u128 << 64, 1_000_000_000);
        reg.insert(p.address, p);
        assert!(scan_best_cycle(&reg, 1_000_000).is_none());
    }

    #[test]
    fn two_pools_yield_quote_with_full_metadata() {
        let reg = dashmap::DashMap::new();
        let a = fake_pool("orca_sol_usdc", 1u128 << 64, 1_000_000_000);
        let b = fake_pool("raydium_sol_usdc", (1u128 << 64) + (1u128 << 60), 1_000_000_000);
        reg.insert(a.address, a);
        reg.insert(b.address, b);
        let q = scan_best_cycle(&reg, 1_000_000).expect("should have a quote");
        assert_eq!(q.amount_in, 1_000_000);
        assert!(!q.leg0_label.is_empty());
        assert!(!q.leg1_label.is_empty());
        assert!(q.sqrt_price_0 > 0);
    }

}
