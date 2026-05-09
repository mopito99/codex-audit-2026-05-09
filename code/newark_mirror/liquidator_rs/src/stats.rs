//! R48 — DaemonStats: lock-free runtime counters shared with telegram_listener.
//! R49 C4 — wraps Arc<Telemetry> for percentile summaries.
//! Read by `/bot_stats` command, written by cyclic_dispatch + grpc.

use crate::telemetry::Telemetry;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

pub struct DaemonStats {
    pub started_at: Instant,
    pub cyclic_scans: AtomicU64,
    pub cyclic_quotes: AtomicU64,
    pub cyclic_decoded_ok: AtomicU64,
    pub cyclic_decoded_err: AtomicU64,
    /// R64 A4.1 — quotes blocked because Pyth oracle reported Depeg/Stale/Unavailable.
    pub cyclic_depeg_skipped: AtomicU64,
    pub pool_count: AtomicUsize,
    pub last_slot_lag: AtomicU64,
    pub last_jito_tip_lamports: AtomicU64,
    pub circuit_breaker_tripped: AtomicBool,
    pub telemetry: Arc<Telemetry>,
}

impl DaemonStats {
    pub fn new(telemetry: Arc<Telemetry>) -> Self {
        Self {
            started_at: Instant::now(),
            cyclic_scans: AtomicU64::new(0),
            cyclic_quotes: AtomicU64::new(0),
            cyclic_decoded_ok: AtomicU64::new(0),
            cyclic_decoded_err: AtomicU64::new(0),
            cyclic_depeg_skipped: AtomicU64::new(0),
            pool_count: AtomicUsize::new(0),
            last_slot_lag: AtomicU64::new(0),
            last_jito_tip_lamports: AtomicU64::new(0),
            circuit_breaker_tripped: AtomicBool::new(false),
            telemetry,
        }
    }

    pub fn snapshot_text(&self) -> String {
        let uptime_s = self.started_at.elapsed().as_secs();
        let h = uptime_s / 3600;
        let m = (uptime_s % 3600) / 60;
        let s = uptime_s % 60;
        let basic = format!(
            "Bot Stats\n\
             uptime: {h}h{m:02}m{s:02}s\n\
             cyclic.scans: {scans}\n\
             cyclic.quotes: {quotes}\n\
             cyclic.decoded ok/err: {ok}/{err}\n\
             cyclic.depeg_skipped: {depeg}\n\
             pool_count: {pools}\n\
             last_slot_lag: {lag}\n\
             jito_tip_lamports: {tip}\n\
             cb_tripped: {cb}",
            scans = self.cyclic_scans.load(Ordering::Relaxed),
            quotes = self.cyclic_quotes.load(Ordering::Relaxed),
            ok = self.cyclic_decoded_ok.load(Ordering::Relaxed),
            err = self.cyclic_decoded_err.load(Ordering::Relaxed),
            depeg = self.cyclic_depeg_skipped.load(Ordering::Relaxed),
            pools = self.pool_count.load(Ordering::Relaxed),
            lag = self.last_slot_lag.load(Ordering::Relaxed),
            tip = self.last_jito_tip_lamports.load(Ordering::Relaxed),
            cb = if self.circuit_breaker_tripped.load(Ordering::Relaxed) {
                "YES"
            } else {
                "NO"
            },
        );
        format!("{basic}\n\n{}", self.telemetry.get_summary())
    }
}
