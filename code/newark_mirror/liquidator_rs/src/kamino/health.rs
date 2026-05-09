//! Health factor utilities.
//!
//! In Kamino Lend, an Obligation is liquidatable when:
//!   borrowed_value > unhealthy_borrow_value  (i.e. health_factor_unhealthy < 1.0)
//! Some configurations use:
//!   borrowed_value > allowed_borrow_value    (early-warning threshold)
//!
//! For Milestone 0 we expose both ratios. Milestone 1 will plug in real
//! Kamino constants per reserve (LTV, liquidation_threshold).

#[inline]
pub fn ratio(numerator: f64, denominator: f64) -> f64 {
    if denominator <= 0.0 {
        f64::INFINITY
    } else {
        numerator / denominator
    }
}
