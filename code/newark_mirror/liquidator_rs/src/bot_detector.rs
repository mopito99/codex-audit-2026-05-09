#![allow(dead_code)] // Algunas APIs son para Phase 2 LIVE; lista JITO_TIP_ACCOUNTS sí se usa desde sandwich_listener
// BotDetector (G58/G68): pipeline de filtros pre-bundle para descartar bots.
//
// Pipeline ordenado por coste (cheapest first):
//   1. Jito tip account en account_keys → descarta ~60% (G58)
//   2. ComputeUnitPrice >100K microlamports → descarta ~20% (G68)
//   3. Wallet en blacklist dinámica → descarta ~10% (G75)
//   4. Slippage "limpio" 0.1%/0.5%/1.0% exactos → descarta ~5% (G68)
//   → Resto (~5%): víctima real candidate
//
// La blacklist se construye dinámicamente observando TODAS las TXs (G75):
// si un signer aparece >5× en 24h con CUP medio >100K → bot confirmado.

use dashmap::{DashMap, DashSet};
use solana_sdk::pubkey::Pubkey;
use std::str::FromStr;
use std::sync::Arc;
use std::time::{Duration, Instant};

/// 8 cuentas oficiales de Jito tip (G58). Si ANY aparece en account_keys de la TX,
/// es un bot/searcher con tip propio — sandwichearlo = pérdida garantizada.
pub const JITO_TIP_ACCOUNTS: &[&str] = &[
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pivKeVQ7eh4P9hbVKyT3",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
];

const CUP_BOT_THRESHOLD: u64 = 100_000; // microlamports — G68
const BLACKLIST_TX_COUNT_THRESHOLD: u32 = 5; // TXs/24h para clasificar como bot
const BLACKLIST_AVG_CUP_THRESHOLD: u64 = 100_000;
const STATS_TTL_SECS: u64 = 86_400; // 24h

#[derive(Debug, Clone)]
pub struct SignerStats {
    pub tx_count: u32,
    pub total_cup: u64,
    pub last_seen: Instant,
}

impl SignerStats {
    fn avg_cup(&self) -> u64 {
        if self.tx_count == 0 { 0 } else { self.total_cup / self.tx_count as u64 }
    }

    fn is_bot(&self) -> bool {
        self.tx_count >= BLACKLIST_TX_COUNT_THRESHOLD
            && self.avg_cup() >= BLACKLIST_AVG_CUP_THRESHOLD
    }
}

#[derive(Clone)]
pub struct BotDetector {
    /// Set pre-cargado con cuentas Jito tip — lookup O(1) por hash
    jito_tips: Arc<DashSet<Pubkey>>,
    /// Stats observadas por signer (G75: registrar TODAS, no solo rechazadas)
    observed: Arc<DashMap<Pubkey, SignerStats>>,
    /// Blacklist confirmada: signer → bot tras umbral
    blacklist: Arc<DashSet<Pubkey>>,
}

impl BotDetector {
    pub fn new() -> Self {
        let jito_tips = DashSet::new();
        for s in JITO_TIP_ACCOUNTS {
            if let Ok(pk) = Pubkey::from_str(s) {
                jito_tips.insert(pk);
            }
        }
        Self {
            jito_tips: Arc::new(jito_tips),
            observed: Arc::new(DashMap::new()),
            blacklist: Arc::new(DashSet::new()),
        }
    }

    /// Filtro #1 (G58): account_keys contiene cuenta Jito tip → bot.
    /// Coste: O(N) donde N = account_keys.len(). N típico = 11-25 → <500ns.
    pub fn has_jito_tip(&self, account_keys: &[Pubkey]) -> bool {
        account_keys.iter().any(|k| self.jito_tips.contains(k))
    }

    /// Filtro #2 (G68): compute_unit_price > 100K microlamports → bot.
    pub fn has_high_cup(&self, cup: u64) -> bool {
        cup > CUP_BOT_THRESHOLD
    }

    /// Filtro #3 (G75): signer en blacklist dinámica.
    pub fn is_blacklisted(&self, signer: &Pubkey) -> bool {
        self.blacklist.contains(signer)
    }

    /// Filtro #4 (G68): slippage tolerance "limpio" exacto (0.1%, 0.5%, 1.0%) = bot.
    /// Humanos usan UI default o valores "sucios" (ej: 0.83%).
    pub fn has_clean_slippage(&self, slippage_bps: u16) -> bool {
        matches!(slippage_bps, 10 | 50 | 100 | 200 | 500 | 1000)
    }

    /// Pipeline completo — true si TX debería descartarse como bot.
    /// Devuelve `Option<&'static str>` con razón si rechaza, None si pasa.
    pub fn classify(
        &self,
        account_keys: &[Pubkey],
        signer: &Pubkey,
        cup: u64,
        slippage_bps: Option<u16>,
    ) -> Option<&'static str> {
        if self.has_jito_tip(account_keys) {
            return Some("jito_tip_in_keys");
        }
        if self.has_high_cup(cup) {
            return Some("high_cup");
        }
        if self.is_blacklisted(signer) {
            return Some("blacklisted_signer");
        }
        if let Some(bps) = slippage_bps {
            if self.has_clean_slippage(bps) {
                return Some("clean_slippage_bps");
            }
        }
        None
    }

    /// Registrar observación (G75: registrar TODAS, no solo rechazadas).
    /// Si stats superan umbral → añadir signer a blacklist.
    pub fn observe(&self, signer: Pubkey, cup: u64) {
        let now = Instant::now();
        let mut entry = self
            .observed
            .entry(signer)
            .or_insert_with(|| SignerStats {
                tx_count: 0,
                total_cup: 0,
                last_seen: now,
            });
        entry.tx_count += 1;
        entry.total_cup = entry.total_cup.saturating_add(cup);
        entry.last_seen = now;

        if entry.is_bot() {
            self.blacklist.insert(signer);
        }
    }

    /// Limpieza de stats viejas (>24h). Llamar desde background task cada 1h.
    pub fn prune_old_stats(&self) {
        let ttl = Duration::from_secs(STATS_TTL_SECS);
        self.observed.retain(|_, s| s.last_seen.elapsed() < ttl);
    }

    pub fn blacklist_size(&self) -> usize {
        self.blacklist.len()
    }

    pub fn observed_size(&self) -> usize {
        self.observed.len()
    }
}

impl Default for BotDetector {
    fn default() -> Self {
        Self::new()
    }
}

/// Background task: prune cada 1h.
pub fn spawn_periodic_prune(detector: BotDetector) {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(3600));
        interval.tick().await; // descartar primera (inmediata)
        loop {
            interval.tick().await;
            let before = detector.observed_size();
            detector.prune_old_stats();
            let after = detector.observed_size();
            println!(
                "[bot_detector] prune: {before}→{after} signers, blacklist={}",
                detector.blacklist_size()
            );
        }
    });
}
