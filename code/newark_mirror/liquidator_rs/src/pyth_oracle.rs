//! PythOracle — depeg detection layer (Pieza 6 R59 · Q14e).
//!
//! Vigila precios on-chain de Pyth Network y detecta divergencia entre el
//! precio de pool (CLMM) y el oracle de referencia. Si la divergencia supera
//! threshold → trip Circuit Breaker (TripReason::SlippageDivergence o similar).
//!
//! Casos típicos de uso (R59 Q14e):
//!   - SOL crash 30% en 1h: oracle baja antes que pool → divergencia detectada.
//!   - USDC depeg: stablecoin se aleja de $1 → riesgo crédito, pause inmediato.
//!   - Pool manipulado por whale: pool refleja precio falso → oracle correcto
//!     muestra divergencia → CB trip.
//!
//! Decisión arquitectónica: NO bloquear el hot path con calls a Pyth.
//! Background task que actualiza un cache lock-free de `OraclePrice` cada
//! 1-2s (Pyth on-chain updates ~400ms slot frequency).
//!
//! Filosofía (R59 Q14e + G38):
//!   - Oracle como SAFETY check, NO como trading signal.
//!   - Si Pyth feed stale o down → TRIP por defecto (sin info = peligro).
//!   - Threshold 40 bps default (Gemma R59 Q4) — divergencia > 0.4% → pause.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;
use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::sync::Arc;

/// Threshold default de divergencia: 40 basis points = 0.4% (Gemma R59 Q4).
pub const DEFAULT_DEPEG_BPS: u32 = 40;
/// Max staleness antes de considerar el oracle "down" — 30 segundos.
/// Pyth updates per slot (~400ms), 30s = 75+ slots sin update = problema.
pub const DEFAULT_MAX_STALENESS_SECS: u64 = 30;

/// R62 audit A4: per-pool tier classification para threshold dinámico.
/// Tier 1 (Majors): SOL, USDC, USDT — threshold 40 bps
/// Tier 2 (Mid-cap): JUP, BONK, JTO — threshold 100 bps
/// Tier 3 (Long-tail): tokens nuevos / micro-cap — threshold 200 bps
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PoolTier {
    Major,
    MidCap,
    LongTail,
}

impl PoolTier {
    /// Threshold bps según tier (R62 A4).
    pub fn depeg_threshold_bps(self) -> u32 {
        match self {
            PoolTier::Major => 40,
            PoolTier::MidCap => 100,
            PoolTier::LongTail => 200,
        }
    }
}

/// R62 audit A4: emergency exit timing — staleness escalation.
///   - 30s staleness → Pause Trading (no nuevas posiciones, NO cerrar abiertas)
///   - 5min staleness → Emergency Exit (cerrar posiciones via SafetyWorker)
pub const EMERGENCY_EXIT_STALENESS_SECS: u64 = 300;

/// Acción que debe tomar el orchestrator según severidad de oracle issue.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OracleAction {
    /// Todo OK, continuar normal.
    Continue,
    /// Oracle stale 30s+ pero no llegamos a 5min → pausar nuevas trades.
    PauseNewTrades,
    /// Oracle stale 5min+ → emergency exit, cerrar posiciones.
    EmergencyExit,
}

/// Pyth price feed account addresses para Solana mainnet.
/// Reference: https://pyth.network/developers/price-feed-ids
pub const PYTH_SOL_USD: &str = "H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG";
pub const PYTH_USDC_USD: &str = "Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD";
pub const PYTH_USDT_USD: &str = "3vxLXJqLqF3JG5TCbYycbKWRBbCJQLxQmBGCkyqEEefL";

/// Oracle price snapshot — devuelto por background task.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct OraclePrice {
    pub mint: Pubkey,
    /// Precio en USD (e.g. SOL = ~85.0).
    pub price_usd: f64,
    /// Confidence interval del oracle (Pyth proporciona ±N).
    pub confidence: f64,
    /// Timestamp Unix UTC del último update.
    pub publish_time: i64,
    /// Slot Solana del update.
    pub slot: u64,
}

