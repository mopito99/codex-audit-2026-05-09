// ChaosDetector — detecta régimen de mercado con ventana deslizante de 60s.
//
// Estados: Quiet → Normal → Chaos
// Transición a Chaos es inmediata si los thresholds se superan.
// Bajada desde Chaos tiene histéresis de 5 min para evitar flapping.
//
// El caller aplica el hard cap de balance:
//   effective_probe = mkt_cfg.probe_amount_usdc.min(usdc_balance * 0.90)

use std::collections::VecDeque;
use std::sync::RwLock;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarketState {
    Quiet,
    Normal,
    Chaos,
}

#[derive(Debug, Clone)]
pub struct MarketConfig {
    pub state: MarketState,
    /// Probe size sugerida. Aplicar hard cap: min(probe, usdc_balance * 0.90)
    pub probe_amount_usdc: f64,
    pub min_profit_usdc: f64,
    pub min_profit_bps: f64,
    /// Tip máximo: clampear siempre, ignorar multiplicadores externos en Chaos
    pub max_tip_lamports: u64,
}

struct Inner {
    state: MarketState,
    window: VecDeque<(Instant, f64)>, // (ts, gap_pct)
    chaos_since: Option<Instant>,
}

pub struct ChaosDetector {
    inner: RwLock<Inner>,
}

impl ChaosDetector {
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(Inner {
                state: MarketState::Normal,
                window: VecDeque::with_capacity(512),
                chaos_since: None,
            }),
        }
    }

    /// Registrar evento de gap. Llamar para cada SandwichGap recibido.
    pub fn update(&self, gap_pct: f64) {
        let mut g = self.inner.write().unwrap();
        let now = Instant::now();

        g.window.push_back((now, gap_pct));

        // Evictar entradas > 60s
        let cutoff = now - Duration::from_secs(60);
        while g.window.front().map_or(false, |(t, _)| *t < cutoff) {
            g.window.pop_front();
        }

        let raw = Self::classify(&g.window);

        // Histéresis: en Chaos mínimo 5 min antes de bajar
        let new_state = if g.state == MarketState::Chaos && raw != MarketState::Chaos {
            match g.chaos_since {
                Some(since) if since.elapsed() < Duration::from_secs(300) => MarketState::Chaos,
                _ => {
                    g.chaos_since = None;
                    raw
                }
            }
        } else {
            raw
        };

        if new_state == MarketState::Chaos && g.state != MarketState::Chaos {
            g.chaos_since = Some(now);
        }

        if g.state != new_state {
            println!(
                "[chaos] {:?} → {:?}  (ventana={} eventos, max_gap={:.4}%)",
                g.state,
                new_state,
                g.window.len(),
                g.window.iter().map(|(_, x)| *x).fold(0.0_f64, f64::max) * 100.0,
            );
        }

        g.state = new_state;
    }

    fn classify(window: &VecDeque<(Instant, f64)>) -> MarketState {
        if window.is_empty() {
            return MarketState::Quiet;
        }

        let count = window.len();
        let max_gap = window.iter().map(|(_, g)| *g).fold(0.0_f64, f64::max);
        let avg_gap = window.iter().map(|(_, g)| g).sum::<f64>() / count as f64;

        if avg_gap > 0.0020 && count > 30 {
            // Caos = volatilidad SOSTENIDA (avg > 0.20%). Un spike individual NO es caos.
            // Gemma fix: max_gap solo no trigger Chaos — un gap gordo es oportunidad, no riesgo.
            MarketState::Chaos
        } else if count < 5 || max_gap < 0.0003 {
            // Pocos eventos o gaps muy pequeños → mercado tranquilo
            MarketState::Quiet
        } else {
            MarketState::Normal
        }
    }

    pub fn current_state(&self) -> MarketState {
        self.inner.read().unwrap().state
    }

    /// Config para el estado actual. Caller aplica: probe.min(balance * 0.90)
    pub fn current_config(&self) -> MarketConfig {
        match self.inner.read().unwrap().state {
            MarketState::Quiet => MarketConfig {
                state: MarketState::Quiet,
                probe_amount_usdc: 1_000.0,
                min_profit_usdc: 0.02,
                min_profit_bps: 0.5,
                max_tip_lamports: 5_000_000,
            },
            MarketState::Normal => MarketConfig {
                state: MarketState::Normal,
                probe_amount_usdc: 3_000.0,
                min_profit_usdc: 0.05,
                min_profit_bps: 1.0,
                max_tip_lamports: 10_000_000,
            },
            MarketState::Chaos => MarketConfig {
                state: MarketState::Chaos,
                probe_amount_usdc: 500.0,
                min_profit_usdc: 0.20,
                min_profit_bps: 5.0,
                max_tip_lamports: 10_000_000,
            },
        }
    }
}
