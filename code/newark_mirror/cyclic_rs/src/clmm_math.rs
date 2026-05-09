//! CLMM swap math (R30 Q1 — Gemma fix).
//!
//! For shadow probes that don't cross a tick boundary the math reduces to the
//! constant-product Q64.64 spot formula:
//!   A → B:  out = in × P              where P = (sqrt_p_x64 / 2^64)^2
//!   B → A:  out = in / P
//!
//! Implemented in U256 to avoid overflow: out = (in × sqrt_p²) / 2^128 (Upper).
//! See R26 for the tick-traversal motor — currently unused for shadow logging,
//! kept dead-code-friendly for when probe sizes grow past the 0.1% L cap.

use ethnum::U256;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SwapDirection {
    Upper, // A → B (precio sube)
    Lower, // B → A (precio baja)
}

#[derive(Debug, Clone)]
pub struct Tick {
    pub index: i32,
    pub liquidity_net: i128,
}

#[derive(Debug, Clone)]
pub struct Leg {
    pub pool_id: String,
    pub amount_in: U256,
    pub current_price: U256,
    pub liquidity: U256,
    pub ticks: Vec<Tick>,
}

/// Spot-price swap math without tick traversal (R30 Q1).
pub fn calculate_swap_out(amount_in: U256, sqrt_price_x64: u128, dir: SwapDirection) -> U256 {
    let sqrt_p = U256::from(sqrt_price_x64);
    match dir {
        SwapDirection::Upper => {
            // A → B: out = in × (sqrt_p² / 2^128)
            let numerator = amount_in * sqrt_p * sqrt_p;
            let denominator = U256::ONE << 128;
            numerator / denominator
        }
        SwapDirection::Lower => {
            // B → A: out = (in × 2^128) / sqrt_p²
            let denominator = sqrt_p * sqrt_p;
            if denominator == U256::ZERO {
                return U256::ZERO;
            }
            let numerator = amount_in * (U256::ONE << 128);
            numerator / denominator
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Live SOL/USDC at ~$83.7. sqrt_price_x64 = 5_336_409_708_600_152_234.
    /// 1 USDC base unit (1_000_000) → SOL base units via Lower. Then SOL → USDC via Upper.
    /// The round trip should be lossless to within rounding.
    #[test]
    fn round_trip_usdc_sol_usdc_is_close_to_input() {
        let sqrt_p: u128 = 5_336_409_708_600_152_234;
        let amount_in = U256::from(1_000_000u128); // 1 USDC base unit
        // USDC → SOL: B → A → Lower
        let sol_out = calculate_swap_out(amount_in, sqrt_p, SwapDirection::Lower);
        // SOL → USDC: A → B → Upper
        let usdc_back = calculate_swap_out(sol_out, sqrt_p, SwapDirection::Upper);
        // Should be ~ 1_000_000, with rounding error ≤ 0.1%
        let usdc_back_u128 = usdc_back.as_u128();
        assert!(
            usdc_back_u128 > 999_000 && usdc_back_u128 <= 1_000_000,
            "round trip {usdc_back_u128} not in [999_000, 1_000_000]"
        );
    }

    #[test]
    fn upper_at_unity_price_is_identity() {
        let sqrt_p_unity: u128 = 1u128 << 64; // sqrt_p = 1.0 → P = 1.0
        let amount_in = U256::from(12_345u128);
        let out = calculate_swap_out(amount_in, sqrt_p_unity, SwapDirection::Upper);
        assert_eq!(out, amount_in);
    }

    #[test]
    fn lower_at_unity_price_is_identity() {
        let sqrt_p_unity: u128 = 1u128 << 64;
        let amount_in = U256::from(7u128);
        let out = calculate_swap_out(amount_in, sqrt_p_unity, SwapDirection::Lower);
        assert_eq!(out, amount_in);
    }

    #[test]
    fn lower_with_zero_sqrt_returns_zero() {
        let out = calculate_swap_out(U256::from(1u128), 0, SwapDirection::Lower);
        assert_eq!(out, U256::ZERO);
    }

    #[test]
    fn sqrt_price_limit_a_to_b_lowers_price() {
        let sqrt_p: u128 = 5_336_409_708_600_152_234;
        let limit = sqrt_price_limit_from_slippage(sqrt_p, 50, true);
        assert!(limit < sqrt_p);
        let drop = sqrt_p - limit;
        assert!(drop > sqrt_p / 1000 && drop < sqrt_p / 200);
    }

    #[test]
    fn sqrt_price_limit_b_to_a_raises_price() {
        let sqrt_p: u128 = 5_336_409_708_600_152_234;
        let limit = sqrt_price_limit_from_slippage(sqrt_p, 50, false);
        assert!(limit > sqrt_p);
    }

    #[test]
    fn sqrt_price_limit_zero_slippage_nudges_one_unit() {
        let sqrt_p: u128 = 1u128 << 64;
        assert_eq!(sqrt_price_limit_from_slippage(sqrt_p, 0, true), sqrt_p - 1);
        assert_eq!(sqrt_price_limit_from_slippage(sqrt_p, 0, false), sqrt_p + 1);
    }
}

/// R38 Q1 — Compute sqrt_price_limit for CLMM swaps from slippage_bps.
/// Slippage is defined on price P; sqrt_limit = sqrt_curr × √(1 ± ε).
pub fn sqrt_price_limit_from_slippage(
    sqrt_price_curr: u128,
    slippage_bps: u16,
    a_to_b: bool,
) -> u128 {
    let slippage_decimal = slippage_bps as f64 / 10_000.0;
    let multiplier = if a_to_b {
        (1.0 - slippage_decimal).sqrt()
    } else {
        (1.0 + slippage_decimal).sqrt()
    };
    let limit = (sqrt_price_curr as f64 * multiplier) as u128;
    if a_to_b && limit >= sqrt_price_curr {
        limit.saturating_sub(1)
    } else if !a_to_b && limit <= sqrt_price_curr {
        limit.saturating_add(1)
    } else {
        limit
    }
}
