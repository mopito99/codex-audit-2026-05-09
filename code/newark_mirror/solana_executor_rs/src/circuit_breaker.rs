#![allow(dead_code)] // observe_slippage/SLIPPAGE_MAX_RATIO usados en Phase 2 LIVE
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

const GAP_WINDOW_SECS: u64  = 60;
const GAP_SPIKE_THRESHOLD:  f64 = 0.005; // 0.5% avg en 60s = manipulación/flash crash
const SLIPPAGE_MAX_RATIO:   f64 = 3.0;   // slippage_real > 3× simulado
const MAX_CONSECUTIVE_FAIL: u32 = 5;     // 5 fallos seguidos = tip o competidor más rápido
const RECOVERY_GAP_MAX:     f64 = 0.0015; // gap_avg < 0.15% durante 30s para recuperarse
const RECOVERY_WINDOW_SECS: u64 = 30;

pub struct CircuitBreaker {
    tripped:          AtomicBool,
    tripped_reason:   Mutex<Option<&'static str>>,
    tripped_at:       Mutex<Option<Instant>>,
    consecutive_fail: AtomicU32,
    // rolling gaps para calcular avg_60s
    gap_history:      Mutex<VecDeque<(f64, Instant)>>,
    // para detectar recuperación
    recovery_start:   Mutex<Option<Instant>>,
}

impl CircuitBreaker {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            tripped:          AtomicBool::new(false),
            tripped_reason:   Mutex::new(None),
            tripped_at:       Mutex::new(None),
            consecutive_fail: AtomicU32::new(0),
            gap_history:      Mutex::new(VecDeque::new()),
            recovery_start:   Mutex::new(None),
        })
    }

    /// Llamar en cada ciclo con el gap actual del pool.
    /// Devuelve Some(reason) si se activa el breaker, None si todo OK.
    pub fn observe_gap(&self, gap_pct: f64) -> Option<&'static str> {
        let now = Instant::now();
        {
            let mut h = self.gap_history.lock().unwrap();
            h.push_back((gap_pct, now));
            h.retain(|(_, ts)| now.duration_since(*ts).as_secs() < GAP_WINDOW_SECS);
        }

        if self.tripped.load(Ordering::Relaxed) {
            return None; // ya está tripeado, no re-evaluar hasta reset
        }

        let avg = self.gap_avg_60s();
        if avg > GAP_SPIKE_THRESHOLD {
            self.trip("gap_spike");
            return Some("gap_spike");
        }
        None
    }

    /// Llamar cuando un bundle falla (status = failed/timeout).
    pub fn record_failure(&self) -> Option<&'static str> {
        if self.tripped.load(Ordering::Relaxed) { return None; }
        let n = self.consecutive_fail.fetch_add(1, Ordering::Relaxed) + 1;
        if n >= MAX_CONSECUTIVE_FAIL {
            self.trip("consecutive_failures");
            return Some("consecutive_failures");
        }
        None
    }

    /// Llamar cuando un bundle aterriza exitosamente.
    pub fn record_success(&self) {
        self.consecutive_fail.store(0, Ordering::Relaxed);
    }

    /// Llamar con el ratio slippage_real / slippage_simulado tras cada trade LIVE.
    pub fn observe_slippage(&self, ratio: f64) -> Option<&'static str> {
        if self.tripped.load(Ordering::Relaxed) { return None; }
        if ratio > SLIPPAGE_MAX_RATIO {
            self.trip("slippage_extreme");
            return Some("slippage_extreme");
        }
        None
    }

    /// True si el breaker está activo (no ejecutar trades).
    pub fn is_tripped(&self) -> bool {
        self.tripped.load(Ordering::Relaxed)
    }

    /// Razón del trip actual (para logs y Telegram).
    pub fn reason(&self) -> Option<&'static str> {
        *self.tripped_reason.lock().unwrap()
    }

    /// Comprobar si las condiciones de recuperación se cumplen.
    /// Recuperación: gap_avg < 0.15% sostenido durante 30s consecutivos.
    /// Llamar periódicamente mientras tripped=true.
    /// Devuelve true si el breaker se ha reseteado.
    pub fn check_recovery(&self) -> bool {
        if !self.tripped.load(Ordering::Relaxed) { return true; }

        let avg = self.gap_avg_60s();
        if avg >= RECOVERY_GAP_MAX {
            // Condición no cumplida — resetear ventana de recuperación
            *self.recovery_start.lock().unwrap() = None;
            return false;
        }

        // avg OK — empezar o continuar ventana de recuperación
        let mut rs = self.recovery_start.lock().unwrap();
        let start = rs.get_or_insert(Instant::now());
        if start.elapsed().as_secs() >= RECOVERY_WINDOW_SECS {
            // 30s consecutivos con gap bajo → reset
            drop(rs);
            self.reset();
            println!("[circuit_breaker] RECUPERADO — gap_avg bajo 30s consecutivos");
            return true;
        }
        false
    }

    fn trip(&self, reason: &'static str) {
        self.tripped.store(true, Ordering::Relaxed);
        *self.tripped_reason.lock().unwrap() = Some(reason);
        *self.tripped_at.lock().unwrap() = Some(Instant::now());
        *self.recovery_start.lock().unwrap() = None;
        eprintln!("[circuit_breaker] TRIP — razón: {}", reason);
    }

    fn reset(&self) {
        self.tripped.store(false, Ordering::Relaxed);
        *self.tripped_reason.lock().unwrap() = None;
        *self.tripped_at.lock().unwrap() = None;
        self.consecutive_fail.store(0, Ordering::Relaxed);
    }

    fn gap_avg_60s(&self) -> f64 {
        let h = self.gap_history.lock().unwrap();
        if h.is_empty() { return 0.0; }
        h.iter().map(|(g, _)| g).sum::<f64>() / h.len() as f64
    }
}