impl OraclePrice {
    /// Edad del precio en segundos respecto a "ahora".
    pub fn staleness_secs(&self, now_unix: i64) -> i64 {
        (now_unix - self.publish_time).max(0)
    }

    /// Confidence ratio (confidence / price). 0.001 = 0.1% confidence.
    pub fn confidence_ratio(&self) -> f64 {
        if self.price_usd > 0.0 {
            self.confidence / self.price_usd
        } else {
            f64::INFINITY
        }
    }
}

/// Resultado de check de divergencia.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DepegStatus {
    /// Pool y oracle alineados, divergencia < threshold.
    Healthy,
    /// Divergencia > threshold → trip CB.
    Depeg,
    /// Oracle stale (sin update en > max_staleness) → trip por defecto (R59 Q14e).
    Stale,
    /// Oracle inválido o no disponible → trip por defecto.
    Unavailable,
}

impl DepegStatus {
    pub fn should_trip(self) -> bool {
        !matches!(self, DepegStatus::Healthy)
    }
}

/// Decision logic puro — sin side effects, testeable.
///
/// R62 audit A4: ahora acepta `tier` para threshold dinámico per-pool.
pub fn evaluate_depeg(
    pool_price_usd: f64,
    oracle: Option<&OraclePrice>,
    now_unix: i64,
    threshold_bps: u32,
    max_staleness_secs: u64,
) -> DepegStatus {
    let Some(oracle) = oracle else {
        return DepegStatus::Unavailable;
    };

    if oracle.price_usd <= 0.0 || pool_price_usd <= 0.0 {
        return DepegStatus::Unavailable;
    }

    let stale = oracle.staleness_secs(now_unix);
    if stale > max_staleness_secs as i64 {
        return DepegStatus::Stale;
    }

    let divergence_pct = (pool_price_usd - oracle.price_usd).abs() / oracle.price_usd;
    let divergence_bps = (divergence_pct * 10_000.0) as u32;

    if divergence_bps > threshold_bps {
        DepegStatus::Depeg
    } else {
        DepegStatus::Healthy
    }
}

/// Convenience helper R62 A4: usa threshold del tier directamente.
pub fn evaluate_depeg_for_tier(
    pool_price_usd: f64,
    oracle: Option<&OraclePrice>,
    now_unix: i64,
    tier: PoolTier,
    max_staleness_secs: u64,
) -> DepegStatus {
    evaluate_depeg(pool_price_usd, oracle, now_unix, tier.depeg_threshold_bps(), max_staleness_secs)
}

/// R62 audit A4: decide qué acción operativa tomar según staleness.
///   < 30s    → Continue
///   30s-5min → PauseNewTrades
///   > 5min   → EmergencyExit
pub fn decide_oracle_action(
    oracle: Option<&OraclePrice>,
    now_unix: i64,
    pause_threshold_secs: u64,
    emergency_threshold_secs: u64,
) -> OracleAction {
    let Some(oracle) = oracle else {
        return OracleAction::PauseNewTrades; // sin oracle = peligro
    };

    let stale = oracle.staleness_secs(now_unix);
    if stale > emergency_threshold_secs as i64 {
        OracleAction::EmergencyExit
    } else if stale > pause_threshold_secs as i64 {
        OracleAction::PauseNewTrades
    } else {
        OracleAction::Continue
    }
}

/// PythCache — almacena últimos precios oracle, lock-free reads.
#[derive(Debug, Clone)]
pub struct PythCache {
    inner: Arc<dashmap::DashMap<Pubkey, OraclePrice>>,
    /// Última actualización exitosa (para detectar Pyth feed down).
    last_success: Arc<AtomicI64>,
    /// Conteo de fetches OK / fallidos (debugging).
    fetch_ok: Arc<AtomicU64>,
    fetch_err: Arc<AtomicU64>,
}

