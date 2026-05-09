//! PoolRegistry — hot-reloadable multi-pool configuration (Pieza 4 R59).
//!
//! Lee TOML desde disco, ofrece lectura lock-free vía ArcSwap, y observa
//! cambios al archivo para hot-reload sin reiniciar daemon.
//!
//! Uso:
//!   let registry = PoolRegistry::load_from_toml("pools.toml").await?;
//!   spawn_watcher(registry.clone(), "pools.toml");
//!   let snapshot = registry.snapshot();   // Arc<PoolSet> lock-free
//!
//! TOML format (`pools.toml` ejemplo):
//! ```toml
//! [global]
//! probe_usd = 1.0
//! cycle_path = ["USDC", "SOL", "USDC"]
//! scan_interval_ms = 200
//!
//! [[pool]]
//! label = "orca_sol_usdc"
//! address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
//! kind = "orca"
//! cap_usd = 2000.0
//! score = 0.85
//! enabled = true
//!
//! [[pool]]
//! label = "raydium_sol_usdc"
//! address = "..."
//! kind = "raydium"
//! cap_usd = 2000.0
//! score = 0.78
//! enabled = true
//! ```

use anyhow::{anyhow, Context, Result};
use arc_swap::ArcSwap;
use cyclic_rs::config::{PoolEntry, PoolKind};
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Arc;

/// TOML-deserialized pool entry (richer than cyclic_rs::config::PoolEntry).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PoolToml {
    pub label: String,
    pub address: String,
    /// "orca" | "raydium" | "meteora"
    pub kind: String,
    /// Capital máximo USD asignado a este pool (per Gemma R59 Q2).
    pub cap_usd: f64,
    /// Score G79 ranking (0-1) — mayor = más prioritario.
    #[serde(default = "default_score")]
    pub score: f64,
    /// R63 A4.1 fix: tier para Pyth Oracle threshold per-pool.
    /// "major" | "midcap" | "longtail". Default "longtail" (más permisivo) —
    /// si no especificas, asumimos pool desconocido y aplicamos threshold flojo.
    #[serde(default = "default_tier")]
    pub tier: String,
    /// Disable temporal sin borrar entry (manual override).
    #[serde(default = "default_enabled")]
    pub enabled: bool,
}

