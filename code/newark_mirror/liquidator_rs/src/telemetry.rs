//! R49 C4 — pipeline telemetry with sliding-window percentiles + auto-trip.
//! Tracks: decode_to_registry_ms, scan_duration_ms, quote_to_record_ms,
//! mpsc_depth, updates_count.
//!
//! Background monitor every 30s: snapshots tracing log + checks thresholds:
//!   mpsc_depth > 100  → TripReason::TelemetryCritical{ MPSC_BACKLOG }
//!   scan p95 > 100ms × 3 consecutive ticks → TripReason::TelemetryCritical{ SCAN_STALL }

use crate::circuit_breaker::{CircuitBreaker, TripReason};
use parking_lot::Mutex;
use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tracing::info;

pub struct MetricWindow {
    samples: VecDeque<u64>,
    max_size: usize,
}

impl MetricWindow {
    fn new(max_size: usize) -> Self {
        Self {
            samples: VecDeque::with_capacity(max_size),
            max_size,
        }
    }

    fn record(&mut self, value: u64) {
        if self.samples.len() >= self.max_size {
            self.samples.pop_front();
        }
        self.samples.push_back(value);
    }

    fn calculate_percentile(&self, p: f64) -> u64 {
        if self.samples.is_empty() {
            return 0;
        }
        let mut sorted: Vec<u64> = self.samples.iter().cloned().collect();
        sorted.sort_unstable();
        let idx = ((p / 100.0) * (sorted.len() as f64 - 1.0)) as usize;
        sorted[idx]
    }
}

pub struct Telemetry {
    pub decode_to_registry: Mutex<MetricWindow>,
    pub scan_duration: Mutex<MetricWindow>,
    pub quote_to_record: Mutex<MetricWindow>,
    /// Pending items in the mpsc(decoder) channel. Incremented at send-site,
    /// decremented after recv processed.
    pub pending_decodes: AtomicU64,
    pub updates_count: AtomicU64,
}

impl Default for Telemetry {
    fn default() -> Self {
        Self::new()
    }
}

impl Telemetry {
    pub fn new() -> Self {
        Self {
            decode_to_registry: Mutex::new(MetricWindow::new(1000)),
            scan_duration: Mutex::new(MetricWindow::new(100)),
            quote_to_record: Mutex::new(MetricWindow::new(1000)),
            pending_decodes: AtomicU64::new(0),
            updates_count: AtomicU64::new(0),
        }
    }

    pub fn record_decode_to_registry(&self, ms: u64) {
        self.decode_to_registry.lock().record(ms);
    }
    pub fn record_scan_duration(&self, ms: u64) {
        self.scan_duration.lock().record(ms);
    }
    pub fn record_quote_to_record(&self, ms: u64) {
        self.quote_to_record.lock().record(ms);
    }
    pub fn inc_pending(&self) {
        self.pending_decodes.fetch_add(1, Ordering::Relaxed);
    }
    pub fn dec_pending(&self) {
        self.pending_decodes.fetch_sub(1, Ordering::Relaxed);
    }
    pub fn inc_updates(&self) {
        self.updates_count.fetch_add(1, Ordering::Relaxed);
    }

    pub fn get_summary(&self) -> String {
        let d2r = self.decode_to_registry.lock();
        let sd = self.scan_duration.lock();
        let q2r = self.quote_to_record.lock();
        let depth = self.pending_decodes.load(Ordering::Relaxed);
        let ups = self.updates_count.load(Ordering::Relaxed);

        format!(
            "Telemetry:\n  Dec→Reg     p50:{}ms p95:{}ms p99:{}ms\n  ScanLoop    p50:{}ms p95:{}ms\n  Quote→Rec   p50:{}ms p95:{}ms p99:{}ms\n  pending_decodes:{}  updates_count:{}",
            d2r.calculate_percentile(50.0),
            d2r.calculate_percentile(95.0),
            d2r.calculate_percentile(99.0),
            sd.calculate_percentile(50.0),
            sd.calculate_percentile(95.0),
            q2r.calculate_percentile(50.0),
            q2r.calculate_percentile(95.0),
            q2r.calculate_percentile(99.0),
            depth,
            ups
        )
    }
}

/// Background task that snapshots every 30s and trips CB on threshold breach.
pub fn spawn_telemetry_monitor(telemetry: Arc<Telemetry>, cb: Arc<CircuitBreaker>) {
    tokio::spawn(async move {
        let mut scan_stall_count: u32 = 0;
        let mut interval = tokio::time::interval(Duration::from_secs(30));
        loop {
            interval.tick().await;

            let summary = telemetry.get_summary();
            info!("--- 30s telemetry snapshot ---\n{}\n------------------------------", summary);

            // 1. mpsc backlog → trip
            let depth = telemetry.pending_decodes.load(Ordering::Relaxed);
            if depth > 100 {
                cb.trip(TripReason::TelemetryCritical {
                    metric: "MPSC_BACKLOG".to_string(),
                    threshold: 100.0,
                    actual_value: depth as f64,
                });
            }

            // 2. scan stall: p95 > 100ms during 3 consecutive ticks
            let scan_p95 = telemetry.scan_duration.lock().calculate_percentile(95.0);
            if scan_p95 > 100 {
                scan_stall_count += 1;
                if scan_stall_count >= 3 {
                    cb.trip(TripReason::TelemetryCritical {
                        metric: "SCAN_STALL".to_string(),
                        threshold: 100.0,
                        actual_value: scan_p95 as f64,
                    });
                }
            } else {
                scan_stall_count = 0;
            }
        }
    });
}