impl Default for PythCache {
    fn default() -> Self {
        Self::new()
    }
}

impl PythCache {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(dashmap::DashMap::new()),
            last_success: Arc::new(AtomicI64::new(0)),
            fetch_ok: Arc::new(AtomicU64::new(0)),
            fetch_err: Arc::new(AtomicU64::new(0)),
        }
    }

    /// Inserta o actualiza precio en cache.
    pub fn upsert(&self, price: OraclePrice) {
        self.inner.insert(price.mint, price);
        self.last_success
            .store(price.publish_time, Ordering::Relaxed);
        self.fetch_ok.fetch_add(1, Ordering::Relaxed);
    }

    /// Lookup lock-free.
    pub fn get(&self, mint: &Pubkey) -> Option<OraclePrice> {
        self.inner.get(mint).map(|e| *e.value())
    }

    /// Increment fetch error counter (cuando el background task falla).
    pub fn record_error(&self) {
        self.fetch_err.fetch_add(1, Ordering::Relaxed);
    }

    /// Stats (debugging / dashboard).
    pub fn stats(&self) -> PythCacheStats {
        PythCacheStats {
            entries: self.inner.len(),
            last_success_unix: self.last_success.load(Ordering::Relaxed),
            fetch_ok_total: self.fetch_ok.load(Ordering::Relaxed),
            fetch_err_total: self.fetch_err.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PythCacheStats {
    pub entries: usize,
    pub last_success_unix: i64,
    pub fetch_ok_total: u64,
    pub fetch_err_total: u64,
}

/// Helper: parse default Pyth pubkeys for major Solana tokens.
pub fn default_pyth_feeds() -> Result<std::collections::HashMap<&'static str, Pubkey>> {
    let mut m = std::collections::HashMap::new();
    m.insert("SOL/USD", Pubkey::from_str(PYTH_SOL_USD)?);
    m.insert("USDC/USD", Pubkey::from_str(PYTH_USDC_USD)?);
    m.insert("USDT/USD", Pubkey::from_str(PYTH_USDT_USD)?);
    Ok(m)
}

/// PythOracle config.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PythOracleConfig {
    /// Threshold de divergencia (bps). Default 40 = 0.4%.
    pub depeg_threshold_bps: u32,
    /// Max staleness aceptable en segundos. Default 30s.
    pub max_staleness_secs: u64,
    /// Frecuencia de polling on-chain (ms). Default 2000 = 2s.
    pub poll_interval_ms: u64,
}

impl Default for PythOracleConfig {
    fn default() -> Self {
        Self {
            depeg_threshold_bps: DEFAULT_DEPEG_BPS,
            max_staleness_secs: DEFAULT_MAX_STALENESS_SECS,
            poll_interval_ms: 2000,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pk(s: &str) -> Pubkey {
        Pubkey::from_str(s).unwrap()
    }

    fn oracle(price: f64, conf: f64, age_secs: i64) -> OraclePrice {
        let now = 1746230000i64;
        OraclePrice {
            mint: pk(PYTH_SOL_USD),
            price_usd: price,
            confidence: conf,
            publish_time: now - age_secs,
            slot: 1000,
        }
    }

    #[test]
    fn healthy_when_pool_close_to_oracle() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 5);
        // Pool 85.10 vs oracle 85.0 → 0.118% = 11.8 bps < 40 threshold
        let status = evaluate_depeg(85.10, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Healthy);
    }

