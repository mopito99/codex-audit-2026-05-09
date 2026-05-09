// Logger persistente: stats.json + opportunities.jsonl + bundles.jsonl
// Espejo de src/logger.ts del bot Node.

use crate::config::{name_for, LOG_DIR};
use crate::jupiter::CyclicArb;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PairStats {
    pub probes: u64,
    pub fails: u64,
    #[serde(rename = "opsSeen")] pub ops_seen: u64,
    #[serde(rename = "opsProfitable")] pub ops_profitable: u64,
    #[serde(rename = "sumNetProfit")] pub sum_net_profit: f64,
    #[serde(rename = "bestNetProfit")] pub best_net_profit: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionStats {
    #[serde(rename = "startedAt")] pub started_at: String,
    #[serde(rename = "paperMode")] pub paper_mode: bool,
    #[serde(rename = "probesTotal")] pub probes_total: u64,
    #[serde(rename = "probesFailed")] pub probes_failed: u64,
    #[serde(rename = "probesApiError")] pub probes_api_error: u64,
    #[serde(rename = "probesNoRoute")] pub probes_no_route: u64,
    #[serde(rename = "probesNoProfit")] pub probes_no_profit: u64,
    #[serde(rename = "opsSeen")] pub ops_seen: u64,
    #[serde(rename = "opsProfitable")] pub ops_profitable: u64,
    #[serde(rename = "totalSimProfit")] pub total_sim_profit: f64,
    #[serde(rename = "bundlesSent")] pub bundles_sent: u64,
    #[serde(rename = "bundlesLanded")] pub bundles_landed: u64,
    #[serde(rename = "bundlesFailed")] pub bundles_failed: u64,
    #[serde(rename = "bundlesTimeout")] pub bundles_timeout: u64,
    #[serde(rename = "realizedProfit")] pub realized_profit: f64,
    #[serde(rename = "lastLandedSig")] pub last_landed_sig: Option<String>,
    #[serde(rename = "lastLandedAt")] pub last_landed_at: Option<String>,
    #[serde(rename = "byPair")] pub by_pair: HashMap<String, PairStats>,
}

#[derive(Clone)]
pub struct Logger {
    inner: Arc<Mutex<Inner>>,
}

struct Inner {
    stats: SessionStats,
    pending_bundles: HashMap<String, (f64, String, f64)>, // bundleId -> (expectedProfit, intermediate, inputUsdc)
    log_dir: PathBuf,
}

#[derive(Serialize)]
struct OpportunityEntry<'a> {
    ts: String,
    intermediate: &'a str,
    #[serde(rename = "inputUsdc")] input_usdc: f64,
    #[serde(rename = "outputUsdc")] output_usdc: f64,
    #[serde(rename = "grossProfit")] gross_profit: f64,
    #[serde(rename = "netProfit")] net_profit: f64,
    #[serde(rename = "profitBps")] profit_bps: f64,
    #[serde(rename = "leg1Dexes")] leg1_dexes: &'a [String],
    #[serde(rename = "leg2Dexes")] leg2_dexes: &'a [String],
}

#[derive(Serialize)]
struct BundleEntry<'a> {
    ts: String,
    #[serde(rename = "bundleId")] bundle_id: &'a str,
    endpoint: &'a str,
    #[serde(rename = "expectedProfit")] expected_profit: f64,
    status: &'a str,
    arb: BundleArbInfo,
}

#[derive(Serialize)]
struct BundleArbInfo { intermediate: String, #[serde(rename = "inputUsdc")] input_usdc: f64 }

impl Logger {
    pub fn new(paper_mode: bool) -> Self {
        let log_dir = PathBuf::from(LOG_DIR);
        let _ = fs::create_dir_all(&log_dir);
        Self {
            inner: Arc::new(Mutex::new(Inner {
                stats: SessionStats {
                    started_at: Utc::now().to_rfc3339(),
                    paper_mode,
                    probes_total: 0, probes_failed: 0, probes_api_error: 0,
                    probes_no_route: 0, probes_no_profit: 0,
                    ops_seen: 0, ops_profitable: 0, total_sim_profit: 0.0,
                    bundles_sent: 0, bundles_landed: 0, bundles_failed: 0, bundles_timeout: 0,
                    realized_profit: 0.0, last_landed_sig: None, last_landed_at: None,
                    by_pair: HashMap::new(),
                },
                pending_bundles: HashMap::new(),
                log_dir,
            })),
        }
    }

    fn pair_key(intermediate: &str, amount: f64) -> String {
        format!("{}@{}", name_for(intermediate), amount as u64)
    }

    pub fn record_probe(&self, intermediate: &str, amount: f64, status: &str) {
        let mut inner = self.inner.lock().unwrap();
        inner.stats.probes_total += 1;
        match status {
            "api_error" => { inner.stats.probes_api_error += 1; inner.stats.probes_failed += 1; }
            "no_route"  => { inner.stats.probes_no_route  += 1; inner.stats.probes_failed += 1; }
            "no_profit" => { inner.stats.probes_no_profit += 1; }
            _ => {}
        }
        let key = Self::pair_key(intermediate, amount);
        let ps = inner.stats.by_pair.entry(key).or_default();
        ps.probes += 1;
        if status == "api_error" || status == "no_route" { ps.fails += 1; }
    }

