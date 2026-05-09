//! Observability — bundle tracking + alert metrics (Pieza A7 R62 audit).
//!
//! Gemma R62 A7 dijo CRITICAL pre-LIVE: tener visibilidad de
//!   1. Bundle landed/failed con razón (no operar a ciegas)
//!   2. Alert metrics — qué CB tripeó, cuántas veces, recovery
//!
//! Este módulo expone counters atómicos lock-free + struct emitible JSONL.

use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// Razón por la que un bundle no aterrizó.
/// Útil para diagnostic post-mortem (latencia? tip bajo? state stale?).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BundleFailureReason {
    /// Tip insuficiente — competidor pagó más.
    LowTip,
    /// State pool cambió antes de que el bundle llegara al líder.
    StaleState,
    /// Vote account o cuenta bloqueada por otro bundle (auto-blacklist candidato).
    VoteAccountConflict,
    /// Bundle oversized (demasiadas instrucciones).
    OverSized,
    /// Timeout del Block Engine — no respondió en ventana.
    BlockEngineTimeout,
    /// Bundle simulación falló (math error, slippage exceeded).
    SimulationFailed,
    /// RPC error — desconocido, log para análisis manual.
    Unknown,
}

impl BundleFailureReason {
    pub fn as_str(self) -> &'static str {
        match self {
            BundleFailureReason::LowTip => "low_tip",
            BundleFailureReason::StaleState => "stale_state",
            BundleFailureReason::VoteAccountConflict => "vote_account_conflict",
            BundleFailureReason::OverSized => "over_sized",
            BundleFailureReason::BlockEngineTimeout => "block_engine_timeout",
            BundleFailureReason::SimulationFailed => "simulation_failed",
            BundleFailureReason::Unknown => "unknown",
        }
    }
}

/// Outcome de un bundle enviado.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BundleOutcome {
    pub bundle_id: String,
    pub timestamp_unix: i64,
    pub pool_label: String,
    pub probe_size_usd: f64,
    pub tip_lamports: u64,
    pub priority_fee_lamports: u64,
    /// Latencia desde detect → send (ms).
    pub detect_to_send_ms: u64,
    pub landed: bool,
    /// Si landed: net_profit en USD. Si fallido: pérdida del tip (negativo).
    pub realized_pnl_usd: f64,
    /// Si fallido: razón.
    pub failure_reason: Option<BundleFailureReason>,
    /// Slot Solana cuando aterrizó (None si fallido).
    pub landed_slot: Option<u64>,
}

/// Counters lock-free para alert metrics (R62 A7).
/// Por cada CB trip reason, contamos cuántas veces se ha tripeado.
#[derive(Debug)]
pub struct AlertMetrics {
    pub trips_slot_lag: AtomicU64,
    pub trips_wallet_drain: AtomicU64,
    pub trips_slippage_divergence: AtomicU64,
    pub trips_tip_exhausted: AtomicU64,
    pub trips_consecutive_failures: AtomicU64,
    pub trips_telemetry_critical: AtomicU64,
    pub trips_pyth_depeg: AtomicU64,
    pub trips_pyth_emergency_exit: AtomicU64,
    pub trips_safety_worker_event: AtomicU64,
    pub manual_resets: AtomicU64,
    pub safe_resets_attempted: AtomicU64,
    pub safe_resets_rejected: AtomicU64,
}

impl Default for AlertMetrics {
    fn default() -> Self {
        Self {
            trips_slot_lag: AtomicU64::new(0),
            trips_wallet_drain: AtomicU64::new(0),
            trips_slippage_divergence: AtomicU64::new(0),
            trips_tip_exhausted: AtomicU64::new(0),
            trips_consecutive_failures: AtomicU64::new(0),
            trips_telemetry_critical: AtomicU64::new(0),
            trips_pyth_depeg: AtomicU64::new(0),
            trips_pyth_emergency_exit: AtomicU64::new(0),
            trips_safety_worker_event: AtomicU64::new(0),
            manual_resets: AtomicU64::new(0),
            safe_resets_attempted: AtomicU64::new(0),
            safe_resets_rejected: AtomicU64::new(0),
        }
    }
}

