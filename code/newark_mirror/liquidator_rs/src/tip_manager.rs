//! R37 Q4 — Adaptive TipManager.
//! Adjusts the tip_stream multiplier based on the rolling success rate of
//! recent bundle landings. Goal: stay competitive without over-paying.
//!
//! Feedback loop:
//!   win_rate < 0.10  → increase multiplier (we're being out-tipped)
//!   win_rate > 0.50  → decrease multiplier (we're overpaying)
//!   else             → hold
//! Clamp: multiplier ∈ [1.1, 3.0]
//!
//! Updated externally via `record_landed(bool)` after each bundle outcome.

use std::collections::VecDeque;
use std::sync::Mutex;

const WINDOW: usize = 20;
const FLOOR: f64 = 1.1;
const CEIL: f64 = 3.0;

pub struct TipManager {
    inner: Mutex<Inner>,
}

struct Inner {
    multiplier: f64,
    landings: VecDeque<bool>,
}

impl Default for TipManager {
    fn default() -> Self {
        Self::new(1.2)
    }
}

impl TipManager {
    pub fn new(initial_multiplier: f64) -> Self {
        Self {
            inner: Mutex::new(Inner {
                multiplier: initial_multiplier.clamp(FLOOR, CEIL),
                landings: VecDeque::with_capacity(WINDOW),
            }),
        }
    }

    pub fn current_multiplier(&self) -> f64 {
        self.inner.lock().unwrap().multiplier
    }

    pub fn record_landed(&self, landed: bool) {
        let mut g = self.inner.lock().unwrap();
        g.landings.push_back(landed);
        while g.landings.len() > WINDOW {
            g.landings.pop_front();
        }
        if g.landings.len() < WINDOW {
            return; // not enough samples to recalibrate
        }
        let win_count = g.landings.iter().filter(|x| **x).count();
        let win_rate = win_count as f64 / WINDOW as f64;
        if win_rate < 0.10 {
            g.multiplier += 0.10;
        } else if win_rate > 0.50 {
            g.multiplier -= 0.05;
        }
        g.multiplier = g.multiplier.clamp(FLOOR, CEIL);
    }

    pub fn win_rate(&self) -> f64 {
        let g = self.inner.lock().unwrap();
        if g.landings.is_empty() {
            return 0.0;
        }
        let win_count = g.landings.iter().filter(|x| **x).count();
        win_count as f64 / g.landings.len() as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn climbs_when_failing() {
        let m = TipManager::new(1.2);
        for _ in 0..WINDOW {
            m.record_landed(false);
        }
        // After 20 fails, multiplier should bump by 0.10 once (only one cycle past the gate)
        assert!(m.current_multiplier() >= 1.3 - 1e-9);
    }

    #[test]
    fn drops_when_dominating() {
        let m = TipManager::new(2.0);
        for i in 0..WINDOW {
            m.record_landed(i % 2 == 0); // win_rate = 0.5 exactly → no change
        }
        let mid = m.current_multiplier();
        // Now flood with wins to push above 0.5
        for _ in 0..WINDOW {
            m.record_landed(true);
        }
        assert!(m.current_multiplier() < mid + 1e-9);
        assert!(m.current_multiplier() < 2.0);
    }

    #[test]
    fn clamps_to_ceil() {
        let m = TipManager::new(2.95);
        for _ in 0..WINDOW * 5 {
            m.record_landed(false);
        }
        assert!(m.current_multiplier() <= CEIL);
    }
}
