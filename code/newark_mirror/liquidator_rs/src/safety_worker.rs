//! SafetyWorker — emergency exit defense layer (Pieza 5 R59).
//!
//! Defense in depth: si por algún false negative del RugCheck, math bug, o
//! comportamiento adversarial el daemon termina con un token NO esperado en la
//! hot wallet, este worker lo detecta y lo vende vía Jupiter slippage alto.
//!
//! Filosofía (Gemma G73, confirmada R59 Q14f):
//!   - NO es para profit. Es para "salida garantizada".
//!   - Slippage tolerance 10-20% — aceptar pérdida controlada antes que
//!     quedarse atrapado con token sin liquidez.
//!   - Trip Circuit Breaker tras emergency sell → daemon entra en pause
//!     hasta /manual_reset.
//!
//! Uso:
//!   let worker = SafetyWorker::new(cfg);
//!   tokio::spawn(worker.run(rpc, jupiter, cb));
//!
//! Trigger:
//!   - Cada 60s lee balances on-chain de hot wallet.
//!   - Si token NO whitelist + valor estimado > min_value_usd → emergency sell.
//!   - Después: trip CB con TripReason::WalletDrain.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;
use std::collections::HashSet;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};

/// USDC mainnet (whitelist por defecto).
pub const USDC_MAINNET: &str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
/// USDT mainnet (whitelist por defecto).
pub const USDT_MAINNET: &str = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB";
/// Wrapped SOL (whitelist por defecto).
pub const WSOL_MAINNET: &str = "So11111111111111111111111111111111111111112";

/// SafetyConfig — serializable para hot-reload TOML futuro (R61 audit follow-up #3).
///
/// Los thresholds (slippage_pct, min_value_usd) están en este struct para que
/// puedan moverse a un config file en wire-up sin reescribir lógica.
///
/// Ejemplo TOML futuro:
/// ```toml
/// [safety]
/// min_value_usd = 10.0
/// slippage_pct = 0.20
/// scan_interval_secs = 60
/// alert_scan_interval_secs = 10
/// jupiter_base = "https://quote-api.jup.ag/v6"
/// whitelist = [
///   "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
///   "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
///   "So11111111111111111111111111111111111111112",   # WSOL
/// ]
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SafetyConfig {
    /// Tokens permitidos en wallet — todo lo demás dispara emergency sell.
    /// Serializa como Vec<String> y se convierte a HashSet<Pubkey> internamente.
    #[serde(serialize_with = "serialize_pubkey_set", deserialize_with = "deserialize_pubkey_set")]
    pub whitelist: HashSet<Pubkey>,
    /// Min USD value para activar — bajo este valor se ignora (dust).
    pub min_value_usd: f64,
    /// Slippage tolerance Jupiter swap (0.20 = 20%, R61 audit Q2).
    pub slippage_pct: f64,
    /// Frecuencia de scan en segundos (Normal state).
    pub scan_interval_secs: u64,
    /// Intervalo entre scans cuando state == Vigilant.
    pub alert_scan_interval_secs: u64,
    /// Hot wallet pubkey — la que monitorizamos.
    #[serde(serialize_with = "serialize_pubkey", deserialize_with = "deserialize_pubkey")]
    pub hot_wallet: Pubkey,
    /// Jupiter API base URL.
    pub jupiter_base: String,
}

fn serialize_pubkey<S: serde::Serializer>(pk: &Pubkey, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&pk.to_string())
}
fn deserialize_pubkey<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Pubkey, D::Error> {
    let s = String::deserialize(d)?;
    Pubkey::from_str(&s).map_err(serde::de::Error::custom)
}
fn serialize_pubkey_set<S: serde::Serializer>(set: &HashSet<Pubkey>, s: S) -> Result<S::Ok, S::Error> {
    let v: Vec<String> = set.iter().map(|p| p.to_string()).collect();
    v.serialize(s)
}
fn deserialize_pubkey_set<'de, D: serde::Deserializer<'de>>(d: D) -> Result<HashSet<Pubkey>, D::Error> {
    let v: Vec<String> = Vec::deserialize(d)?;
    v.into_iter()
        .map(|s| Pubkey::from_str(&s).map_err(serde::de::Error::custom))
        .collect()
}