impl AlertMetrics {
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    /// Snapshot de todos los counters (para dashboard JSON).
    pub fn snapshot(&self) -> AlertMetricsSnapshot {
        AlertMetricsSnapshot {
            trips_slot_lag: self.trips_slot_lag.load(Ordering::Relaxed),
            trips_wallet_drain: self.trips_wallet_drain.load(Ordering::Relaxed),
            trips_slippage_divergence: self.trips_slippage_divergence.load(Ordering::Relaxed),
            trips_tip_exhausted: self.trips_tip_exhausted.load(Ordering::Relaxed),
            trips_consecutive_failures: self.trips_consecutive_failures.load(Ordering::Relaxed),
            trips_telemetry_critical: self.trips_telemetry_critical.load(Ordering::Relaxed),
            trips_pyth_depeg: self.trips_pyth_depeg.load(Ordering::Relaxed),
            trips_pyth_emergency_exit: self.trips_pyth_emergency_exit.load(Ordering::Relaxed),
            trips_safety_worker_event: self.trips_safety_worker_event.load(Ordering::Relaxed),
            manual_resets: self.manual_resets.load(Ordering::Relaxed),
            safe_resets_attempted: self.safe_resets_attempted.load(Ordering::Relaxed),
            safe_resets_rejected: self.safe_resets_rejected.load(Ordering::Relaxed),
            total_trips: self.total_trips(),
        }
    }

    /// Total trips (todas las razones).
    pub fn total_trips(&self) -> u64 {
        self.trips_slot_lag.load(Ordering::Relaxed)
            + self.trips_wallet_drain.load(Ordering::Relaxed)
            + self.trips_slippage_divergence.load(Ordering::Relaxed)
            + self.trips_tip_exhausted.load(Ordering::Relaxed)
            + self.trips_consecutive_failures.load(Ordering::Relaxed)
            + self.trips_telemetry_critical.load(Ordering::Relaxed)
            + self.trips_pyth_depeg.load(Ordering::Relaxed)
            + self.trips_pyth_emergency_exit.load(Ordering::Relaxed)
            + self.trips_safety_worker_event.load(Ordering::Relaxed)
    }
}

/// Snapshot serializable para dashboard / JSONL export.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertMetricsSnapshot {
    pub trips_slot_lag: u64,
    pub trips_wallet_drain: u64,
    pub trips_slippage_divergence: u64,
    pub trips_tip_exhausted: u64,
    pub trips_consecutive_failures: u64,
    pub trips_telemetry_critical: u64,
    pub trips_pyth_depeg: u64,
    pub trips_pyth_emergency_exit: u64,
    pub trips_safety_worker_event: u64,
    pub manual_resets: u64,
    pub safe_resets_attempted: u64,
    pub safe_resets_rejected: u64,
    pub total_trips: u64,
}

/// Counters de bundle outcome (lock-free).
#[derive(Debug, Default)]
pub struct BundleMetrics {
    pub bundles_sent: AtomicU64,
    pub bundles_landed: AtomicU64,
    pub bundles_failed_low_tip: AtomicU64,
    pub bundles_failed_stale_state: AtomicU64,
    pub bundles_failed_vote_conflict: AtomicU64,
    pub bundles_failed_oversized: AtomicU64,
    pub bundles_failed_be_timeout: AtomicU64,
    pub bundles_failed_simulation: AtomicU64,
    pub bundles_failed_unknown: AtomicU64,
}

