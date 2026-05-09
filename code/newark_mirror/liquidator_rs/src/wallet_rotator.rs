//! R39 Q1 — WalletRotator skeleton (DORMANT).
//!
//! Pattern: ArcSwap<HotWallet> for zero-downtime wallet rotation.
//! Workers call `rotator.current()` to grab a snapshot Arc<HotWallet>; rotation
//! atomically swaps the inner pointer. In-flight signers continue to use their
//! captured Arc until they drop the reference.
//!
//! Activation: requires R40 follow-up #2 (env layout for warm pool of pre-funded
//! wallets) before main.rs wires this up. The wallets must already have their
//! USDC + wSOL ATAs created on-chain.

use crate::wallet::HotWallet;
use arc_swap::ArcSwap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tracing::info;

pub struct WalletRotator {
    current_wallet: ArcSwap<HotWallet>,
    warm_pool: Vec<Arc<HotWallet>>,
    pool_index: AtomicUsize,
}

impl WalletRotator {
    /// Build a rotator from a non-empty pool. Index 0 is the active wallet at startup.
    pub fn new(warm_pool: Vec<HotWallet>) -> anyhow::Result<Self> {
        if warm_pool.is_empty() {
            anyhow::bail!("WalletRotator: warm pool must contain at least one wallet");
        }
        let warm_pool: Vec<Arc<HotWallet>> =
            warm_pool.into_iter().map(Arc::new).collect();
        let initial = warm_pool[0].clone();
        Ok(Self {
            current_wallet: ArcSwap::new(initial),
            warm_pool,
            pool_index: AtomicUsize::new(0),
        })
    }

    /// Grab the wallet that workers should sign with right now.
    pub fn current(&self) -> Arc<HotWallet> {
        self.current_wallet.load_full()
    }

    /// Atomically rotate to the next wallet in the warm pool.
    /// CALLER is responsible for confirming `in_flight_bundles == 0` before
    /// invoking this — rotating mid-bundle does not invalidate the captured
    /// Arc but capital may be stranded across wallets.
    pub fn rotate(&self) {
        let next_idx = (self.pool_index.fetch_add(1, Ordering::SeqCst) + 1) % self.warm_pool.len();
        let next_wallet = self.warm_pool[next_idx].clone();
        self.current_wallet.store(next_wallet);
        info!(rotation_index = next_idx, "wallet rotated");
    }

    pub fn pool_size(&self) -> usize {
        self.warm_pool.len()
    }

    pub fn current_index(&self) -> usize {
        self.pool_index.load(Ordering::Relaxed) % self.warm_pool.len()
    }
}
