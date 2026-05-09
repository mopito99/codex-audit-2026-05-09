//! Domain-agnostic circuit breaker for the merged daemon.
//! R34 Q1 base + R39 Q3 safe_reset + TripReason enum.
//!
//! Trip categorization (R39 Q3):
//!   Transient (auto-reset):  SlotLag       → recovers when lag < 2
//!   Critical  (manual-only): WalletDrain   → requires balance verification
//!   Critical  (safe-reset):  SlippageDivergence, TipExhausted, ConsecutiveFailures
//!     → safe_reset() clears state once operator confirms.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tracing::{error, info, warn};

/// R63 A10.1 + R64 A3.4 fix — Hysteresis con monotonic clock.
///
/// R64 audit MODIFY: AtomicI64 con Unix ts era vulnerable a NTP drift hacia
/// atrás (now - healthy_since podria ser negativo → nunca reset). Cambio a
/// std::time::Instant que es monotónico (siempre creciente, immune a NTP).
///
/// Trip:    slot_lag >= TRIP_THRESHOLD (5)
/// Warn:    slot_lag in [RESET_THRESHOLD, TRIP_THRESHOLD) (2..5)
/// Reset:   slot_lag < RESET_THRESHOLD (2) sostenido 10s consecutivos
const HYSTERESIS_RESET_MIN_DURATION: Duration = Duration::from_secs(10);
const HYSTERESIS_TRIP_THRESHOLD: u64 = 5;
const HYSTERESIS_RESET_THRESHOLD: u64 = 2;

#[derive(Debug, Clone, PartialEq)]
pub enum TripReason {
    SlotLag,
    WalletDrain,
    SlippageDivergence,
    TipExhausted,
    ConsecutiveFailures,
    /// R49 C4 — telemetry trip with diagnostic context.
    TelemetryCritical {
        metric: String,
        threshold: f64,
        actual_value: f64,
    },
}

pub struct CircuitBreaker {
    consecutive_failures: AtomicUsize,
    is_tripped: AtomicBool,
    failure_threshold: usize,
    last_reason: Mutex<Option<TripReason>>,
    /// R63 A10.1 + R64 A3.4 — Hysteresis con monotonic clock.
    /// Some(t) = racha "healthy" empezó en t (Instant). Reset solo cuando
    /// elapsed(t) >= HYSTERESIS_RESET_MIN_DURATION.
    /// None = no hay racha activa.
    healthy_since: Mutex<Option<Instant>>,
}

impl CircuitBreaker {
    pub fn new(threshold: usize) -> Self {
        Self {
            consecutive_failures: AtomicUsize::new(0),
            is_tripped: AtomicBool::new(false),
            failure_threshold: threshold,
            last_reason: Mutex::new(None),
            healthy_since: Mutex::new(None),
        }
    }

    pub fn is_allowed(&self) -> bool {
        !self.is_tripped.load(Ordering::Relaxed)
    }

    pub fn is_tripped(&self) -> bool {
        self.is_tripped.load(Ordering::SeqCst)
    }

    pub fn last_trip_reason(&self) -> Option<TripReason> {
        self.last_reason.lock().unwrap().clone()
    }

    /// R39 Q3 — typed trip. Logs the reason and stores it for safe_reset.
    pub fn trip(&self, reason: TripReason) {
        if !self.is_tripped.swap(true, Ordering::SeqCst) {
            error!("CIRCUIT BREAKER TRIPPED: {:?}", reason);
        }
        *self.last_reason.lock().unwrap() = Some(reason);
    }

    /// Reset the failure counter on a successful TX. Does NOT auto-untrip.
    pub fn report_success(&self) {
        self.consecutive_failures.store(0, Ordering::SeqCst);
    }

    /// Increment consecutive failures; trip with `ConsecutiveFailures` once
    /// threshold reached.
    pub fn report_failure(&self) {
        let prev = self.consecutive_failures.fetch_add(1, Ordering::SeqCst);
        if prev + 1 >= self.failure_threshold {
            self.trip(TripReason::ConsecutiveFailures);
        }
    }

    /// R34 Q1 + R39 Q3 + R63 A10.1 — slot-lag con HYSTERESIS.
    ///
    /// Trip:    slot_lag >= TRIP_THRESHOLD (5)
    /// Warn:    slot_lag in [RESET_THRESHOLD, TRIP_THRESHOLD) (2..5)
    /// Reset:   slot_lag < RESET_THRESHOLD (2) sostenido por
    ///          HYSTERESIS_RESET_MIN_DURATION_SECS (10s) consecutivos.
    ///
    /// Tracking del "healthy streak":
    ///   - Si slot_lag < 2: si no hay racha activa, marca healthy_since_unix = now.
    ///   - Si slot_lag >= 2: clear healthy_since_unix (rompe racha).
    ///   - Reset se ejecuta solo si (now - healthy_since_unix) >= 10s.
    pub fn check_slot_lag(&self, slot_lag: u64) {
        if slot_lag >= HYSTERESIS_TRIP_THRESHOLD {
            self.trip(TripReason::SlotLag);
            *self.healthy_since.lock().unwrap() = None;
            return;
        }

        if slot_lag >= HYSTERESIS_RESET_THRESHOLD {
            *self.healthy_since.lock().unwrap() = None;
            warn!("CIRCUIT BREAKER WARNING: slot lag increasing ({} slots)", slot_lag);
            return;
        }

        // slot_lag < RESET_THRESHOLD → estado saludable instantáneo.
        // R64 A3.4: usar Instant (monotonic clock), inmune a NTP drift.
        let mut healthy_lock = self.healthy_since.lock().unwrap();
        let now = Instant::now();
        let racha_dur = match *healthy_lock {
            None => {
                // No hay racha activa — empezar nueva.
                *healthy_lock = Some(now);
                return;
            }
            Some(start) => now.saturating_duration_since(start),
        };
        if racha_dur < HYSTERESIS_RESET_MIN_DURATION {
            // Aún no consolidada (10s mínimos). NO reset.
            return;
        }

        // Racha consolidada — auto-reset SOLO si trip fue SlotLag.
        drop(healthy_lock);  // liberar antes de tomar last_reason lock
        if self.is_tripped.load(Ordering::SeqCst) {
            let mut reason = self.last_reason.lock().unwrap();
            if matches!(*reason, Some(TripReason::SlotLag)) {
                self.is_tripped.store(false, Ordering::SeqCst);
                *reason = None;
                info!(
                    "CIRCUIT BREAKER RESET (R64 hysteresis monotonic): slot lag recovered \
                     ({} slots) sostenido {:.1}s consecutivos",
                    slot_lag, racha_dur.as_secs_f32()
                );
            }
        }
    }

