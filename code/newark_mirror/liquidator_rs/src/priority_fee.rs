//! R34 Q2 — FeeManager + tip-laddering verbatim from Gemma.
//!
//! Two distinct fees per execution:
//!   1. Priority Fee (leader-side):   base_fee + p75_per_cu × cu_estimate
//!   2. Jito Tip     (validator-side): max(rolling_median × 1.2, floor)
//!
//! `get_execution_fees()` returns both — caller assigns priority_fee to the
//! ComputeBudgetInstruction and jito_tip to the final transfer in the bundle.

use crate::tip_stream::TipStream;
use std::sync::Arc;

#[derive(Debug, Clone, Copy)]
pub struct PriorityFeeConfig {
    pub base_fee: u64,
    pub cu_estimate: u64,
}

impl Default for PriorityFeeConfig {
    fn default() -> Self {
        // Defaults match R28 Q5 numbers: 2 sigs × 5_000 lam, 2-leg cyclic = 100k CU.
        Self {
            base_fee: 10_000,
            cu_estimate: 100_000,
        }
    }
}

impl PriorityFeeConfig {
    pub fn new(base_fee: u64, cu_estimate: u64) -> Self {
        Self { base_fee, cu_estimate }
    }

    /// Total lamports for the priority fee.
    /// **Unit fix**: Solana `getRecentPrioritizationFees` returns the fee in
    /// micro-lamports per CU. To convert to total lamports we divide by 1e6.
    /// priority_fee_lamports = base_fee + (p75_micro × cu_estimate) / 1_000_000
    pub fn calculate_priority_fee_total(&self, p75_per_cu: u64) -> u64 {
        let priority_fee_lamports =
            p75_per_cu.saturating_mul(self.cu_estimate) / 1_000_000;
        self.base_fee.saturating_add(priority_fee_lamports)
    }

    /// Tip-laddering: median × 1.2 of the Jito public tip_floor stream.
    pub fn calculate_effective_jito_tip(&self, tip_stream: &TipStream) -> u64 {
        let median = tip_stream.get_rolling_median();
        let multiplier = 1.2_f64;
        (median as f64 * multiplier) as u64
    }
}

#[derive(Clone)]
pub struct FeeManager {
    pub config: PriorityFeeConfig,
    pub tip_stream: Arc<TipStream>,
}

impl FeeManager {
    pub fn new(config: PriorityFeeConfig, tip_stream: Arc<TipStream>) -> Self {
        Self { config, tip_stream }
    }

    /// Returns (priority_fee_total_lamports, jito_tip_lamports).
    pub fn get_execution_fees(&self, p75_per_cu: u64) -> (u64, u64) {
        let priority_fee = self.config.calculate_priority_fee_total(p75_per_cu);
        let jito_tip = self.config.calculate_effective_jito_tip(&self.tip_stream);
        (priority_fee, jito_tip)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fee_unit_conversion_micro_lamports_per_cu() {
        let cfg = PriorityFeeConfig::default();
        // p75 = 886 micro-lamports/CU, cu_estimate = 100k
        // expected: 886 × 100_000 / 1_000_000 = 88 lamports + 10_000 base = 10_088
        let total = cfg.calculate_priority_fee_total(886);
        assert!(total < 11_000, "priority_fee_total={total} too high — unit bug?");
        assert!(total > 10_000);
    }

    #[test]
    fn fee_zero_p75_returns_just_base() {
        let cfg = PriorityFeeConfig::default();
        assert_eq!(cfg.calculate_priority_fee_total(0), 10_000);
    }

    #[test]
    fn fee_huge_p75_does_not_overflow() {
        let cfg = PriorityFeeConfig::default();
        // huge p75 should still be bounded by saturating math
        let total = cfg.calculate_priority_fee_total(u64::MAX);
        assert!(total > 0);
    }
}
