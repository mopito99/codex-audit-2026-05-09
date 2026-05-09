//! Probe-time safety filters per Gemma R11 Q6.
//!
//! These run BEFORE we attempt to send a bundle. They protect against:
//!   - Wasting tip on positions that will heal themselves (HF too close to 1.0)
//!   - Wasting tip on positions where we don't have enough USDC (debt > wallet balance)
//!   - Insufficient profit margin to justify the bundle
//!   - Kamino-internal errors that don't panic but log a known error string

use crate::rpc::SimulationResult;

/// Live-mode pre-flight checks. Returns Err(reason) if we should skip this position.
#[derive(Debug, Clone)]
pub struct ProbeFilter {
    pub max_health_factor: f64,        // skip if HF > this (per Gemma: 0.95)
    pub max_debt_usd: f64,             // skip if borrowed > this (per Gemma: 500)
    pub min_expected_profit_usd: f64,  // skip if profit < this (per Gemma: 2.0)
    pub max_jito_tip_lamports: u64,    // cap tip (per Gemma: 0.005 SOL = 5_000_000)
}

impl Default for ProbeFilter {
    fn default() -> Self {
        Self {
            max_health_factor: 0.95,
            max_debt_usd: 500.0,
            min_expected_profit_usd: 2.0,
            max_jito_tip_lamports: 5_000_000, // 0.005 SOL
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ProbeReject {
    #[error("HF too high: {hf:.4} > max {max:.4}")]
    HealthFactor { hf: f64, max: f64 },
    #[error("debt too large: ${debt:.2} > max ${max:.2}")]
    DebtCap { debt: f64, max: f64 },
    #[error("profit too small: ${profit:.4} < min ${min:.2}")]
    Unprofitable { profit: f64, min: f64 },
    #[error("tip too high: {tip} lamports > max {max}")]
    TipTooHigh { tip: u64, max: u64 },
}

/// Pre-bundle checks given (HF, debt_usd, expected_profit_usd, tip_lamports).
pub fn pre_bundle_check(
    f: &ProbeFilter,
    hf: f64,
    debt_usd: f64,
    profit_usd: f64,
    tip_lamports: u64,
) -> Result<(), ProbeReject> {
    if hf > f.max_health_factor {
        return Err(ProbeReject::HealthFactor { hf, max: f.max_health_factor });
    }
    if debt_usd > f.max_debt_usd {
        return Err(ProbeReject::DebtCap { debt: debt_usd, max: f.max_debt_usd });
    }
    if profit_usd < f.min_expected_profit_usd {
        return Err(ProbeReject::Unprofitable { profit: profit_usd, min: f.min_expected_profit_usd });
    }
    if tip_lamports > f.max_jito_tip_lamports {
        return Err(ProbeReject::TipTooHigh { tip: tip_lamports, max: f.max_jito_tip_lamports });
    }
    Ok(())
}

/// Per Gemma R11 Q5: scan simulation logs for Kamino-internal errors that don't panic.
/// Returns Err if we find a known error string in the logs.
pub fn validate_simulation_logs(result: &SimulationResult) -> Result<(), String> {
    if !result.is_success() {
        return Err(format!("simulation reported err: {:?}", result.err));
    }
    // Even if no top-level err, scan for Kamino-internal warnings that signal a logical fail.
    let bad_strings: &[&str] = &[
        "Insufficient",
        "Invalid Price",
        "Stale price",
        "Obligation healthy",
        "AnchorError",
        "panicked",
        // Gemma R12-Q4: extra strings for blind-loss prevention
        "Constraint",         // pubkey ownership / account validation errors
        "InvalidAccount",     // wrong account ordering or missing accounts
        "Custom",             // Kamino-specific error codes
        "TooMany",            // account limit issues
        "Slippage",           // price moved between simulate and execute
    ];
    for log in &result.logs {
        for bad in bad_strings {
            if log.contains(bad) {
                return Err(format!("log contains '{bad}': {log}"));
            }
        }
    }
    // Confirm we ACTUALLY hit the liquidate ix successfully
    let saw_liquidate = result.logs.iter().any(|l|
        l.contains("Instruction: LiquidateObligationAndRedeemReserveCollateral"));
    let saw_kamino_success = result.logs.iter().any(|l|
        l.contains("KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD success"));
    if !saw_liquidate {
        return Err("logs do not show LiquidateObligation ix invocation".to_string());
    }
    if !saw_kamino_success {
        return Err("logs do not show Kamino program success after liquidate".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_high_hf() {
        let f = ProbeFilter::default();
        assert!(matches!(
            pre_bundle_check(&f, 0.99, 100.0, 5.0, 1_000_000),
            Err(ProbeReject::HealthFactor { .. })
        ));
    }

    #[test]
    fn rejects_big_debt() {
        let f = ProbeFilter::default();
        assert!(matches!(
            pre_bundle_check(&f, 0.90, 1000.0, 5.0, 1_000_000),
            Err(ProbeReject::DebtCap { .. })
        ));
    }

    #[test]
    fn rejects_unprofitable() {
        let f = ProbeFilter::default();
        assert!(matches!(
            pre_bundle_check(&f, 0.90, 100.0, 1.0, 1_000_000),
            Err(ProbeReject::Unprofitable { .. })
        ));
    }

    #[test]
    fn passes_all_checks() {
        let f = ProbeFilter::default();
        assert!(pre_bundle_check(&f, 0.93, 200.0, 5.0, 2_000_000).is_ok());
    }
}
