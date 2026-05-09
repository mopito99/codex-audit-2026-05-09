// Filtro de Toxic Flow segun arquitectura de Gemma 2026-04-28.
// Distingue Mean Reversion (fat finger real) de Momentum Crash (precio en caida libre).

use solana_sdk::pubkey::Pubkey;
use std::sync::Arc;
use std::time::{Duration, Instant};
use dashmap::DashMap;

#[derive(Debug, Clone)]
pub struct MarketSnapshot {
    pub asset_mint: String,
    pub last_30s_volume_usd: f64,
    pub sell_volume_pct: f64,         // 0.0 a 1.0
    pub whale_tx_count: u32,          // txs > $1k en misma direccion ultimos 10 slots
    pub price_change_last_5s: f64,    // delta porcentual
    pub slots_since_gap_start: u64,
    pub updated_at: Instant,
}

impl Default for MarketSnapshot {
    fn default() -> Self {
        Self {
            asset_mint: String::new(),
            last_30s_volume_usd: 0.0,
            sell_volume_pct: 0.5,
            whale_tx_count: 0,
            price_change_last_5s: 0.0,
            slots_since_gap_start: 0,
            updated_at: Instant::now(),
        }
    }
}

pub struct ToxicityFilter {
    // Mints clasificados como meme (umbrales mas estrictos)
    meme_mints: Vec<&'static str>,
    // Snapshot global por mint, actualizado por worker
    snapshots: Arc<DashMap<String, MarketSnapshot>>,
    // Si no hay snapshot reciente (>10s), asumir SAFE (failsafe permisivo)
    snapshot_max_age_secs: u64,
}

impl ToxicityFilter {
    pub fn new(snapshots: Arc<DashMap<String, MarketSnapshot>>) -> Self {
        Self {
            // BONK + WIF
            meme_mints: vec![
                "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  // BONK
                "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",  // WIF
            ],
            snapshots,
            snapshot_max_age_secs: 10,
        }
    }

    fn is_meme(&self, mint: &str) -> bool {
        self.meme_mints.contains(&mint)
    }

    /// Retorna (toxic, razon). toxic=true significa rechazar trade.
    pub fn is_toxic(&self, mint: &str) -> (bool, &'static str) {
        let snapshot = match self.snapshots.get(mint) {
            Some(s) => s.clone(),
            None => return (false, "no_data_assume_safe"),
        };

        // Si snapshot stale, no podemos confiar — asumir SAFE pero log
        if snapshot.updated_at.elapsed().as_secs() > self.snapshot_max_age_secs {
            return (false, "snapshot_stale_assume_safe");
        }

        let is_meme = self.is_meme(mint);

        // Umbrales segun Gemma 2026-04-28
        let max_sell_vol_pct      = if is_meme { 0.60 } else { 0.75 };
        let max_whale_txs         = if is_meme { 2 }    else { 3 };
        let max_price_velocity    = if is_meme { -0.01 } else { -0.02 };
        let max_gap_duration      = if is_meme { 3 }    else { 5 };

        // 1. Volumen direccional (sell pressure)
        if snapshot.sell_volume_pct > max_sell_vol_pct {
            return (true, "sell_pressure");
        }

        // 2. Whale pressure (3+ ballenas misma direccion)
        if snapshot.whale_tx_count >= max_whale_txs {
            return (true, "whale_pressure");
        }

        // 3. Velocity (caida muy rapida = crash)
        if snapshot.price_change_last_5s < max_price_velocity {
            return (true, "price_crash");
        }

        // 4. Gap duration (fat finger se corrige rapido, momentum no)
        if snapshot.slots_since_gap_start > max_gap_duration {
            return (true, "gap_too_persistent");
        }

        (false, "safe")
    }
}

/// Helper para crear el DashMap compartido entre worker y filter
pub fn new_snapshot_map() -> Arc<DashMap<String, MarketSnapshot>> {
    Arc::new(DashMap::new())
}