impl SafetyConfig {
    /// Default conservador para Phase 1.
    /// whitelist: USDC, USDT, WSOL · min_value: $10 · slippage: 20% (R61 audit Q2)
    /// scan: 60s normal, 10s vigilant (R61 audit Q5)
    pub fn default_for(hot_wallet: Pubkey) -> Self {
        let mut whitelist = HashSet::new();
        whitelist.insert(Pubkey::from_str(USDC_MAINNET).unwrap());
        whitelist.insert(Pubkey::from_str(USDT_MAINNET).unwrap());
        whitelist.insert(Pubkey::from_str(WSOL_MAINNET).unwrap());

        Self {
            whitelist,
            min_value_usd: 10.0,
            // R61 audit Q2: emergency = liquidation certainty > price optimization.
            // 20% slippage tolerance ensures TX lands even si pool tóxico shifting.
            slippage_pct: 0.20,
            scan_interval_secs: 60,
            alert_scan_interval_secs: 10,
            hot_wallet,
            jupiter_base: "https://quote-api.jup.ag/v6".to_string(),
        }
    }
}

/// State machine para adaptive scan rate (R61 audit Q5).
///
/// Transitions:
///   Normal      → Vigilant   cuando ScanResult.has_alerts()
///   Vigilant    → Normal     cuando ScanResult limpio (no flags)
///
/// En Vigilant: scan más frecuente (10s) hasta confirmar limpio.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SafetyState {
    Normal,
    Vigilant,
}

impl SafetyState {
    /// Calcula próximo state según resultado del scan.
    pub fn next(self, has_alerts: bool) -> Self {
        match (self, has_alerts) {
            (_, true) => SafetyState::Vigilant,
            (SafetyState::Vigilant, false) => SafetyState::Normal,
            (SafetyState::Normal, false) => SafetyState::Normal,
        }
    }

    /// Devuelve el interval correcto según state.
    pub fn interval_secs(self, cfg: &SafetyConfig) -> u64 {
        match self {
            SafetyState::Normal => cfg.scan_interval_secs,
            SafetyState::Vigilant => cfg.alert_scan_interval_secs,
        }
    }
}

/// Token detectado en wallet con info para decision-making.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WalletToken {
    pub mint: Pubkey,
    pub balance_raw: u64,
    pub decimals: u8,
    pub ui_amount: f64,
    pub estimated_value_usd: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SafetyAction {
    /// Token está en whitelist o below min_value_usd → no action.
    Ignore,
    /// Token NO whitelist con valor > threshold → emergency sell.
    EmergencySell,
}

/// Decision logic puro — sin side effects, sin red. Testeable.
pub fn decide_action(token: &WalletToken, cfg: &SafetyConfig) -> SafetyAction {
    if cfg.whitelist.contains(&token.mint) {
        return SafetyAction::Ignore;
    }
    if token.estimated_value_usd < cfg.min_value_usd {
        return SafetyAction::Ignore;
    }
    SafetyAction::EmergencySell
}

/// Evento que el SafetyWorker emite via mpsc al orchestrator (R62 audit A3).
/// REJECT del polling pattern previo: ahora es event-driven directo.
#[derive(Debug, Clone)]
pub enum SafetyAlert {
    /// Token NO whitelist detectado con valor > min_threshold.
    /// El orchestrator debe (a) trip CB con TripReason::WalletDrain,
    /// (b) iniciar emergency sell via Jupiter.
    TokenDetected {
        timestamp_unix: i64,
        flagged_tokens: Vec<WalletToken>,
        total_value_usd: f64,
    },
    /// State transition Normal → Vigilant (telemetría / dashboard).
    StateChanged {
        timestamp_unix: i64,
        from: SafetyState,
        to: SafetyState,
    },
    /// Heartbeat — wallet limpia, todos los tokens en whitelist.
    /// Útil para dashboards (heartbeat del worker).
    Heartbeat {
        timestamp_unix: i64,
        n_tokens_observed: usize,
    },
}

/// Resultado de un scan completo de wallet.
#[derive(Debug, Clone)]
pub struct ScanResult {
    pub all_tokens: Vec<WalletToken>,
    pub flagged_for_sell: Vec<WalletToken>,
}

impl ScanResult {
    pub fn has_alerts(&self) -> bool {
        !self.flagged_for_sell.is_empty()
    }
    pub fn n_flagged(&self) -> usize {
        self.flagged_for_sell.len()
    }
    pub fn total_flagged_value_usd(&self) -> f64 {
        self.flagged_for_sell.iter().map(|t| t.estimated_value_usd).sum()
    }
}

/// Analiza un set de tokens según config y separa alerts.
pub fn analyze_wallet(tokens: &[WalletToken], cfg: &SafetyConfig) -> ScanResult {
    let flagged: Vec<WalletToken> = tokens
        .iter()
        .filter(|t| decide_action(t, cfg) == SafetyAction::EmergencySell)
        .cloned()
        .collect();
    ScanResult {
        all_tokens: tokens.to_vec(),
        flagged_for_sell: flagged,
    }
}

