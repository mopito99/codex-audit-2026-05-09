//! RugCheck — token safety filter para pool selection (Pieza 2 R59).
//!
//! Filtro pre-allocation: descarta tokens con honeypot, freeze authority activo,
//! transfer fee, mint authority no-quemado, holder concentration extrema.
//!
//! API pública gratuita: https://api.rugcheck.xyz/v1
//!
//! Convención de scores RugCheck (descubierto empíricamente 2026-05-03):
//!   - `score_normalised`: 0-100 donde HIGHER = MÁS RIESGO (inverso de safety)
//!   - USDC → 1 (muy seguro)
//!   - BONK → 7 (1 minor risk: mutable metadata)
//!   - WIF  → 23 (holder concentration > 50% top 10)
//!
//! Para alinearnos con Gemma R59 (filtro `RugCheck ≥ 80/100` donde 80 = safe),
//! convertimos: `safety_score = 100 - score_normalised`.
//!
//! Caché in-memory con TTL 1h (G70-style) para evitar re-queries y respetar
//! rate limits de la API gratuita.

use anyhow::{anyhow, Result};
use dashmap::DashMap;
use serde::Deserialize;
use solana_sdk::pubkey::Pubkey;
use std::sync::Arc;
use std::time::{Duration, Instant};

const RUGCHECK_BASE: &str = "https://api.rugcheck.xyz/v1";
/// TTL caché 15 min (Gemma R60 audit Q3 — modificado desde 1h).
/// Razón: un developer puede habilitar mint/freeze authority en segundos.
/// 15 min es compromiso entre rate limits API y safety en long-tail.
const DEFAULT_CACHE_TTL_SECS: u64 = 900;
const DEFAULT_HTTP_TIMEOUT_SECS: u64 = 10;

/// Threshold de seguridad mínimo (Gemma R59 — pools long-tail).
/// Calculado como `100 - score_normalised`. Token rechazado si safety < 80.
pub const SAFETY_THRESHOLD: u32 = 80;

/// Threshold pristine (Gemma R62 audit A1) — más estricto para Mes 1 LIVE.
/// is_pristine() requiere safety_score > PRISTINE_THRESHOLD AND 0 warns.
/// Razón: en Mes 1 (probe $200) priorizamos supervivencia sobre profit.
/// A partir de Mes 3, si data muestra rug rate <X%, se relaja a SAFETY_THRESHOLD.
pub const PRISTINE_THRESHOLD: u32 = 90;

/// Token-2022 program ID (Gemma R60 audit Q6 — blanket reject Phase 1).
/// Razón: puede tener transfer_fee_extension que cobra X% en cada swap.
/// Para arbitraje cíclico, fee 1-5% es "invisible rug" (mata margen).
/// Reject hasta que Pieza 4 implemente parser de extension data.
pub const TOKEN_2022_PROGRAM: &str = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";

/// Respuesta cruda de RugCheck (campos que usamos).
/// Nota: `score` raw cumulativo (e.g. 1148) se ignora — solo nos interesa
/// `score_normalised` clamped 0-100. Removed para evitar warning dead code.
#[derive(Debug, Deserialize, Clone)]
struct RugCheckRaw {
    #[serde(rename = "score_normalised", default)]
    score_normalised: i32,

    #[serde(default)]
    risks: Vec<RawRisk>,

    #[serde(rename = "lpLockedPct", default)]
    lp_locked_pct: f64,

    #[serde(rename = "tokenProgram", default)]
    token_program: String,
}

#[derive(Debug, Deserialize, Clone)]
struct RawRisk {
    #[serde(default)]
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    level: String,
    #[serde(default)]
    score: i32,
}