    #[test]
    fn depeg_when_pool_diverges_above_threshold() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 5);
        // Pool 86.0 vs oracle 85.0 → 1.176% = 117 bps > 40 threshold
        let status = evaluate_depeg(86.0, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Depeg);
        assert!(status.should_trip());
    }

    #[test]
    fn stale_when_oracle_too_old() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 100); // 100s viejo > 30s max
        let status = evaluate_depeg(85.0, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Stale);
        assert!(status.should_trip());
    }

    #[test]
    fn unavailable_when_no_oracle() {
        let status = evaluate_depeg(85.0, None, 1746230000, 40, 30);
        assert_eq!(status, DepegStatus::Unavailable);
        assert!(status.should_trip());
    }

    #[test]
    fn unavailable_when_zero_oracle_price() {
        let now = 1746230000i64;
        let o = OraclePrice {
            mint: pk(PYTH_SOL_USD),
            price_usd: 0.0,
            confidence: 0.0,
            publish_time: now - 5,
            slot: 1000,
        };
        let status = evaluate_depeg(85.0, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Unavailable);
    }

    #[test]
    fn unavailable_when_zero_pool_price() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 5);
        let status = evaluate_depeg(0.0, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Unavailable);
    }

    #[test]
    fn boundary_at_exact_threshold_is_healthy() {
        let now = 1746230000i64;
        let o = oracle(100.0, 0.1, 5);
        // Pool 100.40 vs oracle 100.0 → 0.4% = 40 bps (NOT > 40, equal)
        let status = evaluate_depeg(100.40, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Healthy);
    }

    #[test]
    fn boundary_above_threshold_is_depeg() {
        let now = 1746230000i64;
        let o = oracle(100.0, 0.1, 5);
        // Pool 100.50 vs oracle 100.0 → 0.5% = 50 bps > 40
        let status = evaluate_depeg(100.50, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Depeg);
    }

    #[test]
    fn negative_divergence_also_detected() {
        let now = 1746230000i64;
        let o = oracle(100.0, 0.1, 5);
        // Pool 99.0 vs oracle 100.0 → 1.0% = 100 bps > 40
        let status = evaluate_depeg(99.0, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Depeg);
    }

    #[test]
    fn stable_depeg_detected_at_50bps() {
        // USDC depeg case: oracle says $1.00, pool says $0.995 (50 bps below)
        let now = 1746230000i64;
        let o = OraclePrice {
            mint: pk(PYTH_USDC_USD),
            price_usd: 1.00,
            confidence: 0.001,
            publish_time: now - 2,
            slot: 1000,
        };
        // Pool 0.995 → 50 bps divergence > 40 threshold → DEPEG
        let status = evaluate_depeg(0.995, Some(&o), now, 40, 30);
        assert_eq!(status, DepegStatus::Depeg);
    }

    #[test]
    fn cache_upsert_and_get() {
        let cache = PythCache::new();
        let p = oracle(85.0, 0.05, 0);
        cache.upsert(p);
        let got = cache.get(&p.mint);
        assert!(got.is_some());
        assert_eq!(got.unwrap().price_usd, 85.0);
    }

    #[test]
    fn cache_stats_track_correctly() {
        let cache = PythCache::new();
        let p1 = oracle(85.0, 0.05, 0);
        cache.upsert(p1);
        cache.record_error();
        cache.record_error();
        let s = cache.stats();
        assert_eq!(s.entries, 1);
        assert_eq!(s.fetch_ok_total, 1);
        assert_eq!(s.fetch_err_total, 2);
        assert!(s.last_success_unix > 0);
    }

    #[test]
    fn cache_get_missing_returns_none() {
        let cache = PythCache::new();
        let missing_pk = pk("So11111111111111111111111111111111111111112");
        assert!(cache.get(&missing_pk).is_none());
    }

    #[test]
    fn cache_upsert_overwrites_same_mint() {
        let cache = PythCache::new();
        let p1 = oracle(85.0, 0.05, 0);
        cache.upsert(p1);
        let p2 = OraclePrice {
            mint: p1.mint,
            price_usd: 86.5,
            confidence: 0.04,
            publish_time: p1.publish_time + 1,
            slot: 1001,
        };
        cache.upsert(p2);
        let got = cache.get(&p1.mint).unwrap();
        assert_eq!(got.price_usd, 86.5);
    }

    #[test]
    fn confidence_ratio_calc() {
        let p = OraclePrice {
            mint: pk(PYTH_SOL_USD),
            price_usd: 100.0,
            confidence: 0.5,
            publish_time: 0,
            slot: 0,
        };
        assert!((p.confidence_ratio() - 0.005).abs() < 1e-9);

        // Edge case: zero price
        let zero = OraclePrice {
            mint: pk(PYTH_SOL_USD),
            price_usd: 0.0,
            confidence: 0.5,
            publish_time: 0,
            slot: 0,
        };
        assert!(zero.confidence_ratio().is_infinite());
    }

    #[test]
    fn default_pyth_feeds_parse_correctly() {
        let feeds = default_pyth_feeds().unwrap();
        assert_eq!(feeds.len(), 3);
        assert!(feeds.contains_key("SOL/USD"));
        assert!(feeds.contains_key("USDC/USD"));
        assert!(feeds.contains_key("USDT/USD"));
    }

    #[test]
    fn config_default_values() {
        let c = PythOracleConfig::default();
        assert_eq!(c.depeg_threshold_bps, 40);
        assert_eq!(c.max_staleness_secs, 30);
        assert_eq!(c.poll_interval_ms, 2000);
    }

    #[test]
    fn tier_thresholds_R62_A4() {
        // R62 A4: tier-based per-pool thresholds
        assert_eq!(PoolTier::Major.depeg_threshold_bps(), 40);
        assert_eq!(PoolTier::MidCap.depeg_threshold_bps(), 100);
        assert_eq!(PoolTier::LongTail.depeg_threshold_bps(), 200);
    }

    #[test]
    fn evaluate_depeg_for_tier_long_tail_R62_A4() {
        let now = 1746230000i64;
        let o = oracle(100.0, 0.5, 5);
        // Pool 100.0 ↔ 101.0 = 100 bps. Major reject (>40), MidCap exact (=100, not >),
        // LongTail allow (<=200).
        let s_major = evaluate_depeg_for_tier(101.0, Some(&o), now, PoolTier::Major, 30);
        assert_eq!(s_major, DepegStatus::Depeg);

        let s_mid = evaluate_depeg_for_tier(101.0, Some(&o), now, PoolTier::MidCap, 30);
        // 100 bps == threshold → NOT > → Healthy (boundary)
        assert_eq!(s_mid, DepegStatus::Healthy);

        let s_long = evaluate_depeg_for_tier(101.0, Some(&o), now, PoolTier::LongTail, 30);
        assert_eq!(s_long, DepegStatus::Healthy);

        // Pool 103.0 (300 bps) → todos depeg
        let s_long_x = evaluate_depeg_for_tier(103.0, Some(&o), now, PoolTier::LongTail, 30);
        assert_eq!(s_long_x, DepegStatus::Depeg);
    }

    #[test]
    fn decide_oracle_action_continue_when_fresh_R62_A4() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 5);
        let action = decide_oracle_action(Some(&o), now, 30, 300);
        assert_eq!(action, OracleAction::Continue);
    }

    #[test]
    fn decide_oracle_action_pause_at_30s_to_5min_R62_A4() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 60); // 60s old
        let action = decide_oracle_action(Some(&o), now, 30, 300);
        assert_eq!(action, OracleAction::PauseNewTrades);
    }

    #[test]
    fn decide_oracle_action_emergency_at_5min_R62_A4() {
        let now = 1746230000i64;
        let o = oracle(85.0, 0.05, 360); // 6min old
        let action = decide_oracle_action(Some(&o), now, 30, 300);
        assert_eq!(action, OracleAction::EmergencyExit);
    }

    #[test]
    fn decide_oracle_action_no_oracle_pauses_R62_A4() {
        let action = decide_oracle_action(None, 1746230000, 30, 300);
        assert_eq!(action, OracleAction::PauseNewTrades);
    }
}
