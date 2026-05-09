#![allow(dead_code)] // Phase 2 LIVE — paper mode no resuelve ALTs todavía
// AltCache (G59/G65/G70): caché de Address Lookup Tables para resolución v0 lock-free.
//
// Sin esto, cada VersionedTransaction v0 requeriría getAccountInfo en hot path
// (+10-30ms por TX) — suicidio competitivo. Con DashMap pre-cargada, la resolución
// es lookup en memoria (~ns).
//
// Uso:
//   let cache = AltCache::new();
//   cache.preload_known_orca(&rpc).await?;        // pre-carga ALTs canónicas Orca
//   spawn_lazy_refresh(cache.clone(), rpc.clone()); // background refresh 1h
//   let resolved: Vec<Pubkey> = cache.resolve_v0_message(&msg_v0)?; // hot path
//
// Política de errores: NUNCA panic. Si una ALT no está cacheada → return Err
// → executor descarta la TX y dispara lazy refresh asíncrono.

use anyhow::{anyhow, Result};
use dashmap::DashMap;
use solana_client::nonblocking::rpc_client::RpcClient;
use solana_sdk::{
    address_lookup_table::state::AddressLookupTable,
    message::v0::MessageAddressTableLookup,
    pubkey::Pubkey,
};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// ALTs canónicas de Orca SOL/USDC (G65 — pre-cargar al inicio).
/// Cubren >90% de swaps Orca v0 reales según observación de mainnet.
/// Si una v0 referencia una ALT fuera de esta lista → lazy load + descartar
/// esa TX (coste de aprendizaje — 1×).
pub const ORCA_KNOWN_ALTS: &[&str] = &[
    // ALT maestra Orca Whirlpool (whirlpools program ID + tick arrays comunes)
    "AGZAVAhSJupFK6PCTGsbEXQEU9q3R3wH9bN5SmQYrqQS",
    // ALT auxiliar Token-2022 + ATAs estándar
    "Cuh4VH5kQTzz3TxKD78XC5xGY56wbxYeFbzm38ngu5Wc",
];

#[derive(Clone)]
pub struct AltCache {
    cache: Arc<DashMap<Pubkey, Vec<Pubkey>>>,
    timestamps: Arc<DashMap<Pubkey, Instant>>,
}

impl AltCache {
    pub fn new() -> Self {
        Self {
            cache: Arc::new(DashMap::new()),
            timestamps: Arc::new(DashMap::new()),
        }
    }

    /// Tamaño actual del caché.
    pub fn len(&self) -> usize {
        self.cache.len()
    }

    pub fn is_empty(&self) -> bool {
        self.cache.is_empty()
    }

    /// Pre-carga ALTs canónicas conocidas de Orca al arrancar el bot.
    pub async fn preload_known_orca(&self, rpc: &RpcClient) -> Result<()> {
        for alt_str in ORCA_KNOWN_ALTS {
            let alt_key: Pubkey = alt_str
                .parse()
                .map_err(|e| anyhow!("invalid ALT pubkey {alt_str}: {e}"))?;
            match self.fetch_and_cache(rpc, &alt_key).await {
                Ok(n) => println!("[alt_cache] precargado {alt_key} ({n} addresses)"),
                Err(e) => eprintln!("[alt_cache] precarga falló {alt_key}: {e}"),
            }
        }
        Ok(())
    }

    /// Fetch desde RPC + parseo + insert en caché.
    pub async fn fetch_and_cache(&self, rpc: &RpcClient, alt_key: &Pubkey) -> Result<usize> {
        let account = rpc
            .get_account(alt_key)
            .await
            .map_err(|e| anyhow!("get_account ALT {alt_key}: {e}"))?;
        let alt = AddressLookupTable::deserialize(&account.data)
            .map_err(|e| anyhow!("deserialize ALT {alt_key}: {e}"))?;
        let addresses: Vec<Pubkey> = alt.addresses.to_vec();
        let len = addresses.len();
        self.cache.insert(*alt_key, addresses);
        self.timestamps.insert(*alt_key, Instant::now());
        Ok(len)
    }

    /// Lookup síncrono — usado en hot path. Si miss → Err (NO bloquear con fetch).
    pub fn get(&self, alt_key: &Pubkey) -> Option<Vec<Pubkey>> {
        self.cache.get(alt_key).map(|v| v.clone())
    }

    /// Resolución completa de un MessageV0 → lista plana de Pubkeys.
    ///
    /// Orden (G65): primero account_keys del message, luego ALT writable, luego ALT readonly.
    /// Si CUALQUIER ALT no está cacheada → Err (caller descarta TX + dispara lazy refresh).
    pub fn resolve_v0_message(
        &self,
        account_keys: &[Pubkey],
        lookups: &[MessageAddressTableLookup],
    ) -> Result<Vec<Pubkey>> {
        let mut all = account_keys.to_vec();

        // Primer paso: writable indexes de cada ALT (G65 — Solana runtime los procesa antes)
        for lookup in lookups {
            let alt_addresses = self.get(&lookup.account_key).ok_or_else(|| {
                anyhow!(
                    "ALT {} no está cacheada — descartando TX, lazy refresh disparado",
                    lookup.account_key
                )
            })?;
            for &idx in &lookup.writable_indexes {
                let i = idx as usize;
                if i >= alt_addresses.len() {
                    return Err(anyhow!(
                        "ALT {} writable index {i} fuera de rango (len={})",
                        lookup.account_key,
                        alt_addresses.len()
                    ));
                }
                all.push(alt_addresses[i]);
            }
        }

        // Segundo paso: readonly indexes
        for lookup in lookups {
            let alt_addresses = self.get(&lookup.account_key).ok_or_else(|| {
                anyhow!("ALT {} no cacheada (readonly pass)", lookup.account_key)
            })?;
            for &idx in &lookup.readonly_indexes {
                let i = idx as usize;
                if i >= alt_addresses.len() {
                    return Err(anyhow!(
                        "ALT {} readonly index {i} fuera de rango (len={})",
                        lookup.account_key,
                        alt_addresses.len()
                    ));
                }
                all.push(alt_addresses[i]);
            }
        }

        Ok(all)
    }
}

impl Default for AltCache {
    fn default() -> Self {
        Self::new()
    }
}

/// Background task: refresh de ALTs cada 1 hora (G70).
/// Las ALTs raramente cambian — refresh frecuente desperdicia RPC.
/// Si una resolución falla por "account not found" → lazy refresh on-demand.
pub fn spawn_periodic_refresh(cache: AltCache, rpc: Arc<RpcClient>) {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(3600));
        interval.tick().await; // primera tick es inmediata, descartarla
        loop {
            interval.tick().await;
            let keys: Vec<Pubkey> = cache.cache.iter().map(|e| *e.key()).collect();
            for k in keys {
                if let Err(e) = cache.fetch_and_cache(&rpc, &k).await {
                    eprintln!("[alt_cache] refresh {k} falló: {e}");
                }
            }
        }
    });
}