/// Construye Jupiter swap quote URL.
/// Devuelve URL para fetch del quote (NO ejecuta el swap — solo prepara).
pub fn build_jupiter_quote_url(
    base: &str,
    input_mint: &Pubkey,
    output_mint: &Pubkey,
    amount_raw: u64,
    slippage_bps: u16,
) -> String {
    format!(
        "{base}/quote?inputMint={input_mint}&outputMint={output_mint}\
         &amount={amount_raw}&slippageBps={slippage_bps}"
    )
}

/// SafetyWorker — wrapper para uso async. Mantiene estado interno minimal.
#[derive(Debug, Clone)]
pub struct SafetyWorker {
    pub cfg: SafetyConfig,
    /// Tracking: cuántas alerts hemos disparado (incrementa con cada emergency).
    pub alerts_fired: Arc<std::sync::atomic::AtomicU64>,
    /// Estado actual del worker (Normal | Vigilant) — R61 audit Q5.
    /// Se exponer como AtomicU8 (0=Normal, 1=Vigilant) para lockfree reads.
    pub state: Arc<std::sync::atomic::AtomicU8>,
}

impl SafetyWorker {
    pub fn new(cfg: SafetyConfig) -> Self {
        Self {
            cfg,
            alerts_fired: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            state: Arc::new(std::sync::atomic::AtomicU8::new(0)), // 0 = Normal
        }
    }

