// Worker que prefetch el blockhash actual cada 200ms.
// Elimina el RPC roundtrip durante construccion del bundle (ahorra ~100ms).
// Patron de Gemma 2026-04-28.

use solana_client::rpc_client::RpcClient;
use solana_sdk::hash::Hash;
use std::sync::{Arc, RwLock};
use std::time::Duration;

pub type BlockhashCache = Arc<RwLock<Option<Hash>>>;

pub fn new_cache() -> BlockhashCache {
    Arc::new(RwLock::new(None))
}

pub fn spawn(rpc: Arc<RpcClient>, cache: BlockhashCache) {
    tokio::spawn(async move {
        loop {
            // Solana blockhash valido ~150 slots = ~60s. Refresh cada 200ms es mucho margen.
            tokio::time::sleep(Duration::from_millis(200)).await;
            // get_latest_blockhash es bloqueante — usar spawn_blocking para no bloquear runtime
            let rpc_clone = rpc.clone();
            let result = tokio::task::spawn_blocking(move || {
                rpc_clone.get_latest_blockhash()
            }).await;
            match result {
                Ok(Ok(bh)) => {
                    if let Ok(mut w) = cache.write() {
                        *w = Some(bh);
                    }
                }
                _ => {
                    // Mantener el cache previo si falla
                }
            }
        }
    });
}

/// Lee el blockhash cacheado. Retorna None si nunca se ha llenado.
pub fn get(cache: &BlockhashCache) -> Option<Hash> {
    cache.read().ok().and_then(|r| *r)
}