fn default_score() -> f64 { 0.5 }
fn default_enabled() -> bool { true }
fn default_tier() -> String { "longtail".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GlobalConfig {
    /// Probe base size en USDC (e.g. 1.0 = $1 probe).
    pub probe_usd: f64,
    /// Token cycle path para cycle_finder.
    pub cycle_path: Vec<String>,
    /// Interval entre scans en ms.
    pub scan_interval_ms: u64,
}

impl Default for GlobalConfig {
    fn default() -> Self {
        Self {
            probe_usd: 1.0,
            cycle_path: vec!["USDC".into(), "SOL".into(), "USDC".into()],
            scan_interval_ms: 200,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PoolsToml {
    #[serde(default)]
    pub global: GlobalConfig,
    #[serde(default, rename = "pool")]
    pub pools: Vec<PoolToml>,
}

/// Snapshot inmutable del registry — lo que consume el daemon.
#[derive(Debug, Clone)]
pub struct PoolSet {
    pub global: GlobalConfig,
    /// Solo pools con enabled=true; ya parseados a tipos solana_sdk.
    pub pools: Vec<RuntimePool>,
}

#[derive(Debug, Clone)]
pub struct RuntimePool {
    pub label: String,
    pub address: Pubkey,
    pub kind: PoolKind,
    pub cap_usd: f64,
    pub score: f64,
    /// R63 A4.1 fix: Pyth Oracle tier para threshold per-pool.
    /// El cyclic_dispatch usa este tier para decidir threshold de divergencia
    /// (Major=40bps, MidCap=100bps, LongTail=200bps).
    pub tier: crate::pyth_oracle::PoolTier,
}

impl PoolSet {
    /// Suma de cap_usd de todos los pools enabled (capital operativo total).
    pub fn total_cap_usd(&self) -> f64 {
        self.pools.iter().map(|p| p.cap_usd).sum()
    }

    /// Para compat con CyclicConfig actual: convierte a Vec<PoolEntry>.
    pub fn as_pool_entries(&self) -> Vec<PoolEntry> {
        self.pools
            .iter()
            .map(|p| PoolEntry {
                label: p.label.clone(),
                address: p.address,
                kind: p.kind,
            })
            .collect()
    }
}

/// Registry hot-reloadable lock-free.
pub struct PoolRegistry {
    inner: ArcSwap<PoolSet>,
    path: PathBuf,
}

impl std::fmt::Debug for PoolRegistry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let snap = self.snapshot();
        f.debug_struct("PoolRegistry")
            .field("path", &self.path)
            .field("n_pools", &snap.pools.len())
            .field("total_cap_usd", &snap.total_cap_usd())
            .finish()
    }
}

impl PoolRegistry {
    /// Carga inicial desde TOML.
    pub fn load_from_toml(path: impl AsRef<Path>) -> Result<Arc<Self>> {
        let path = path.as_ref().to_path_buf();
        let set = parse_toml_file(&path)?;
        Ok(Arc::new(Self {
            inner: ArcSwap::from_pointee(set),
            path,
        }))
    }

    /// Crea registry a partir de un PoolSet existente (testing / fallback).
    pub fn from_set(set: PoolSet, path: impl AsRef<Path>) -> Arc<Self> {
        Arc::new(Self {
            inner: ArcSwap::from_pointee(set),
            path: path.as_ref().to_path_buf(),
        })
    }

    /// Snapshot lock-free (cheap atomic load).
    pub fn snapshot(&self) -> Arc<PoolSet> {
        self.inner.load_full()
    }

    /// Re-parse desde disco. Si falla → mantiene snapshot anterior.
    pub fn reload(&self) -> Result<()> {
        let new_set = parse_toml_file(&self.path)?;
        self.inner.store(Arc::new(new_set));
        Ok(())
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

/// Parser TOML → PoolSet (con validación).
fn parse_toml_file(path: &Path) -> Result<PoolSet> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("read pools toml {path:?}"))?;
    let parsed: PoolsToml = toml::from_str(&raw)
        .with_context(|| format!("parse toml {path:?}"))?;

    // Validate global
    if parsed.global.probe_usd <= 0.0 {
        return Err(anyhow!("global.probe_usd must be > 0"));
    }
    if parsed.global.scan_interval_ms == 0 {
        return Err(anyhow!("global.scan_interval_ms must be > 0"));
    }

    // Convert + filter enabled
    let mut pools = Vec::new();
    let mut seen_labels: std::collections::HashSet<String> = Default::default();
    let mut seen_addresses: std::collections::HashSet<Pubkey> = Default::default();

    for p in parsed.pools.iter().filter(|p| p.enabled) {
        if !seen_labels.insert(p.label.clone()) {
            return Err(anyhow!("duplicate pool label: {}", p.label));
        }
        let addr = Pubkey::from_str(&p.address)
            .with_context(|| format!("parse pool address {}", p.address))?;
        if !seen_addresses.insert(addr) {
            return Err(anyhow!("duplicate pool address: {addr}"));
        }
        let kind = match p.kind.to_ascii_lowercase().as_str() {
            "orca" | "whirlpool" | "orca_clmm" => PoolKind::OrcaWhirlpool,
            "raydium" | "raydium_clmm" => PoolKind::RaydiumClmm,
            other => return Err(anyhow!("unknown pool kind: {other}")),
        };
        if p.cap_usd <= 0.0 {
            return Err(anyhow!("pool {} cap_usd must be > 0", p.label));
        }
        if !(0.0..=1.0).contains(&p.score) {
            return Err(anyhow!("pool {} score must be 0..=1", p.label));
        }
        // R63 A4.1: tier mapping
        use crate::pyth_oracle::PoolTier;
        let tier = match p.tier.to_ascii_lowercase().as_str() {
            "major" | "tier1" => PoolTier::Major,
            "midcap" | "mid" | "tier2" => PoolTier::MidCap,
            "longtail" | "long_tail" | "tier3" => PoolTier::LongTail,
            other => return Err(anyhow!("pool {} unknown tier: {}", p.label, other)),
        };
        pools.push(RuntimePool {
            label: p.label.clone(),
            address: addr,
            kind,
            cap_usd: p.cap_usd,
            score: p.score,
            tier,
        });
    }

    if pools.is_empty() {
        return Err(anyhow!("no enabled pools in {path:?}"));
    }

    Ok(PoolSet {
        global: parsed.global,
        pools,
    })
}

/// Debounce window — R62 audit A2: 150ms era insuficiente para editores
/// que hacen write-rename atomic saves (vim, neovim, network mounts).
/// 500ms coalesce eventos sin bloquear demasiado los reloads legítimos.
const RELOAD_DEBOUNCE_MS: u64 = 500;

/// Notification a enviar cuando reload OK o fail.
/// Caller (main.rs) puede subscribe via mpsc::Receiver y rutar a Telegram.
#[derive(Debug, Clone)]
pub enum ReloadNotification {
    Success {
        n_pools: usize,
        total_cap_usd: f64,
    },
    Failure {
        error: String,
        previous_snapshot_kept: bool,
    },
}

/// Background task: vigila cambios en el TOML y dispara reload.
/// Usa la crate `notify` (cross-platform inotify).
///
/// R62 audit A2:
///   - Debounce 500ms (no 150ms)
///   - Notifica via mpsc cada reload OK/Fail → caller envía a Telegram CRITICAL
pub fn spawn_watcher(
    registry: Arc<PoolRegistry>,
    notify_tx: Option<tokio::sync::mpsc::UnboundedSender<ReloadNotification>>,
) -> Result<()> {
    use notify::{recommended_watcher, EventKind, RecursiveMode, Watcher};
    use std::sync::mpsc::channel;

    let path = registry.path().to_path_buf();
    let (tx, rx) = channel();

    // Spawn dedicated OS thread for watcher (notify uses sync APIs)
    std::thread::spawn(move || {
        let mut watcher = match recommended_watcher(move |res| {
            if let Ok(ev) = res {
                let _ = tx.send(ev);
            }
        }) {
            Ok(w) => w,
            Err(e) => {
                tracing::error!(error=?e, "pool_registry watcher init failed");
                return;
            }
        };

        if let Err(e) = watcher.watch(&path, RecursiveMode::NonRecursive) {
            tracing::error!(error=?e, "pool_registry watcher.watch failed");
            return;
        }

        // Block reading events
        for event in rx.iter() {
            match event.kind {
                EventKind::Modify(_) | EventKind::Create(_) | EventKind::Remove(_) => {
                    // R62 A2: Debounce 500ms (write-rename coalesce)
                    std::thread::sleep(std::time::Duration::from_millis(RELOAD_DEBOUNCE_MS));
                    match registry.reload() {
                        Ok(()) => {
                            let snap = registry.snapshot();
                            tracing::info!(
                                pools = snap.pools.len(),
                                total_cap_usd = snap.total_cap_usd(),
                                "pool_registry HOT-RELOADED"
                            );
                            if let Some(tx) = &notify_tx {
                                let _ = tx.send(ReloadNotification::Success {
                                    n_pools: snap.pools.len(),
                                    total_cap_usd: snap.total_cap_usd(),
                                });
                            }
                        }
                        Err(e) => {
                            tracing::error!(
                                error=?e,
                                "🚨 pool_registry reload FAILED — keeping previous snapshot"
                            );
                            if let Some(tx) = &notify_tx {
                                let _ = tx.send(ReloadNotification::Failure {
                                    error: format!("{:#}", e),
                                    previous_snapshot_kept: true,
                                });
                            }
                        }
                    }
                }
                _ => {}
            }
        }
    });

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn write_toml(content: &str) -> NamedTempFile {
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{}", content).unwrap();
        f
    }

    const VALID_TOML: &str = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC", "SOL", "USDC"]
scan_interval_ms = 200

[[pool]]
label = "orca_sol_usdc"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 2000.0
score = 0.85
enabled = true
"#;

    #[test]
    fn loads_valid_toml() {
        let f = write_toml(VALID_TOML);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let snap = reg.snapshot();
        assert_eq!(snap.pools.len(), 1);
        assert_eq!(snap.pools[0].label, "orca_sol_usdc");
        assert_eq!(snap.pools[0].cap_usd, 2000.0);
        assert_eq!(snap.global.probe_usd, 1.0);
        assert_eq!(snap.total_cap_usd(), 2000.0);
        // R63 A4.1: default tier es LongTail
        assert_eq!(snap.pools[0].tier, crate::pyth_oracle::PoolTier::LongTail);
    }

    #[test]
    fn parses_explicit_tier_R63_A41() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC", "SOL", "USDC"]
scan_interval_ms = 200

[[pool]]
label = "p_major"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 2000.0
score = 0.85
tier = "major"

[[pool]]
label = "p_mid"
address = "AGZAVAhSJupFK6PCTGsbEXQEU9q3R3wH9bN5SmQYrqQS"
kind = "orca"
cap_usd = 1500.0
score = 0.6
tier = "midcap"

[[pool]]
label = "p_lt"
address = "Cuh4VH5kQTzz3TxKD78XC5xGY56wbxYeFbzm38ngu5Wc"
kind = "orca"
cap_usd = 500.0
score = 0.4
tier = "longtail"
"#;
        let f = write_toml(toml);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let snap = reg.snapshot();
        use crate::pyth_oracle::PoolTier;
        assert_eq!(snap.pools[0].tier, PoolTier::Major);
        assert_eq!(snap.pools[1].tier, PoolTier::MidCap);
        assert_eq!(snap.pools[2].tier, PoolTier::LongTail);
    }

    #[test]
    fn rejects_unknown_tier_R63_A41() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "bad_tier"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1000.0
tier = "supergiant"
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("unknown tier"));
    }

    #[test]
    fn filters_disabled_pools() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC", "SOL", "USDC"]