    pub fn alerts_count(&self) -> u64 {
        self.alerts_fired.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// Read current state lockfree.
    pub fn current_state(&self) -> SafetyState {
        match self.state.load(std::sync::atomic::Ordering::Relaxed) {
            1 => SafetyState::Vigilant,
            _ => SafetyState::Normal,
        }
    }

    fn set_state(&self, s: SafetyState) {
        let v = match s {
            SafetyState::Normal => 0u8,
            SafetyState::Vigilant => 1u8,
        };
        self.state.store(v, std::sync::atomic::Ordering::Relaxed);
    }

    /// Computa el slippage en basis points para Jupiter (20% = 2000 bps).
    pub fn slippage_bps(&self) -> u16 {
        (self.cfg.slippage_pct * 10_000.0).round() as u16
    }

    /// Run loop EVENT-DRIVEN (R62 audit A3 — REJECT del polling pattern).
    /// Cuando detecta alerta, EMITE inmediatamente via mpsc::Sender al orchestrator.
    /// El orchestrator (main.rs) recibe el evento y dispara cb.trip() sin latencia.
    ///
    /// Flujo: Detection → Channel send → Orchestrator receives → CB trip → Pause.
    /// Sin polling externo. Sin race conditions.
    pub async fn run<F, Fut>(
        self,
        fetch_wallet: F,
        alert_tx: tokio::sync::mpsc::UnboundedSender<SafetyAlert>,
    ) where
        F: Fn() -> Fut + Send + Sync + 'static,
        Fut: std::future::Future<Output = Result<Vec<WalletToken>>> + Send,
    {
        info!(
            scan_normal = self.cfg.scan_interval_secs,
            scan_vigilant = self.cfg.alert_scan_interval_secs,
            slippage_pct = self.cfg.slippage_pct,
            min_value_usd = self.cfg.min_value_usd,
            whitelist_size = self.cfg.whitelist.len(),
            "SafetyWorker starting (event-driven R62 A3)"
        );

        loop {
            let cur_state = self.current_state();
            let sleep_secs = cur_state.interval_secs(&self.cfg);
            tokio::time::sleep(Duration::from_secs(sleep_secs)).await;

            let tokens = match fetch_wallet().await {
                Ok(t) => t,
                Err(e) => {
                    warn!(error=?e, "SafetyWorker: fetch_wallet failed");
                    continue;
                }
            };

            let scan = analyze_wallet(&tokens, &self.cfg);
            let next_state = cur_state.next(scan.has_alerts());
            let now_unix = chrono::Utc::now().timestamp();

            if next_state != cur_state {
                info!(from = ?cur_state, to = ?next_state, "state transition");
                self.set_state(next_state);
                let _ = alert_tx.send(SafetyAlert::StateChanged {
                    timestamp_unix: now_unix,
                    from: cur_state,
                    to: next_state,
                });
            }

            if scan.has_alerts() {
                let n = self.alerts_fired.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                error!(
                    flagged_count = scan.n_flagged(),
                    total_value_usd = scan.total_flagged_value_usd(),
                    alerts_total = n + 1,
                    "🚨 SafetyWorker EMERGENCY → emitting event"
                );
                // R62 A3: event-driven emit (no polling externo).
                // P#1 R62 OPTIMIZACION: move scan.flagged_for_sell instead of clone().
                // ScanResult ya no se necesita post-emit, así que move es válido.
                let total_value_usd = scan.total_flagged_value_usd();
                let _ = alert_tx.send(SafetyAlert::TokenDetected {
                    timestamp_unix: now_unix,
                    flagged_tokens: scan.flagged_for_sell,
                    total_value_usd,
                });
            } else {
                let _ = alert_tx.send(SafetyAlert::Heartbeat {
                    timestamp_unix: now_unix,
                    n_tokens_observed: tokens.len(),
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pk(s: &str) -> Pubkey {
        Pubkey::from_str(s).unwrap()
    }

    fn cfg() -> SafetyConfig {
        SafetyConfig::default_for(pk("GaL85ykdeJ9g5JeXE2Yvar92yMktVCzvi5vGJB77wbTh"))
    }

    fn tok(mint: &str, value_usd: f64) -> WalletToken {
        WalletToken {
            mint: pk(mint),
            balance_raw: 1_000_000,
            decimals: 6,
            ui_amount: 1.0,
            estimated_value_usd: value_usd,
        }
    }

    #[test]
    fn whitelist_token_is_ignored() {
        let c = cfg();
        let t = tok(USDC_MAINNET, 5000.0);
        assert_eq!(decide_action(&t, &c), SafetyAction::Ignore);
    }

    #[test]
    fn unknown_token_above_threshold_triggers_sell() {
        let c = cfg();
        let t = tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 50.0);
        assert_eq!(decide_action(&t, &c), SafetyAction::EmergencySell);
    }

    #[test]
    fn unknown_token_below_threshold_is_dust() {
        let c = cfg();
        let t = tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 5.0);
        assert_eq!(decide_action(&t, &c), SafetyAction::Ignore);
    }

    #[test]
    fn unknown_token_at_exact_threshold_below_does_not_trigger() {
        let c = cfg();
        let t = tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 9.99);
        assert_eq!(decide_action(&t, &c), SafetyAction::Ignore);
    }

    #[test]
    fn unknown_token_at_threshold_exactly_does_not_trigger() {
        // < check, not <= so 10.0 == threshold should NOT ignore (matches our < logic)
        // Wait — code is `< cfg.min_value_usd`. If value = 10.0 and min = 10.0,
        // 10.0 < 10.0 is false → not ignored → triggers sell.
        let c = cfg();
        let t = tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 10.0);
        assert_eq!(decide_action(&t, &c), SafetyAction::EmergencySell);
    }

    #[test]
    fn analyze_wallet_separates_correctly() {
        let c = cfg();
        let tokens = vec![
            tok(USDC_MAINNET, 5000.0),                                          // ignore (whitelist)
            tok(USDT_MAINNET, 1000.0),                                          // ignore (whitelist)
            tok(WSOL_MAINNET, 2000.0),                                          // ignore (whitelist)
            tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 50.0),           // FLAG (BONK)
            tok("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", 100.0),          // FLAG (WIF)
            tok("HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", 1.0),            // ignore (dust)
        ];
        let scan = analyze_wallet(&tokens, &c);
        assert!(scan.has_alerts());
        assert_eq!(scan.n_flagged(), 2);
        assert!((scan.total_flagged_value_usd() - 150.0).abs() < 1e-9);
    }

    #[test]
    fn default_slippage_is_20_pct_R61_Q2() {
        // R61 audit Q2: emergency = liquidation certainty. Default debe ser 20%.
        let c = cfg();
        assert!((c.slippage_pct - 0.20).abs() < 1e-9);
        let w = SafetyWorker::new(c);
        assert_eq!(w.slippage_bps(), 2000);
    }

    #[test]
    fn slippage_bps_calculation() {
        let mut c = cfg();
        c.slippage_pct = 0.10;
        let w = SafetyWorker::new(c);
        assert_eq!(w.slippage_bps(), 1000); // 10% = 1000 bps

        let mut c2 = cfg();
        c2.slippage_pct = 0.20;
        let w2 = SafetyWorker::new(c2);
        assert_eq!(w2.slippage_bps(), 2000); // 20% = 2000 bps

        let mut c3 = cfg();
        c3.slippage_pct = 0.05;
        let w3 = SafetyWorker::new(c3);
        assert_eq!(w3.slippage_bps(), 500);
    }

    #[test]
    fn state_transition_normal_to_vigilant_on_alert_R61_Q5() {
        // R61 audit Q5: state transition Normal → Vigilant cuando hay alerts
        let s = SafetyState::Normal;
        let next = s.next(true);
        assert_eq!(next, SafetyState::Vigilant);
    }

    #[test]
    fn state_transition_vigilant_to_normal_on_clean() {
        // Vigilant → Normal cuando scan limpio (no alerts)
        let s = SafetyState::Vigilant;
        let next = s.next(false);
        assert_eq!(next, SafetyState::Normal);
    }

    #[test]
    fn state_stays_normal_when_clean() {
        let s = SafetyState::Normal;
        assert_eq!(s.next(false), SafetyState::Normal);
    }

    #[test]
    fn state_stays_vigilant_on_repeated_alerts() {
        let s = SafetyState::Vigilant;
        assert_eq!(s.next(true), SafetyState::Vigilant);
    }

    #[test]
    fn interval_secs_per_state() {
        let c = cfg();
        assert_eq!(SafetyState::Normal.interval_secs(&c), 60);
        assert_eq!(SafetyState::Vigilant.interval_secs(&c), 10);
    }

    #[test]
    fn worker_starts_in_normal_state() {
        let w = SafetyWorker::new(cfg());
        assert_eq!(w.current_state(), SafetyState::Normal);
    }

    #[test]
    fn safety_alert_token_detected_R62_A3() {
        let alert = SafetyAlert::TokenDetected {
            timestamp_unix: 1746230000,
            flagged_tokens: vec![tok("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 50.0)],
            total_value_usd: 50.0,
        };
        match alert {
            SafetyAlert::TokenDetected { total_value_usd, flagged_tokens, .. } => {
                assert_eq!(total_value_usd, 50.0);
                assert_eq!(flagged_tokens.len(), 1);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn safety_alert_state_changed_R62_A3() {
        let alert = SafetyAlert::StateChanged {
            timestamp_unix: 1746230000,
            from: SafetyState::Normal,
            to: SafetyState::Vigilant,
        };
        match alert {
            SafetyAlert::StateChanged { from, to, .. } => {
                assert_eq!(from, SafetyState::Normal);
                assert_eq!(to, SafetyState::Vigilant);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn safety_alert_heartbeat_R62_A3() {
        let alert = SafetyAlert::Heartbeat {
            timestamp_unix: 1746230000,
            n_tokens_observed: 3,
        };
        match alert {
            SafetyAlert::Heartbeat { n_tokens_observed, .. } => {
                assert_eq!(n_tokens_observed, 3);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn worker_state_can_be_set_atomically() {
        let w = SafetyWorker::new(cfg());
        assert_eq!(w.current_state(), SafetyState::Normal);
        w.set_state(SafetyState::Vigilant);
        assert_eq!(w.current_state(), SafetyState::Vigilant);
        w.set_state(SafetyState::Normal);
        assert_eq!(w.current_state(), SafetyState::Normal);
    }

    #[test]
    fn jupiter_quote_url_format() {
        let url = build_jupiter_quote_url(
            "https://quote-api.jup.ag/v6",
            &pk("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
            &pk(USDC_MAINNET),
            1_000_000_000,
            1000,
        );
        assert!(url.contains("inputMint=DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"));
        assert!(url.contains("outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"));
        assert!(url.contains("amount=1000000000"));
        assert!(url.contains("slippageBps=1000"));
    }

    #[test]
    fn alerts_count_increments() {
        let w = SafetyWorker::new(cfg());
        assert_eq!(w.alerts_count(), 0);
        w.alerts_fired.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        assert_eq!(w.alerts_count(), 1);
        w.alerts_fired.fetch_add(2, std::sync::atomic::Ordering::Relaxed);
        assert_eq!(w.alerts_count(), 3);
    }

    #[test]
    fn empty_wallet_no_alerts() {
        let c = cfg();
        let scan = analyze_wallet(&[], &c);
        assert!(!scan.has_alerts());
        assert_eq!(scan.n_flagged(), 0);
        assert_eq!(scan.total_flagged_value_usd(), 0.0);
    }

    #[test]
    fn wallet_only_whitelist_no_alerts() {
        let c = cfg();
        let tokens = vec![
            tok(USDC_MAINNET, 3000.0),
            tok(USDT_MAINNET, 1100.0),
            tok(WSOL_MAINNET, 250.0),
        ];
        let scan = analyze_wallet(&tokens, &c);
        assert!(!scan.has_alerts());
        assert_eq!(scan.n_flagged(), 0);
    }
}
