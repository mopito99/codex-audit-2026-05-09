//! Shadow logger — writes hypothetical opportunities to JSONL for offline
//! analysis. Schema per R28 Q1.

use crate::cycle_finder::{dir_str, CycleQuote};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ShadowRecord {
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub slot: u64,
    pub slot_lag: u64,           // R31 Q2: current_slot − max_pool_slot
    pub cycle_path: Vec<String>, // e.g. ["USDC", "SOL", "USDC"]
    pub pools: Vec<String>,      // ["orca_sol_usdc", "raydium_sol_usdc"]
    pub amount_in: u128,
    pub amount_out: u128,
    pub net_profit_base_units: i128,
    pub amount_in_usd: f64,
    pub latency_ms: i64,
    pub leg0_dir: String,
    pub leg1_dir: String,
    pub sqrt_price_0: u128,
    pub sqrt_price_1: u128,
    pub p75_priority_fee_per_cu: u64,
    pub priority_fee_lamports: u64, // R34 Q2: leader-side fee
    pub jito_tip_lamports: u64,     // R34 Q2: validator-side tip
    pub total_cost_lamports: u64,   // priority_fee + jito_tip
    pub net_profit_usd: f64,        // R35 Q0: USD-corrected
    pub total_cost_usd: f64,        // R35 Q0: USD-corrected
    pub would_send: bool,
    pub stale_due_to_missing_ticks: bool,
    pub slippage_bps_0: u16,             // R35 Q3 dynamic slippage
    pub slippage_bps_1: u16,
    pub min_intermediate_out: u128,
    pub min_final_out: u128,
    pub is_outlier: bool,
    /// R48 C3 — generated when would_send=true. None for non-actionable scans.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bundle_id: Option<String>,
    /// R74 V3 Visibility Phase (Gemma spec) — desambigua el "by_other"
    /// del gating breakdown. cb_blocked=true cuando CB.is_allowed()=false
    /// al evaluar would_send. depeg_blocked=true cuando el Pyth depeg
    /// gate bloqueó este quote. Permite separar al 47% que hoy es
    /// "CB O depeg" en sus 2 causas reales.
    pub cb_blocked: bool,
    pub depeg_blocked: bool,
    /// r144 firma Gemma Q1 — audit trail del effective profit floor aplicado en
    /// would_send. SHADOW=$0.10, LIVE=$1.00. Permite verificar post-mortem qué
    /// floor se usó en cada cycle.
    pub min_profit_usd_applied: f64,
}

/// R48 C3 — canonical memo string for on-chain pairing.
pub fn format_bundle_id_for_memo(uuid: &str) -> String {
    format!("cyclic-arb:{uuid}")
}

pub struct ShadowLogger {
    path: PathBuf,
    file: Mutex<std::fs::File>,
}

impl ShadowLogger {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        Ok(Self {
            path,
            file: Mutex::new(file),
        })
    }

    pub fn path(&self) -> &PathBuf {
        &self.path
    }

    pub fn write(&self, rec: &ShadowRecord) -> Result<()> {
        let line = serde_json::to_string(rec)?;
        let mut f = self.file.lock().unwrap();
        f.write_all(line.as_bytes())?;
        f.write_all(b"\n")?;
        Ok(())
    }

    /// R39 Q4 — append a LiveOutcome record. Reuses the same JSONL file; a
    /// dedicated `live_attempts.jsonl` writer can be added later by passing
    /// a different ShadowLogger to `log_live_outcome` callers.
    pub fn write_live_outcome(&self, outcome: &LiveOutcome) -> Result<()> {
        let line = serde_json::to_string(outcome)?;
        let mut f = self.file.lock().unwrap();
        f.write_all(line.as_bytes())?;
        f.write_all(b"\n")?;
        Ok(())
    }
}

/// R39 Q4 — Live execution outcome (paired with a ShadowRecord by `bundle_id`).
/// `actual_profit_usd` is computed externally from balance deltas:
///   profit_real = (balance_post - balance_pre) - priority_fee_usd - jito_tip_usd
/// `deviation_bps` = (actual - expected) / |expected| × 10_000 (signed).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiveOutcome {
    pub timestamp: chrono::DateTime<chrono::Utc>,
    pub bundle_id: String,
    pub sig: String,
    pub status: String, // "landed" | "failed" | "timeout"
    pub slot_sent: u64,
    pub slot_landed: Option<u64>,
    pub expected_profit_usd: f64,
    pub expected_cost_usd: f64,
    pub actual_profit_usd: f64,
    pub actual_priority_fee_lamports: u64,
    pub actual_jito_tip_lamports: u64,
    pub deviation_bps: i64,
    pub execution_time_ms: u64,
}

pub fn deviation_bps(expected: f64, actual: f64) -> i64 {
    if expected.abs() < f64::EPSILON {
        return 0;
    }
    ((actual - expected) / expected.abs() * 10_000.0) as i64
}