/// Resultado normalizado y enriquecido para uso operativo.
#[derive(Debug, Clone)]
pub struct RugCheckResult {
    /// Score de seguridad 0-100, MAYOR = más seguro (convención Gemma R59).
    pub safety_score: u32,
    /// Score crudo `score_normalised` original RugCheck (mayor = más riesgo).
    pub raw_risk_score: i32,
    /// % de liquidez del pool/LP que está locked (mayor = más seguro contra rug).
    /// NOTA Gemma R60 audit Q5: NO usar como filtro binario (rejecta 70% de
    /// oportunidades long-tail legítimas). Solo informacional para priorización.
    pub lp_locked_pct: f64,
    /// Cantidad de risks con level "danger" (matan al token).
    pub n_danger_risks: u32,
    /// Cantidad de risks con level "warn" (banderas, no fatales).
    pub n_warn_risks: u32,
    /// Risks más críticos (top 3 por score, danger primero).
    pub top_risks: Vec<RiskSummary>,
    /// Token program (Token vs Token-2022 — afecta transfer fee detection).
    pub token_program: String,
}

#[derive(Debug, Clone)]
pub struct RiskSummary {
    pub name: String,
    pub description: String,
    pub level: String,
    pub score: i32,
}

impl RugCheckResult {
    /// True si el token program es Token-2022 (rejected blanket Phase 1, R60 Q6).
    pub fn is_token_2022(&self) -> bool {
        self.token_program == TOKEN_2022_PROGRAM
    }

    /// Veredicto: ¿token seguro para entrar en pool?
    /// Criteria (Gemma R59 + R60 audit):
    ///   - safety_score >= 80
    ///   - 0 risks de level "danger"
    ///   - NO Token-2022 (R60 Q6 — blanket reject Phase 1)
    pub fn is_safe(&self) -> bool {
        self.safety_score >= SAFETY_THRESHOLD
            && self.n_danger_risks == 0
            && !self.is_token_2022()
    }

    /// Veredicto más estricto (R62 audit A1): score > 90 AND 0 warns AND no Token-2022.
    /// Para Mes 1 LIVE (probe $200) — supervivencia > profit.
    /// A partir de Mes 3 se puede relajar a is_safe() según data observada.
    pub fn is_pristine(&self) -> bool {
        self.safety_score > PRISTINE_THRESHOLD
            && self.n_warn_risks == 0
            && self.n_danger_risks == 0
            && !self.is_token_2022()
    }

    /// Sentinel de "API failed / unsafe" — fail-closed (R62 audit A1).
    /// Llamar este constructor cuando RugCheck API timeout/error.
    /// Siempre is_safe()=false → el orchestrator NO opera con este token.
    pub fn unsafe_fallback() -> Self {
        Self {
            safety_score: 0,
            raw_risk_score: 100,
            lp_locked_pct: 0.0,
            n_danger_risks: 999,
            n_warn_risks: 999,
            top_risks: vec![RiskSummary {
                name: "RUGCHECK_API_FAILED".to_string(),
                description: "API timeout or error — fail-closed treats token as unsafe".to_string(),
                level: "danger".to_string(),
                score: 9999,
            }],
            token_program: "UNKNOWN".to_string(),
        }
    }
}

/// Cliente RugCheck con caché in-memory.
#[derive(Clone)]
pub struct RugCheckClient {
    http: reqwest::Client,
    base_url: String,
    cache: Arc<DashMap<Pubkey, (RugCheckResult, Instant)>>,
    cache_ttl: Duration,
}

impl Default for RugCheckClient {
    fn default() -> Self {
        Self::new()
    }
}

impl RugCheckClient {
    pub fn new() -> Self {
        Self::with_config(RUGCHECK_BASE, DEFAULT_CACHE_TTL_SECS, DEFAULT_HTTP_TIMEOUT_SECS)
    }

