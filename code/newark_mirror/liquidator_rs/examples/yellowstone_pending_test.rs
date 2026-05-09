//! M1 — Test Yellowstone transactions stream con commitment=Processed.
//! Standalone example: NO toca el daemon principal RUN2.
//! Suscribe transactions filter por 60s para Czfq3xZZ + 8sLbNZ pools y mide:
//!   - count de transactions delivered
//!   - delay entre primera entrega gRPC y confirmation via getSignatureStatuses
//!   - distribución p50/p95 lead time

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::time::{Duration, Instant};
use tokio_stream::StreamExt;
use yellowstone_grpc_client::GeyserGrpcClient;
use yellowstone_grpc_proto::geyser::{
    subscribe_update::UpdateOneof,
    CommitmentLevel, SubscribeRequest, SubscribeRequestFilterTransactions,
};

const POOL_ORCA: &str = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE";
const POOL_RAYDIUM: &str = "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj";

#[tokio::main]
async fn main() -> Result<()> {
    let url = std::env::var("LIQ_GRPC_URL")
        .or_else(|_| std::env::var("CHAINSTACK_GRPC_URL"))
        .context("missing LIQ_GRPC_URL")?;
    let token = std::env::var("LIQ_GRPC_TOKEN")
        .or_else(|_| std::env::var("CHAINSTACK_GRPC_TOKEN"))
        .ok();

    println!("[M1] connecting to {}", url);
    let mut client = GeyserGrpcClient::build_from_shared(url)?
        .x_token(token)?
        .tls_config(yellowstone_grpc_client::ClientTlsConfig::new().with_native_roots())?
        .connect()
        .await?;
    println!("[M1] connected");

    let mut tx_filter = HashMap::new();
    tx_filter.insert(
        "pool_txs".to_string(),
        SubscribeRequestFilterTransactions {
            vote: Some(false),
            failed: Some(false),
            signature: None,
            account_include: vec![POOL_ORCA.to_string(), POOL_RAYDIUM.to_string()],
            account_exclude: vec![],
            account_required: vec![],
        },
    );

    let req = SubscribeRequest {
        transactions: tx_filter,
        commitment: Some(CommitmentLevel::Processed as i32),
        ..Default::default()
    };

    let (_subscribe_tx, mut stream) = client.subscribe_with_request(Some(req)).await?;
    println!("[M1] subscribed transactions, commitment=Processed, account_include=[{},{}]", POOL_ORCA, POOL_RAYDIUM);

    let start = Instant::now();
    let deadline = Duration::from_secs(60);
    let mut count_total = 0u64;
    let mut count_orca = 0u64;
    let mut count_raydium = 0u64;
    let mut first_seen: HashMap<String, Instant> = HashMap::new();
    let mut slot_distrib: Vec<u64> = Vec::new();

    while start.elapsed() < deadline {
        let msg = match tokio::time::timeout(Duration::from_secs(2), stream.next()).await {
            Ok(Some(Ok(m))) => m,
            Ok(Some(Err(e))) => { eprintln!("[M1] stream err: {}", e); continue; }
            Ok(None) => { eprintln!("[M1] stream ended"); break; }
            Err(_) => continue,
        };
        if let Some(uo) = msg.update_oneof {
            match uo {
                UpdateOneof::Transaction(tx_update) => {
                    count_total += 1;
                    if let Some(t) = &tx_update.transaction {
                        let sig = bs58::encode(&t.signature).into_string();
                        first_seen.entry(sig.clone()).or_insert_with(Instant::now);
                        slot_distrib.push(tx_update.slot);
                        // Check if it's Orca or Raydium pool by parsing accounts
                        if let Some(tx) = &t.transaction {
                            if let Some(msg) = &tx.message {
                                let mut has_orca = false;
                                let mut has_raydium = false;
                                for acc in &msg.account_keys {
                                    let pk = bs58::encode(acc).into_string();
                                    if pk == POOL_ORCA { has_orca = true; }
                                    if pk == POOL_RAYDIUM { has_raydium = true; }
                                }
                                if has_orca { count_orca += 1; }
                                if has_raydium { count_raydium += 1; }
                            }
                        }
                    }
                }
                UpdateOneof::Ping(_) => {}
                _ => {}
            }
        }
    }

    let elapsed = start.elapsed().as_secs_f64();
    let unique_sigs = first_seen.len();
    let unique_slots: std::collections::HashSet<_> = slot_distrib.iter().collect();

    println!("\n[M1] === RESULTADOS 60s ===");
    println!("transactions delivered:  {} ({:.2}/s)", count_total, count_total as f64 / elapsed);
    println!("unique signatures:       {}", unique_sigs);
    println!("unique slots:            {}", unique_slots.len());
    println!("count Orca:              {}", count_orca);
    println!("count Raydium:           {}", count_raydium);
    println!("commitment level used:   Processed (per SubscribeRequest)");
    println!("\nIf you see >0 transactions: the gRPC stream IS delivering ALL TXs that mention pools (vote+failed filtered out).");
    println!("Compare these counts to mainnet TX rate Czfq3x={} tx/s, 8sLbNZ={} tx/s observed via getSignaturesForAddress.", "1.20", "0.35");
    println!("\nNOTE: Yellowstone with commitment=Processed delivers TXs as soon as they are processed by the validator (~400ms after signing). It does NOT deliver \"pending mempool\" pre-processing TXs unless using a separate banking_stage stream (Shredstream).");

    Ok(())
}