impl BundleMetrics {
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    pub fn record_sent(&self) {
        self.bundles_sent.fetch_add(1, Ordering::Relaxed);
    }
    pub fn record_landed(&self) {
        self.bundles_landed.fetch_add(1, Ordering::Relaxed);
    }
    pub fn record_failed(&self, reason: BundleFailureReason) {
        let counter = match reason {
            BundleFailureReason::LowTip => &self.bundles_failed_low_tip,
            BundleFailureReason::StaleState => &self.bundles_failed_stale_state,
            BundleFailureReason::VoteAccountConflict => &self.bundles_failed_vote_conflict,
            BundleFailureReason::OverSized => &self.bundles_failed_oversized,
            BundleFailureReason::BlockEngineTimeout => &self.bundles_failed_be_timeout,
            BundleFailureReason::SimulationFailed => &self.bundles_failed_simulation,
            BundleFailureReason::Unknown => &self.bundles_failed_unknown,
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> BundleMetricsSnapshot {
        let sent = self.bundles_sent.load(Ordering::Relaxed);
        let landed = self.bundles_landed.load(Ordering::Relaxed);
        let landing_rate = if sent > 0 { (landed as f64) / (sent as f64) } else { 0.0 };
        BundleMetricsSnapshot {
            bundles_sent: sent,
            bundles_landed: landed,
            landing_rate,
            bundles_failed_low_tip: self.bundles_failed_low_tip.load(Ordering::Relaxed),
            bundles_failed_stale_state: self.bundles_failed_stale_state.load(Ordering::Relaxed),
            bundles_failed_vote_conflict: self.bundles_failed_vote_conflict.load(Ordering::Relaxed),
            bundles_failed_oversized: self.bundles_failed_oversized.load(Ordering::Relaxed),
            bundles_failed_be_timeout: self.bundles_failed_be_timeout.load(Ordering::Relaxed),
            bundles_failed_simulation: self.bundles_failed_simulation.load(Ordering::Relaxed),
            bundles_failed_unknown: self.bundles_failed_unknown.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BundleMetricsSnapshot {
    pub bundles_sent: u64,
    pub bundles_landed: u64,
    /// landing_rate = bundles_landed / bundles_sent (0.0 - 1.0).
    pub landing_rate: f64,
    pub bundles_failed_low_tip: u64,
    pub bundles_failed_stale_state: u64,
    pub bundles_failed_vote_conflict: u64,
    pub bundles_failed_oversized: u64,
    pub bundles_failed_be_timeout: u64,
    pub bundles_failed_simulation: u64,
    pub bundles_failed_unknown: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alert_metrics_default_zeros() {
        let m = AlertMetrics::new();
        let s = m.snapshot();
        assert_eq!(s.total_trips, 0);
        assert_eq!(s.trips_slot_lag, 0);
        assert_eq!(s.trips_wallet_drain, 0);
    }

    #[test]
    fn alert_metrics_increment() {
        let m = AlertMetrics::new();
        m.trips_wallet_drain.fetch_add(1, Ordering::Relaxed);
        m.trips_slot_lag.fetch_add(3, Ordering::Relaxed);
        let s = m.snapshot();
        assert_eq!(s.trips_wallet_drain, 1);
        assert_eq!(s.trips_slot_lag, 3);
        assert_eq!(s.total_trips, 4);
    }

    #[test]
    fn bundle_metrics_landing_rate() {
        let m = BundleMetrics::new();
        for _ in 0..10 {
            m.record_sent();
        }
        for _ in 0..3 {
            m.record_landed();
        }
        let s = m.snapshot();
        assert_eq!(s.bundles_sent, 10);
        assert_eq!(s.bundles_landed, 3);
        assert!((s.landing_rate - 0.3).abs() < 1e-9);
    }

    #[test]
    fn bundle_metrics_failure_categorization() {
        let m = BundleMetrics::new();
        m.record_failed(BundleFailureReason::LowTip);
        m.record_failed(BundleFailureReason::LowTip);
        m.record_failed(BundleFailureReason::StaleState);
        m.record_failed(BundleFailureReason::Unknown);
        let s = m.snapshot();
        assert_eq!(s.bundles_failed_low_tip, 2);
        assert_eq!(s.bundles_failed_stale_state, 1);
        assert_eq!(s.bundles_failed_unknown, 1);
    }

    #[test]
    fn bundle_metrics_landing_rate_zero_when_no_sent() {
        let m = BundleMetrics::new();
        let s = m.snapshot();
        assert_eq!(s.landing_rate, 0.0);
    }

    #[test]
    fn failure_reason_as_str() {
        assert_eq!(BundleFailureReason::LowTip.as_str(), "low_tip");
        assert_eq!(BundleFailureReason::StaleState.as_str(), "stale_state");
        assert_eq!(BundleFailureReason::Unknown.as_str(), "unknown");
    }

    #[test]
    fn bundle_outcome_serializable() {
        let o = BundleOutcome {
            bundle_id: "uuid-test".to_string(),
            timestamp_unix: 1746230000,
            pool_label: "orca_sol_usdc".to_string(),
            probe_size_usd: 200.0,
            tip_lamports: 240_000,
            priority_fee_lamports: 10_000,
            detect_to_send_ms: 27,
            landed: true,
            realized_pnl_usd: 0.42,
            failure_reason: None,
            landed_slot: Some(417_000_000),
        };
        let json = serde_json::to_string(&o).unwrap();
        assert!(json.contains("uuid-test"));
        assert!(json.contains("\"landed\":true"));
    }
}