/// Build a ShadowRecord from a CycleQuote. The caller provides:
///   `slot`              — max slot among the registry pools
///   `latency_ms`        — Utc::now() - max(updated_at) of the legs
///   `amount_in_usd`     — pre-computed (depends on the input token)
///   `cycle_path_tokens` — ["USDC","SOL","USDC"] etc., caller-provided
///   `p75_priority_fee_per_cu`, `threshold_lamports`, `would_send`
pub fn build_record(
    quote: &CycleQuote,
    slot: u64,
    latency_ms: i64,
    slot_lag: u64,
    amount_in_usd: f64,
    cycle_path_tokens: Vec<String>,
    p75_priority_fee_per_cu: u64,
    priority_fee_lamports: u64,
    jito_tip_lamports: u64,
    total_cost_lamports: u64,
    net_profit_usd: f64,
    total_cost_usd: f64,
    would_send: bool,
    bundle_id: Option<String>,
    // R74 V3 Visibility Phase — flags para desambiguar by_other gating.
    cb_blocked: bool,
    depeg_blocked: bool,
    // r144 firma Gemma Q1 — effective profit floor aplicado en este cycle.
    min_profit_usd_applied: f64,
) -> ShadowRecord {
    ShadowRecord {
        timestamp: chrono::Utc::now(),
        slot,
        slot_lag,
        cycle_path: cycle_path_tokens,
        pools: vec![quote.leg0_label.clone(), quote.leg1_label.clone()],
        amount_in: quote.amount_in,
        amount_out: quote.final_out,
        net_profit_base_units: quote.net,
        amount_in_usd,
        latency_ms,
        leg0_dir: dir_str(quote.leg0_dir).into(),
        leg1_dir: dir_str(quote.leg1_dir).into(),
        sqrt_price_0: quote.sqrt_price_0,
        sqrt_price_1: quote.sqrt_price_1,
        p75_priority_fee_per_cu,
        priority_fee_lamports,
        jito_tip_lamports,
        total_cost_lamports,
        net_profit_usd,
        total_cost_usd,
        would_send,
        stale_due_to_missing_ticks: quote.stale_due_to_missing_ticks,
        slippage_bps_0: quote.slippage_bps_0,
        slippage_bps_1: quote.slippage_bps_1,
        min_intermediate_out: quote.min_intermediate_out,
        min_final_out: quote.min_final_out,
        is_outlier: amount_in_usd > 1000.0,
        bundle_id,
        cb_blocked,
        depeg_blocked,
        min_profit_usd_applied,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clmm_math::SwapDirection;
    use solana_sdk::pubkey::Pubkey;

    fn fake_quote() -> CycleQuote {
        CycleQuote {
            leg0_pool: Pubkey::new_unique(),
            leg1_pool: Pubkey::new_unique(),
            leg0_label: "orca_sol_usdc".into(),
            leg1_label: "raydium_sol_usdc".into(),
            leg0_dir: SwapDirection::Lower,
            leg1_dir: SwapDirection::Upper,
            sqrt_price_0: 1u128 << 64,
            sqrt_price_1: (1u128 << 64) + 1,
            liquidity_0: 1_000_000_000,
            liquidity_1: 1_000_000_000,
            amount_in: 1_000_000,
            intermediate_out: 500_000,
            final_out: 1_001_000,
            net: 1_000,
            gross_bps: 10.0,
            stale_due_to_missing_ticks: false,
            slippage_bps_0: 5,
            slippage_bps_1: 5,
            min_intermediate_out: 499_750,
            min_final_out: 1_000_500,
        }
    }

    #[test]
    fn write_record_roundtrips() {
        let tmp = std::env::temp_dir().join("cyclic_shadow_test.jsonl");
        let _ = std::fs::remove_file(&tmp);
        let logger = ShadowLogger::open(&tmp).unwrap();
        let q = fake_quote();
        let rec = build_record(
            &q,
            42,
            12,
            3,
            1.0,
            vec!["USDC".into(), "SOL".into(), "USDC".into()],
            5_000,        // p75_priority_fee_per_cu
            10_000_000,   // priority_fee_lamports
            240_000,      // jito_tip_lamports
            10_240_000,   // total_cost_lamports
            0.001,        // net_profit_usd
            0.0436,       // total_cost_usd
            true,
            Some("test-uuid-1234".into()),
        );
        logger.write(&rec).unwrap();
        let body = std::fs::read_to_string(&tmp).unwrap();
        assert!(body.contains("\"would_send\":true"));
        assert!(body.contains("\"leg0_dir\":\"B->A\""));
        assert!(body.contains("\"latency_ms\":12"));
        assert!(body.contains("\"slot_lag\":3"));
    }
}