    /// R39 Q3 — operator-initiated safe reset.
    /// SlotLag → handled automatically; reject manual reset.
    /// WalletDrain → require external verification (return Err).
    /// Others → clear state.
    pub fn safe_reset(&self) -> Result<(), String> {
        let reason = self.last_reason.lock().unwrap().clone();
        match reason {
            Some(TripReason::SlotLag) => {
                Err("SlotLag is handled automatically; no manual reset needed".into())
            }
            Some(TripReason::WalletDrain) => {
                Err("WalletDrain requires manual balance verification before reset".into())
            }
            _ => {
                self.is_tripped.store(false, Ordering::SeqCst);
                self.consecutive_failures.store(0, Ordering::SeqCst);
                *self.last_reason.lock().unwrap() = None;
                info!("CIRCUIT BREAKER: safe_reset performed by operator");
                Ok(())
            }
        }
    }

    /// Manual force-reset escape hatch (after wallet refill, balance verify, etc.).
    /// Bypasses safe_reset rules. Operator responsibility.
    pub fn manual_reset(&self) {
        self.consecutive_failures.store(0, Ordering::SeqCst);
        self.is_tripped.store(false, Ordering::SeqCst);
        *self.last_reason.lock().unwrap() = None;
        info!("CIRCUIT BREAKER: manual_reset performed (force, bypasses policy)");
    }

    pub fn consecutive_failures(&self) -> usize {
        self.consecutive_failures.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_reset_rejects_walletdrain() {
        let cb = CircuitBreaker::new(10);
        cb.trip(TripReason::WalletDrain);
        assert!(cb.safe_reset().is_err());
        assert!(cb.is_tripped());
    }

    #[test]
    fn safe_reset_rejects_slotlag() {
        let cb = CircuitBreaker::new(10);
        cb.trip(TripReason::SlotLag);
        assert!(cb.safe_reset().is_err()); // policy: auto only
    }

    #[test]
    fn safe_reset_clears_slippage() {
        let cb = CircuitBreaker::new(10);
        cb.trip(TripReason::SlippageDivergence);
        assert!(cb.is_tripped());
        cb.safe_reset().unwrap();
        assert!(!cb.is_tripped());
        assert!(cb.last_trip_reason().is_none());
    }

    #[test]
    fn manual_reset_force_clears_anything() {
        let cb = CircuitBreaker::new(10);
        cb.trip(TripReason::WalletDrain);
        cb.manual_reset();
        assert!(!cb.is_tripped());
    }

    #[test]
    fn slot_lag_trip_immediate_R63_A10() {
        let cb = CircuitBreaker::new(10);
        cb.check_slot_lag(7); // >= TRIP_THRESHOLD (5)
        assert!(cb.is_tripped(), "lag 7 → trip immediate");
    }

    #[test]
    fn slot_lag_reset_requires_sustained_10s_R63_A10() {
        // R63 A10.1 hysteresis: reset NO debe ocurrir con un solo lag<2.
        // Solo tras 10s sostenidos.
        let cb = CircuitBreaker::new(10);
        cb.check_slot_lag(7); // trip
        assert!(cb.is_tripped());
        cb.check_slot_lag(0); // primera observación healthy — empieza racha
        // Sin esperar 10s, sigue tripped.
        assert!(cb.is_tripped(), "lag<2 instant NO debe resetear (hysteresis)");
        cb.check_slot_lag(1); // sigue saludable, racha sigue
        assert!(cb.is_tripped(), "lag<2 sostenido pero <10s NO resetea");
    }

    #[test]
    fn slot_lag_warn_zone_breaks_healthy_streak_R63_A10() {
        // Si entras en zona warning (2..5), cualquier racha previa se rompe.
        let cb = CircuitBreaker::new(10);
        cb.check_slot_lag(7); // trip
        cb.check_slot_lag(0); // healthy streak start
        cb.check_slot_lag(3); // zona warning — debe romper racha
        cb.check_slot_lag(0); // empezar racha NUEVA
        // Sigue tripped (racha < 10s).
        assert!(cb.is_tripped());
    }

    #[test]
    fn slot_lag_no_auto_recovery_for_other_trips() {
        let cb = CircuitBreaker::new(10);
        cb.trip(TripReason::SlippageDivergence);
        cb.check_slot_lag(0);
        // Should still be tripped — slot_lag policy only undoes SlotLag trips
        assert!(cb.is_tripped());
    }
}