    pub fn with_config(base_url: &str, cache_ttl_secs: u64, http_timeout_secs: u64) -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(http_timeout_secs))
            .user_agent("VelocityQuant/0.1 (Cuandeoro Limited)")
            .build()
            .expect("reqwest client builds");
        Self {
            http,
            base_url: base_url.to_string(),
            cache: Arc::new(DashMap::new()),
            cache_ttl: Duration::from_secs(cache_ttl_secs),
        }
    }

    /// Tamaño actual del caché (debugging).
    pub fn cache_size(&self) -> usize {
        self.cache.len()
    }

    /// Limpia el caché (testing / forzar refresh global).
    pub fn cache_clear(&self) {
        self.cache.clear();
    }

    /// Check token safety. Retorna desde caché si <TTL. Sino fetch fresh.
    /// Si fetch falla, propaga Err — caller decide.
    pub async fn check(&self, token: &Pubkey) -> Result<RugCheckResult> {
        // Cache hit
        if let Some(entry) = self.cache.get(token) {
            let (result, ts) = entry.value();
            if ts.elapsed() < self.cache_ttl {
                return Ok(result.clone());
            }
        }

        // Cache miss / expired — fetch
        let raw = self.fetch_raw(token).await?;
        let result = Self::normalize(raw);
        self.cache.insert(*token, (result.clone(), Instant::now()));
        Ok(result)
    }

    /// FAIL-CLOSED variant (R62 audit A1): nunca devuelve Err.
    /// Si la API falla (timeout, network, parse error) → retorna unsafe_fallback().
    /// Esto garantiza que el caller siempre tenga un RugCheckResult, y que
    /// fail mode = "unsafe" automáticamente. Recommended para hot path operativo.
    pub async fn check_or_unsafe(&self, token: &Pubkey) -> RugCheckResult {
        match self.check(token).await {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!(
                    token = %token,
                    error = ?e,
                    "RugCheck API failed → fail-closed unsafe_fallback (R62 A1)"
                );
                RugCheckResult::unsafe_fallback()
            }
        }
    }

    async fn fetch_raw(&self, token: &Pubkey) -> Result<RugCheckRaw> {
        let url = format!("{}/tokens/{}/report/summary", self.base_url, token);
        let resp = self.http.get(&url).send().await
            .map_err(|e| anyhow!("rugcheck http {token}: {e}"))?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(anyhow!("rugcheck {token} status={status} body={}", body));
        }
        let parsed: RugCheckRaw = resp.json().await
            .map_err(|e| anyhow!("rugcheck json parse {token}: {e}"))?;
        Ok(parsed)
    }

    /// Convierte respuesta cruda a resultado normalizado.
    /// `safety_score = 100 - score_normalised` (clamped 0..=100).
    fn normalize(raw: RugCheckRaw) -> RugCheckResult {
        let raw_risk = raw.score_normalised;
        let safety_score = (100i32.saturating_sub(raw_risk)).clamp(0, 100) as u32;

        let mut n_danger = 0u32;
        let mut n_warn = 0u32;
        for r in &raw.risks {
            match r.level.as_str() {
                "danger" | "critical" => n_danger += 1,
                "warn" | "warning" => n_warn += 1,
                _ => {}
            }
        }

        // Top 3 risks por severidad
        let mut sorted_risks = raw.risks.clone();
        sorted_risks.sort_by(|a, b| {
            // Danger > warn > info
            let level_rank = |l: &str| match l {
                "danger" | "critical" => 0,
                "warn" | "warning" => 1,
                _ => 2,
            };
            level_rank(&a.level).cmp(&level_rank(&b.level))
                .then(b.score.cmp(&a.score))
        });
        let top_risks: Vec<RiskSummary> = sorted_risks.into_iter().take(3).map(|r| RiskSummary {
            name: r.name,
            description: r.description,
            level: r.level,
            score: r.score,
        }).collect();

        RugCheckResult {
            safety_score,
            raw_risk_score: raw_risk,
            lp_locked_pct: raw.lp_locked_pct,
            n_danger_risks: n_danger,
            n_warn_risks: n_warn,
            top_risks,
            token_program: raw.token_program,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: build raw response struct from inline literal for unit tests
    /// (no network).
    fn raw(score_norm: i32, risks: Vec<(&str, &str, i32)>, lp: f64) -> RugCheckRaw {
        raw_with_program(score_norm, risks, lp, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    }

    fn raw_with_program(score_norm: i32, risks: Vec<(&str, &str, i32)>, lp: f64, prog: &str) -> RugCheckRaw {
        RugCheckRaw {
            score_normalised: score_norm,
            risks: risks.into_iter().map(|(name, level, s)| RawRisk {
                name: name.to_string(),
                description: String::new(),
                level: level.to_string(),
                score: s,
            }).collect(),
            lp_locked_pct: lp,
            token_program: prog.to_string(),
        }
    }

    #[test]
    fn normalize_usdc_like() {
        // USDC: score_normalised=1, no risks → safety=99, safe
        let r = RugCheckClient::normalize(raw(1, vec![], 0.0));
        assert_eq!(r.safety_score, 99);
        assert_eq!(r.n_danger_risks, 0);
        assert_eq!(r.n_warn_risks, 0);
        assert!(r.is_safe());
        assert!(r.is_pristine());
    }

    #[test]
    fn normalize_bonk_like() {
        // BONK: score_normalised=7, 1 warn risk → safety=93, safe but not pristine
        let r = RugCheckClient::normalize(raw(7, vec![
            ("Mutable metadata", "warn", 100),
        ], 1.6));
        assert_eq!(r.safety_score, 93);
        assert_eq!(r.n_danger_risks, 0);
        assert_eq!(r.n_warn_risks, 1);
        assert!(r.is_safe());
        assert!(!r.is_pristine());
    }

    #[test]
    fn normalize_wif_like() {
        // WIF: score_normalised=23, 1 warn risk (concentration) → safety=77, NOT safe per R59
        let r = RugCheckClient::normalize(raw(23, vec![
            ("High holder concentration", "warn", 1147),
        ], 92.0));
        assert_eq!(r.safety_score, 77);
        assert!(!r.is_safe()); // 77 < 80 threshold
    }

    #[test]
    fn normalize_high_risk_token() {
        // Token con score 60 (peligroso): safety=40, danger risks → MUST reject
        let r = RugCheckClient::normalize(raw(60, vec![
            ("Honeypot detected", "danger", 1000),
            ("Freeze authority active", "danger", 800),
            ("Mint not renounced", "warn", 200),
        ], 0.0));
        assert_eq!(r.safety_score, 40);
        assert_eq!(r.n_danger_risks, 2);
        assert_eq!(r.n_warn_risks, 1);
        assert!(!r.is_safe());
        // Top risks: 2 danger primero, luego warn (sorted)
        assert_eq!(r.top_risks[0].level, "danger");
        assert_eq!(r.top_risks[1].level, "danger");
    }

    #[test]
    fn safety_score_clamps() {
        // score_normalised raro (e.g. negativo o > 100) no rompe
        let r1 = RugCheckClient::normalize(raw(-5, vec![], 0.0));
        assert_eq!(r1.safety_score, 100); // 100 - (-5) = 105 → clamp 100

        let r2 = RugCheckClient::normalize(raw(200, vec![], 0.0));
        assert_eq!(r2.safety_score, 0); // 100 - 200 = -100 → clamp 0
    }

    #[test]
    fn safety_threshold_boundary() {
        // safety=80 exacto debe pasar
        let r80 = RugCheckClient::normalize(raw(20, vec![], 0.0));
        assert_eq!(r80.safety_score, 80);
        assert!(r80.is_safe());

        // safety=79 NO debe pasar
        let r79 = RugCheckClient::normalize(raw(21, vec![], 0.0));
        assert_eq!(r79.safety_score, 79);
        assert!(!r79.is_safe());
    }

    #[test]
    fn top_risks_truncated_to_3() {
        let r = RugCheckClient::normalize(raw(50, vec![
            ("R1", "danger", 100),
            ("R2", "warn", 50),
            ("R3", "warn", 40),
            ("R4", "warn", 30),
            ("R5", "warn", 20),
        ], 0.0));
        assert_eq!(r.top_risks.len(), 3);
        assert_eq!(r.top_risks[0].name, "R1"); // danger first
    }

    #[test]
    fn token_2022_blanket_reject_R60_Q6() {
        // Token-2022 con safety perfecto (99) DEBE ser rechazado por blanket
        let r = RugCheckClient::normalize(raw_with_program(
            1,
            vec![],
            100.0,
            "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        ));
        assert_eq!(r.safety_score, 99);
        assert!(r.is_token_2022());
        assert!(!r.is_safe(), "Token-2022 must be rejected per R60 Q6");
        assert!(!r.is_pristine());
    }

    #[test]
    fn token_classic_with_perfect_safety_passes() {
        // Token clásico (no Token-2022) con safety perfecto debe pasar
        let r = RugCheckClient::normalize(raw_with_program(
            1,
            vec![],
            100.0,
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        ));
        assert!(!r.is_token_2022());
        assert!(r.is_safe());
        assert!(r.is_pristine());
    }

    #[test]
    fn pristine_requires_score_above_90_R62_A1() {
        // R62 audit A1: pristine threshold > 90 (not 80).
        // safety=91 + 0 warns → pristine
        let r91 = RugCheckClient::normalize(raw(9, vec![], 0.0));
        assert_eq!(r91.safety_score, 91);
        assert!(r91.is_pristine(), "safety=91 + 0 warns + no Token-2022 → pristine");

        // safety=90 + 0 warns → NOT pristine (must be > 90, strict)
        let r90 = RugCheckClient::normalize(raw(10, vec![], 0.0));
        assert_eq!(r90.safety_score, 90);
        assert!(!r90.is_pristine(), "safety=90 → NOT pristine, threshold is > 90");

        // safety=89 + 0 warns → NOT pristine
        let r89 = RugCheckClient::normalize(raw(11, vec![], 0.0));
        assert!(!r89.is_pristine());
    }

    #[test]
    fn pristine_rejected_with_any_warn_R62_A1() {
        // safety=99 pero 1 warn → NOT pristine (per R62: 0 warns para Mes 1)
        let r = RugCheckClient::normalize(raw(1, vec![("warn1", "warn", 50)], 0.0));
        assert_eq!(r.safety_score, 99);
        assert!(r.is_safe(), "is_safe permite 1 warn");
        assert!(!r.is_pristine(), "is_pristine NO permite warns");
    }

    #[test]
    fn unsafe_fallback_is_definitively_unsafe_R62_A1() {
        // R62 audit A1: API failure debe retornar resultado fail-closed
        let r = RugCheckResult::unsafe_fallback();
        assert_eq!(r.safety_score, 0);
        assert!(!r.is_safe());
        assert!(!r.is_pristine());
        assert_eq!(r.n_danger_risks, 999);
        assert!(r.top_risks.iter().any(|risk| risk.name == "RUGCHECK_API_FAILED"));
    }

    #[test]
    fn cache_hit_returns_same() {
        let client = RugCheckClient::with_config("http://invalid.local", 60, 1);
        // Pre-fill cache manually
        let pk: Pubkey = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v".parse().unwrap();
        let result = RugCheckResult {
            safety_score: 99, raw_risk_score: 1, lp_locked_pct: 0.0,
            n_danger_risks: 0, n_warn_risks: 0, top_risks: vec![],
            token_program: "x".into(),
        };
        client.cache.insert(pk, (result.clone(), Instant::now()));

        // Cache hit returns identical
        let rt = tokio::runtime::Runtime::new().unwrap();
        let got = rt.block_on(client.check(&pk)).unwrap();
        assert_eq!(got.safety_score, 99);
        assert_eq!(got.n_danger_risks, 0);
    }
}
