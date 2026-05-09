//! R53 Q5 — Economic bleed tracker for the abandon trigger ($20 hard stop).
//! Tracks SOL spent on tips + USDC net change since baseline.
//! When `total_bleed > max_loss_usd` → trips CB with WalletDrain.
//!
//! Detects manual deposits ≥ deposit_reset_threshold and rebases.
//! DORMANT — wired into M1 LIVE when bundles start sending.

use crate::circuit_breaker::{CircuitBreaker, TripReason};
use parking_lot::Mutex;
use std::sync::Arc;
use tracing::{info, warn};

#[derive(Debug, Clone, Copy)]
pub struct Balance {
    pub sol_lamports: u64,
    pub usdc_base_units: u128,
}

impl Balance {
    pub fn sol(&self) -> f64 {
        self.sol_lamports as f64 * 1e-9
    }
    pub fn usdc(&self) -> f64 {
        self.usdc_base_units as f64 / 1e6
    }
}

pub struct WalletMonitor {
    initial: Mutex<Balance>,
    sol_price_usd: Mutex<f64>,
    sol_spent_lamports: Mutex<u64>,
    max_loss_usd: f64,
    deposit_reset_threshold_usd: f64,
}

impl WalletMonitor {
    pub fn new(initial: Balance, sol_price_usd: f64, max_loss_usd: f64) -> Self {
        Self {
            initial: Mutex::new(initial),
            sol_price_usd: Mutex::new(sol_price_usd),
            sol_spent_lamports: Mutex::new(0),
            max_loss_usd,
            deposit_reset_threshold_usd: 50.0,
        }
    }

    /// Update reference SOL price (from oracle / pool).
    pub fn update_sol_price(&self, price_usd: f64) {
        *self.sol_price_usd.lock() = price_usd;
    }

    /// Record a tip paid.
    pub fn record_tip_paid(&self, lamports: u64) {
        let mut g = self.sol_spent_lamports.lock();
        *g = g.saturating_add(lamports);
    }

    /// Compute the current bleed in USD. Positive = loss.
    pub fn current_bleed_usd(&self, current: Balance) -> f64 {
        let initial = *self.initial.lock();
        let sol_price = *self.sol_price_usd.lock();
        let tips_spent = *self.sol_spent_lamports.lock();

        let usdc_loss = (initial.usdc() - current.usdc()).max(0.0);
        let tips_loss_usd = (tips_spent as f64 * 1e-9) * sol_price;
        usdc_loss + tips_loss_usd
    }

    /// Returns true if a deposit triggered baseline reset.
    pub fn maybe_reset_baseline(&self, current: Balance) -> bool {
        let initial = *self.initial.lock();
        let inflow_usd = (current.usdc() - initial.usdc()).max(0.0);
        if inflow_usd >= self.deposit_reset_threshold_usd {
            *self.initial.lock() = current;
            *self.sol_spent_lamports.lock() = 0;
            info!(
                inflow_usd,
                "WalletMonitor: deposit detected → baseline reset"
            );
            return true;
        }
        false
    }

    /// Check + trip CB if bleed exceeds threshold. Call after each bundle outcome.
    pub fn check_and_trip(&self, current: Balance, cb: &Arc<CircuitBreaker>) -> bool {
        if self.maybe_reset_baseline(current) {
            return false;
        }
        let bleed = self.current_bleed_usd(current);
        if bleed > self.max_loss_usd {
            warn!(
                bleed_usd = bleed,
                threshold_usd = self.max_loss_usd,
                "WalletMonitor: bleed exceeded → tripping CB"
            );
            cb.trip(TripReason::WalletDrain);
            return true;
        }
        false
    }

    pub fn summary(&self, current: Balance) -> String {
        let initial = *self.initial.lock();
        let bleed = self.current_bleed_usd(current);
        let tips = *self.sol_spent_lamports.lock();
        format!(
            "WalletMonitor: bleed=${:.4}/{} tips_spent={} lam (~${:.4}) USDC: ${:.2}→${:.2}",
            bleed,
            self.max_loss_usd,
            tips,
            tips as f64 * 1e-9 * *self.sol_price_usd.lock(),
            initial.usdc(),
            current.usdc()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_loss_no_trip() {
        let m = WalletMonitor::new(
            Balance { sol_lamports: 1_000_000_000, usdc_base_units: 200_000_000 },
            83.7, 20.0,
        );
        assert!(m.current_bleed_usd(Balance { sol_lamports: 1_000_000_000, usdc_base_units: 200_000_000 }) < 0.01);
    }

    #[test]
    fn usdc_loss_accumulates() {
        let m = WalletMonitor::new(
            Balance { sol_lamports: 0, usdc_base_units: 200_000_000 }, // $200
            83.7, 20.0,
        );
        // Lose $5 USDC
        let cur = Balance { sol_lamports: 0, usdc_base_units: 195_000_000 };
        assert!((m.current_bleed_usd(cur) - 5.0).abs() < 0.01);
    }

    #[test]
    fn tips_spent_counts_against_bleed() {
        let m = WalletMonitor::new(
            Balance { sol_lamports: 1_000_000_000, usdc_base_units: 200_000_000 },
            83.7, 20.0,
        );
        // Spend 0.1 SOL on tips = ~$8.37
        m.record_tip_paid(100_000_000);
        let bleed = m.current_bleed_usd(Balance { sol_lamports: 900_000_000, usdc_base_units: 200_000_000 });
        assert!(bleed > 8.0 && bleed < 9.0);
    }

    #[test]
    fn deposit_resets_baseline() {
        let m = WalletMonitor::new(
            Balance { sol_lamports: 0, usdc_base_units: 200_000_000 },
            83.7, 20.0,
        );
        let after_deposit = Balance { sol_lamports: 0, usdc_base_units: 300_000_000 };
        assert!(m.maybe_reset_baseline(after_deposit));
        // Now bleed should be near 0 against the new baseline
        assert!(m.current_bleed_usd(after_deposit) < 0.01);
    }
}