scan_interval_ms = 200

[[pool]]
label = "active"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 2000.0
score = 0.85
enabled = true

[[pool]]
label = "disabled"
address = "AGZAVAhSJupFK6PCTGsbEXQEU9q3R3wH9bN5SmQYrqQS"
kind = "orca"
cap_usd = 1000.0
score = 0.5
enabled = false
"#;
        let f = write_toml(toml);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let snap = reg.snapshot();
        assert_eq!(snap.pools.len(), 1);
        assert_eq!(snap.pools[0].label, "active");
    }

    #[test]
    fn rejects_duplicate_label() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "dup"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1000.0

[[pool]]
label = "dup"
address = "AGZAVAhSJupFK6PCTGsbEXQEU9q3R3wH9bN5SmQYrqQS"
kind = "orca"
cap_usd = 1000.0
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("duplicate pool label"));
    }

    #[test]
    fn rejects_duplicate_address() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "p1"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1000.0

[[pool]]
label = "p2"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "raydium"
cap_usd = 1000.0
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("duplicate pool address"));
    }

    #[test]
    fn rejects_invalid_score_range() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "bad"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1000.0
score = 1.5
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("score must be 0..=1"));
    }

    #[test]
    fn rejects_zero_cap() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "zero"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 0.0
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("cap_usd must be > 0"));
    }

    #[test]
    fn rejects_no_enabled_pools() {
        let toml = r#"
[global]
probe_usd = 1.0
cycle_path = ["USDC"]
scan_interval_ms = 200

[[pool]]
label = "all_disabled"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1000.0
enabled = false
"#;
        let f = write_toml(toml);
        let err = PoolRegistry::load_from_toml(f.path()).unwrap_err();
        assert!(err.to_string().contains("no enabled pools"));
    }

    #[test]
    fn snapshot_is_lockfree_clone() {
        let f = write_toml(VALID_TOML);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let s1 = reg.snapshot();
        let s2 = reg.snapshot();
        // Both snapshots point to same Arc inner — Arc::ptr_eq holds
        assert!(Arc::ptr_eq(&s1, &s2));
    }

    #[test]
    fn reload_swaps_snapshot() {
        let f = write_toml(VALID_TOML);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let s1 = reg.snapshot();
        assert_eq!(s1.pools.len(), 1);

        // Rewrite file with 2 pools enabled
        let new_toml = r#"
[global]
probe_usd = 2.0
cycle_path = ["USDC", "SOL", "USDC"]
scan_interval_ms = 100

[[pool]]
label = "p1"
address = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
kind = "orca"
cap_usd = 1500.0
score = 0.7

[[pool]]
label = "p2"
address = "AGZAVAhSJupFK6PCTGsbEXQEU9q3R3wH9bN5SmQYrqQS"
kind = "raydium"
cap_usd = 1500.0
score = 0.6
"#;
        std::fs::write(f.path(), new_toml).unwrap();
        reg.reload().unwrap();
        let s2 = reg.snapshot();
        assert_eq!(s2.pools.len(), 2);
        assert_eq!(s2.global.probe_usd, 2.0);
        assert_eq!(s2.global.scan_interval_ms, 100);
        assert_eq!(s2.total_cap_usd(), 3000.0);
        // Old snapshot still valid (Arc shared)
        assert_eq!(s1.pools.len(), 1);
    }

    #[test]
    fn reload_notification_success_R62_A2() {
        let success = ReloadNotification::Success {
            n_pools: 3,
            total_cap_usd: 5000.0,
        };
        // Pattern match works
        match success {
            ReloadNotification::Success { n_pools, total_cap_usd } => {
                assert_eq!(n_pools, 3);
                assert_eq!(total_cap_usd, 5000.0);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn reload_notification_failure_R62_A2() {
        let fail = ReloadNotification::Failure {
            error: "syntax error line 4".to_string(),
            previous_snapshot_kept: true,
        };
        match fail {
            ReloadNotification::Failure { error, previous_snapshot_kept } => {
                assert!(error.contains("syntax"));
                assert!(previous_snapshot_kept);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn debounce_constant_is_500ms_R62_A2() {
        // Verifica que el debounce subió de 150ms (R59) a 500ms (R62 A2)
        assert_eq!(RELOAD_DEBOUNCE_MS, 500);
    }

    #[test]
    fn reload_failure_keeps_previous() {
        let f = write_toml(VALID_TOML);
        let reg = PoolRegistry::load_from_toml(f.path()).unwrap();
        let s1 = reg.snapshot();

        // Corrupt the file
        std::fs::write(f.path(), "this is not valid toml ===").unwrap();
        let res = reg.reload();
        assert!(res.is_err());

        // Snapshot still works — last good state
        let s2 = reg.snapshot();
        assert_eq!(s2.pools.len(), 1);
        assert_eq!(s2.pools[0].label, s1.pools[0].label);
    }
}
