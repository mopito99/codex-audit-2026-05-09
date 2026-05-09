//! Yellowstone gRPC subscriber — feeds the in-memory PoolRegistry from on-chain
//! account updates of the configured CLMM pools.

use crate::config::Config;
use crate::pool_state::{self, PoolState};
use anyhow::{Context, Result};
use dashmap::DashMap;
use futures::StreamExt;
use solana_sdk::pubkey::Pubkey;
use std::collections::HashMap;
use std::sync::Arc;
use tracing::{debug, error, info, warn};
use yellowstone_grpc_client::GeyserGrpcClient;
use yellowstone_grpc_proto::geyser::{
    subscribe_update::UpdateOneof, CommitmentLevel, SubscribeRequest,
    SubscribeRequestFilterAccounts, SubscribeUpdate,
};

pub type PoolRegistry = Arc<DashMap<Pubkey, PoolState>>;

pub fn new_registry() -> PoolRegistry {
    Arc::new(DashMap::new())
}

pub async fn run(cfg: Config, registry: PoolRegistry) -> Result<()> {
    info!(grpc_url = %cfg.grpc_url, pools = cfg.pools.len(), "connecting Yellowstone");

    // R74 Ventana 1 Fase 1.1 — TCP_NODELAY=true (kill Nagle, see liquidator_rs/grpc.rs).
    let mut builder = GeyserGrpcClient::build_from_shared(cfg.grpc_url.clone())?
        .tls_config(yellowstone_grpc_client::ClientTlsConfig::new().with_native_roots())?
        .tcp_nodelay(true);
    if let Some(token) = cfg.grpc_token.as_deref() {
        builder = builder.x_token(Some(token.to_string()))?;
    }
    let mut client = builder.connect().await.context("connect Yellowstone")?;
    info!("Yellowstone connected");

    let pool_addrs: Vec<String> = cfg.pools.iter().map(|p| p.address.to_string()).collect();
    let mut accounts = HashMap::new();
    accounts.insert(
        "clmm_pools".to_string(),
        SubscribeRequestFilterAccounts {
            account: pool_addrs,
            owner: vec![],
            filters: vec![],
            nonempty_txn_signature: None,
        },
    );

    let req = SubscribeRequest {
        accounts,
        commitment: Some(CommitmentLevel::Processed as i32),
        ..Default::default()
    };
    let (_tx, mut stream) = client
        .subscribe_with_request(Some(req))
        .await
        .context("subscribe_with_request")?;
    info!("subscribed to {} CLMM pools (commitment=Processed)", cfg.pools.len());

    // Build address → (label, kind) lookup
    let pool_lookup: HashMap<Pubkey, (String, crate::config::PoolKind)> = cfg
        .pools
        .iter()
        .map(|p| (p.address, (p.label.clone(), p.kind)))
        .collect();

    let mut updates: u64 = 0;
    let mut decoded_ok: u64 = 0;
    let mut decoded_err: u64 = 0;

    while let Some(msg) = stream.next().await {
        let update = match msg {
            Ok(u) => u,
            Err(e) => {
                error!(error=?e, "stream error");
                continue;
            }
        };
        let SubscribeUpdate { update_oneof: Some(uo), .. } = update else {
            continue;
        };

        if let UpdateOneof::Account(acc_update) = uo {
            updates += 1;
            let Some(acc) = acc_update.account else { continue };
            let pubkey_bytes: [u8; 32] = match acc.pubkey.as_slice().try_into() {
                Ok(b) => b,
                Err(_) => continue,
            };
            let pubkey = Pubkey::new_from_array(pubkey_bytes);
            let Some((label, kind)) = pool_lookup.get(&pubkey).cloned() else {
                continue;
            };

            match pool_state::decode(pubkey, &label, kind, &acc.data, acc_update.slot) {
                Ok(state) => {
                    decoded_ok += 1;
                    debug!(
                        slot = acc_update.slot, %pubkey, %label,
                        liquidity = state.liquidity,
                        sqrt_price = state.sqrt_price_x64,
                        tick = state.tick_current,
                        "pool update"
                    );
                    registry.insert(pubkey, state);
                }
                Err(e) => {
                    decoded_err += 1;
                    warn!(error=?e, %pubkey, %label, "decode failed");
                }
            }

            if updates % 100 == 0 {
                info!(updates, decoded_ok, decoded_err, "stream stats");
            }
        }
    }

    Err(anyhow::anyhow!("Yellowstone stream ended"))
}