    pub fn record_opportunity(&self, arb: &CyclicArb, profitable: bool) {
        let mut inner = self.inner.lock().unwrap();
        inner.stats.ops_seen += 1;
        if profitable {
            inner.stats.ops_profitable += 1;
            inner.stats.total_sim_profit += arb.net_profit;
        }
        let key = Self::pair_key(&arb.intermediate, arb.input_usdc);
        let ps = inner.stats.by_pair.entry(key).or_default();
        ps.ops_seen += 1;
        if profitable {
            ps.ops_profitable += 1;
            ps.sum_net_profit += arb.net_profit;
        }
        if arb.net_profit > ps.best_net_profit {
            ps.best_net_profit = arb.net_profit;
        }
        if profitable {
            let intermediate_name = name_for(&arb.intermediate);
            let path = inner.log_dir.join("opportunities.jsonl");
            let entry = OpportunityEntry {
                ts: Utc::now().to_rfc3339(),
                intermediate: intermediate_name,
                input_usdc: arb.input_usdc,
                output_usdc: arb.output_usdc,
                gross_profit: arb.gross_profit,
                net_profit: arb.net_profit,
                profit_bps: arb.profit_bps,
                leg1_dexes: &arb.leg1_dexes,
                leg2_dexes: &arb.leg2_dexes,
            };
            if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&path) {
                let _ = writeln!(f, "{}", serde_json::to_string(&entry).unwrap_or_default());
            }
        }
    }

    pub fn record_bundle_sent(&self, bundle_id: &str, endpoint: &str, expected_profit: f64, intermediate: &str, input_usdc: f64) {
        let mut inner = self.inner.lock().unwrap();
        inner.stats.bundles_sent += 1;
        inner.pending_bundles.insert(
            bundle_id.to_string(),
            (expected_profit, intermediate.to_string(), input_usdc),
        );
        let path = inner.log_dir.join("bundles.jsonl");
        let entry = BundleEntry {
            ts: Utc::now().to_rfc3339(),
            bundle_id, endpoint,
            expected_profit,
            status: "sent",
            arb: BundleArbInfo { intermediate: name_for(intermediate).to_string(), input_usdc },
        };
        if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(f, "{}", serde_json::to_string(&entry).unwrap_or_default());
        }
    }

    pub fn record_bundle_status(&self, bundle_id: &str, status: &str) {
        let mut inner = self.inner.lock().unwrap();
        match status {
            "landed" => {
                inner.stats.bundles_landed += 1;
                if let Some((expected, _, _)) = inner.pending_bundles.get(bundle_id).cloned() {
                    inner.stats.realized_profit += expected;
                    inner.stats.last_landed_sig = Some(bundle_id.to_string());
                    inner.stats.last_landed_at = Some(Utc::now().to_rfc3339());
                }
            }
            "failed"  => inner.stats.bundles_failed  += 1,
            "timeout" => inner.stats.bundles_timeout += 1,
            _ => {}
        }
        let pending = inner.pending_bundles.remove(bundle_id);
        if let Some((expected, intermediate, input_usdc)) = pending {
            let path = inner.log_dir.join("bundles.jsonl");
            let entry = BundleEntry {
                ts: Utc::now().to_rfc3339(),
                bundle_id, endpoint: "",
                expected_profit: expected,
                status,
                arb: BundleArbInfo { intermediate: name_for(&intermediate).to_string(), input_usdc },
            };
            if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&path) {
                let _ = writeln!(f, "{}", serde_json::to_string(&entry).unwrap_or_default());
            }
        }
    }

    pub fn flush(&self) {
        let inner = self.inner.lock().unwrap();
        let path = inner.log_dir.join("stats.json");
        if let Ok(json) = serde_json::to_string_pretty(&inner.stats) {
            let _ = fs::write(path, json);
        }
    }

    pub fn summary_line(&self) -> String {
        let s = &self.inner.lock().unwrap().stats;
        let rate = if s.probes_total > 0 { s.ops_profitable as f64 / s.probes_total as f64 * 100.0 } else { 0.0 };
        format!(
            "probes={} api_err={} no_route={} no_profit={} ops={}/{} hit={:.2}% sim_profit=${:.4} bundles_sent={} landed={}",
            s.probes_total, s.probes_api_error, s.probes_no_route, s.probes_no_profit,
            s.ops_profitable, s.ops_seen, rate, s.total_sim_profit,
            s.bundles_sent, s.bundles_landed
        )
    }

    pub fn record_fat_finger_paper(&self, name: &str, gap: f64, probe_usdc: f64) {
        let inner = self.inner.lock().unwrap();
        let path = inner.log_dir.join("opportunities.jsonl");
        let entry = serde_json::json!({
            "ts": Utc::now().to_rfc3339(),
            "type": "fat_finger_paper",
            "name": name,
            "gap_pct": (gap * 10000.0).round() / 100.0,
            "probe_usdc": probe_usdc,
        });
        if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(f, "{}", entry);
        }
    }
}
