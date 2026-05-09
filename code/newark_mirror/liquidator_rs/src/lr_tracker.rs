//! R53 Q3 — Real-time landing rate tracker.
//! Records bundle send + landed events in a sliding window. Computes LR
//! over last N attempts. Designed to be fed by Yellowstone Transaction
//! filter on signature match, NOT by polling Jito.
//!
//! DORMANT — wired into M1 Phase 1 LIVE when the TX builder spawns bundles.

use parking_lot::Mutex;
use std::collections::VecDeque;
use std::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum AttemptStatus {
    Pending,
    Landed,
    Timeout,
}

#[derive(Debug, Clone)]
pub struct Attempt {
    pub sig: String,
    pub bundle_id: String,
    pub sent_at: Instant,
    pub status: AttemptStatus,
}

pub struct LRTracker {
    inner: Mutex<Inner>,
}

struct Inner {
    window: VecDeque<Attempt>,
    limit: usize,
    timeout_ms: u128,
}

impl LRTracker {
    pub fn new(window_size: usize, timeout_ms: u128) -> Self {
        Self {
            inner: Mutex::new(Inner {
                window: VecDeque::with_capacity(window_size),
                limit: window_size,
                timeout_ms,
            }),
        }
    }

    /// Call when a bundle is sent. The signature must match what Yellowstone
    /// will deliver (so we can pair them).
    pub fn record_send(&self, sig: String, bundle_id: String) {
        let mut g = self.inner.lock();
        if g.window.len() >= g.limit {
            g.window.pop_front();
        }
        g.window.push_back(Attempt {
            sig,
            bundle_id,
            sent_at: Instant::now(),
            status: AttemptStatus::Pending,
        });
    }

    /// Call from Yellowstone Transaction filter when a sig lands.
    pub fn record_land(&self, sig: &str) -> bool {
        let mut g = self.inner.lock();
        for a in g.window.iter_mut() {
            if a.sig == sig && a.status == AttemptStatus::Pending {
                a.status = AttemptStatus::Landed;
                return true;
            }
        }
        false
    }

    /// Sweep pending attempts older than timeout_ms → mark Timeout.
    /// Called periodically (e.g., every 1s by a tokio interval).
    pub fn sweep_timeouts(&self) -> usize {
        let mut g = self.inner.lock();
        let timeout = g.timeout_ms;
        let mut swept = 0;
        for a in g.window.iter_mut() {
            if a.status == AttemptStatus::Pending
                && a.sent_at.elapsed().as_millis() > timeout
            {
                a.status = AttemptStatus::Timeout;
                swept += 1;
            }
        }
        swept
    }

    /// Returns (landed, total_decided, rate). pending attempts excluded.
    pub fn current_rate(&self) -> (usize, usize, f64) {
        let g = self.inner.lock();
        let landed = g
            .window
            .iter()
            .filter(|a| a.status == AttemptStatus::Landed)
            .count();
        let total_decided = g
            .window
            .iter()
            .filter(|a| a.status != AttemptStatus::Pending)
            .count();
        let rate = if total_decided > 0 {
            landed as f64 / total_decided as f64
        } else {
            0.0
        };
        (landed, total_decided, rate)
    }

    pub fn summary(&self) -> String {
        let (landed, decided, rate) = self.current_rate();
        let g = self.inner.lock();
        let pending = g.window.iter().filter(|a| a.status == AttemptStatus::Pending).count();
        format!(
            "LR: {}/{} = {:.1}% (window={}, pending={})",
            landed, decided, rate * 100.0, g.window.len(), pending
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_window_returns_zero_rate() {
        let t = LRTracker::new(50, 5000);
        assert_eq!(t.current_rate().2, 0.0);
    }

    #[test]
    fn record_send_then_land() {
        let t = LRTracker::new(50, 5000);
        t.record_send("sig1".into(), "bid1".into());
        assert!(t.record_land("sig1"));
        let (l, d, r) = t.current_rate();
        assert_eq!(l, 1);
        assert_eq!(d, 1);
        assert!((r - 1.0).abs() < 1e-9);
    }

    #[test]
    fn unknown_sig_land_returns_false() {
        let t = LRTracker::new(50, 5000);
        assert!(!t.record_land("nonexistent"));
    }

    #[test]
    fn rate_under_threshold_signals_abandon() {
        let t = LRTracker::new(50, 5000);
        for i in 0..10 {
            t.record_send(format!("sig{i}"), format!("bid{i}"));
        }
        // Only 1 of 10 lands → 10% rate
        t.record_land("sig0");
        // Mark rest as timed out manually (in real code sweep_timeouts handles it)
        std::thread::sleep(std::time::Duration::from_millis(20));
        // Force-sweep with very low timeout
        let t2 = LRTracker::new(50, 10);
        for i in 0..10 {
            t2.record_send(format!("sig{i}"), format!("bid{i}"));
        }
        t2.record_land("sig0");
        std::thread::sleep(std::time::Duration::from_millis(15));
        t2.sweep_timeouts();
        let (l, d, r) = t2.current_rate();
        assert_eq!(l, 1);
        assert_eq!(d, 10);
        assert!((r - 0.1).abs() < 1e-9);
    }
}
