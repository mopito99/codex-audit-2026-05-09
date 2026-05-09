// Sandwich listener — Yellowstone gRPC subscriber.
// Mantiene espejo local del estado del pool Whirlpool y detecta txs víctimas.
//
// Pipeline: gRPC recv → parse victim amount_in → check profitability → signal executor

use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::Instant;

use anyhow::{Context, Result};
use crossbeam_queue::ArrayQueue;
use solana_sdk::pubkey::Pubkey;
use tokio::sync::mpsc;
use tonic::metadata::MetadataValue;
use tonic::transport::{Channel, ClientTlsConfig};
use tonic::Request;
use tokio_stream::wrappers::ReceiverStream;

use yellowstone_grpc_proto::geyser::{
    geyser_client::GeyserClient,
    subscribe_update::UpdateOneof,
    CommitmentLevel, SubscribeRequest, SubscribeRequestFilterAccounts,
    SubscribeRequestFilterSlots, SubscribeRequestFilterTransactions,
};

use crate::config::EnvCfg;
use crate::metrics;

// ── Pool monitoreado ──────────────────────────────────────────────────────────

// Pool Orca SOL/USDC principal. Cambiar a Vec<Pubkey> para multi-pool.
pub const ORCA_SOL_USDC: &str = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE";

// Programas DEX que nos interesan para filtrar txs víctimas
const ORCA_WHIRLPOOL_PROGRAM: &str = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc";

// ── State mirror Whirlpool (G33: offsets exactos del account data) ────────────

#[derive(Default, Clone, Debug)]
#[allow(dead_code)] // tick_current/updated_at usados en Phase 2 LIVE (orca_builder.tick_array_pda)
pub struct WhirlpoolState {
    pub sqrt_price_x64: u128, // offset 8..24
    pub liquidity:      u128, // offset 24..40
    pub tick_current:   i32,  // offset 40..44
    pub slot:           u64,
    pub updated_at:     Option<Instant>,
}

impl WhirlpoolState {
    pub fn from_account_data(data: &[u8], slot: u64) -> Option<Self> {
        if data.len() < 86 {
            return None;
        }
        // Offsets validados on-chain (tick_spacing_seed es 2 bytes, NO 4):
        // [0..8]   discriminador Anchor
        // [8..40]  whirlpools_config
        // [40..41] whirlpool_bump  [41..43] tick_spacing  [43..45] tick_spacing_seed (2B)
        // [45..47] fee_rate  [47..49] protocol_fee_rate
        // [49..65] liquidity (u128)
        // [65..81] sqrt_price_x64 (u128)
        // [81..85] tick_current_index (i32)
        Some(Self {
            liquidity:      u128::from_le_bytes(data[49..65].try_into().ok()?),
            sqrt_price_x64: u128::from_le_bytes(data[65..81].try_into().ok()?),
            tick_current:   i32::from_le_bytes(data[81..85].try_into().ok()?),
            slot,
            updated_at: Some(Instant::now()),
        })
    }

    /// Precio SOL/USDC en USD. Fórmula Q64.64: (sqrt/2^64)^2 × 10^(9-6).
    pub fn price_usdc_per_sol(&self) -> f64 {
        let sqrt = self.sqrt_price_x64 as f64 / (1u128 << 64) as f64;
        sqrt * sqrt * 1_000.0 // ×10^(9-6) = ×1000
    }
}

// ── Oportunidad de sandwich detectada ────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct SandwichOpportunity {
    pub victim_sig:       String,
    pub victim_amount_in: u64,    // raw units: USDC microcents si a_to_b=false, SOL lamports si a_to_b=true
    pub victim_a_to_b:    bool,   // true=SOL→USDC, false=USDC→SOL (direction de la víctima)
    pub pool_state:       WhirlpoolState,
    pub detected_at:      Instant,
    pub detected_slot:    u64,

    // S3 — versioned transaction tracking (G77)
    pub is_v0:            bool,            // msg.versioned (true = v0 con ALTs)
    pub num_alt_lookups:  u8,              // address_table_lookups.len()

    // G75 — pre-computado por listener para que executor solo haga math/build/send
    pub victim_signer:    Option<String>,  // first signer (base58) — None si parse falla
    pub compute_unit_price: u64,            // microlamports — 0 si no hay SetComputeUnitPrice ix
    pub has_jito_tip:     bool,            // G58 — alguna account_key es Jito tip
    pub filter_reason:    Option<String>,  // None = candidate, Some(reason) = bot/rejected
}

// ── Pool state map (compartido con el executor) ───────────────────────────────

pub type PoolStateMap = Arc<RwLock<HashMap<Pubkey, WhirlpoolState>>>;

pub fn new_pool_state_map() -> PoolStateMap {
    Arc::new(RwLock::new(HashMap::new()))
}

// ── Extraer amount_in + dirección de una instrucción Orca Whirlpool swap ─────
// Orca swap layout (post-discriminador, G29):
//   bytes  0.. 8 : discriminador Anchor
//   bytes  8..16 : amount (u64 LE)
//   bytes 16..24 : other_amount_threshold (u64 LE)
//   bytes 24..40 : sqrt_price_limit (u128 LE)
//   byte  40     : amount_specified_is_input (bool)
//   byte  41     : a_to_b (bool) — true = SOL→USDC, false = USDC→SOL

fn extract_swap_info(instruction_data: &[u8]) -> Option<(u64, bool)> {
    if instruction_data.len() < 42 {
        return None;
    }
    let amount = u64::from_le_bytes(instruction_data[8..16].try_into().ok()?);
    let a_to_b = instruction_data[41] != 0;
    Some((amount, a_to_b))
}

// ── ComputeBudget program: extraer SetComputeUnitPrice ────────────────────────
// G68: cup > 100K microlamports → bot. Detección rápida sin parsear toda la TX.
//
// ComputeBudget instructions:
//   discriminator byte 0 → 0x00=RequestUnits(legacy), 0x01=RequestHeapFrame,
//                          0x02=SetComputeUnitLimit, 0x03=SetComputeUnitPrice
//   SetComputeUnitPrice: [0x03][u64 LE microlamports]

const COMPUTE_BUDGET_PROGRAM: &str = "ComputeBudget111111111111111111111111111111";

fn extract_compute_unit_price(instruction_data: &[u8]) -> Option<u64> {
    if instruction_data.len() < 9 || instruction_data[0] != 0x03 {
        return None;
    }
    Some(u64::from_le_bytes(instruction_data[1..9].try_into().ok()?))
}

// G58 — Jito tip detection: usar lista canónica de bot_detector (single source of truth).
// Lookup en O(N) sobre account_keys (N=11-25 → <500ns).
fn account_keys_contain_jito_tip(account_keys: &[Vec<u8>]) -> bool {
    for k in account_keys {
        let b58 = bs58::encode(k).into_string();
        if crate::bot_detector::JITO_TIP_ACCOUNTS.iter().any(|j| *j == b58) {
            return true;
        }
    }
    false
}

// ── Conectar al stream gRPC de Yellowstone ────────────────────────────────────
// subscribe() es bidireccional (G43): devolvemos un Sender<SubscribeRequest> para
// poder enviar re-suscripciones sin reconectar. Auth via metadata per-request.

async fn connect(cfg: &EnvCfg) -> Result<GeyserClient<Channel>> {
    // Si la URL ya incluye puerto (ej: host:443), usarla tal cual.
    // Si no tiene puerto, añadir :443 (Chainstack usa 443, Helius usaba 2053).
    let base = cfg.chainstack_grpc_url
        .trim_start_matches("https://")
        .trim_end_matches('/');
    let endpoint = if base.contains(':') {
        format!("https://{base}")
    } else {
        format!("https://{base}:443")
    };

    eprintln!("[grpc] endpoint: {endpoint}");
    let channel = Channel::from_shared(endpoint)
        .context("URL gRPC inválida")?
        .tls_config(ClientTlsConfig::new().with_native_roots())?
        .connect()
        .await
        .map_err(|e| anyhow::anyhow!("gRPC connect failed: {e:?}"))?;

    Ok(GeyserClient::new(channel))
}

// Construye un streaming request con auth header y la suscripción inicial.
// Retorna (stream_sender, request) — mantener stream_sender vivo para que el stream no cierre.
fn make_subscribe_request(
    subscribe_req: SubscribeRequest,
    token: &str,
) -> (mpsc::Sender<SubscribeRequest>, Request<ReceiverStream<SubscribeRequest>>) {
    let (req_tx, req_rx) = mpsc::channel::<SubscribeRequest>(4);
    // Enviar la suscripción inicial (bloqueante no es problema, el canal tiene capacidad 4)
    let _ = req_tx.try_send(subscribe_req);

    let stream = ReceiverStream::new(req_rx);
    let mut request = Request::new(stream);
    if !token.is_empty() {
        if let Ok(val) = token.parse::<MetadataValue<tonic::metadata::Ascii>>() {
            request.metadata_mut().insert("x-token", val);
        }
    }
    (req_tx, request)
}

// ── Construir el SubscribeRequest (txs + accounts + slots en 1 stream) ────────

fn build_subscribe_request(pool_addresses: &[&str]) -> SubscribeRequest {
    let account_list: Vec<String> = pool_addresses.iter().map(|s| s.to_string()).collect();

    SubscribeRequest {
        // Transacciones que tocan alguno de nuestros pools (detectar víctimas)
        transactions: HashMap::from([(
            "sandwich_victims".to_string(),
            SubscribeRequestFilterTransactions {
                vote:            Some(false),
                failed:          Some(false),
                account_include: account_list.clone(),
                ..Default::default()
            },
        )]),

        // Account updates de los pools (mantener state mirror)
        accounts: HashMap::from([(
            "pool_mirrors".to_string(),
            SubscribeRequestFilterAccounts {
                account: account_list,
                owner:   vec![],
                filters: vec![],
                ..Default::default()
            },
        )]),

        // Confirmaciones de slot (para detectar stale state, G43)
        slots: HashMap::from([(
            "slot_confirm".to_string(),
            SubscribeRequestFilterSlots {
                filter_by_commitment: Some(true),  // solo slots con commitment confirmado
                interslot_updates:    Some(false),
            },
        )]),

        commitment: Some(CommitmentLevel::Processed as i32),
        ..Default::default()
    }
}

// ── Loop principal del listener ───────────────────────────────────────────────

/// Corre el listener de sandwich en background.
/// Empuja oportunidades a la ArrayQueue lock-free (G53) cuando detecta una víctima rentable.
/// `pool_state` se actualiza continuamente con el estado del pool.
/// `bot_detector` registra TODAS las TXs (G75) para construir blacklist dinámica.
pub async fn run_sandwich_listener(
    cfg:         Arc<EnvCfg>,
    pool_state:  PoolStateMap,
    opp_queue:   Arc<ArrayQueue<SandwichOpportunity>>,
    bot_detector: Arc<crate::bot_detector::BotDetector>,
    min_victim_usdc: f64,  // ignorar víctimas menores a este monto (e.g. $200)
) {
    let pools = vec![ORCA_SOL_USDC];
    let pool_pubkey = ORCA_SOL_USDC.parse::<Pubkey>().expect("pool address válida");

    loop {
        println!("[sandwich_listener] conectando a Yellowstone gRPC...");
        let mut client = match connect(&cfg).await {
            Ok(c) => { println!("[sandwich_listener] conectado ✓"); c }
            Err(e) => {
                eprintln!("[sandwich_listener] error de conexión: {e} — reintento en 5s");
                tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                continue;
            }
        };

        // Subscribe es bidi-streaming: enviar suscripción inicial via canal
        let subscribe_req = build_subscribe_request(&pools);
        let (_req_keeper, grpc_req) = make_subscribe_request(subscribe_req, &cfg.chainstack_grpc_token);
        // _req_keeper debe mantenerse vivo para que el stream no se cierre

        let mut stream = match client.subscribe(grpc_req).await {
            Ok(r) => r.into_inner(),
            Err(e) => {
                eprintln!("[sandwich_listener] subscribe error: {e} — reintento en 5s");
                tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                continue;
            }
        };

        println!("[sandwich_listener] stream activo — monitoreando {}", ORCA_SOL_USDC);

        while let Ok(Some(update)) = stream.message().await {
            match update.update_oneof {

                // ── Account update → actualizar state mirror ──────────────────
                Some(UpdateOneof::Account(acc_update)) => {
                    let Some(acc_info) = acc_update.account else { continue };
                    let pubkey = match Pubkey::try_from(acc_info.pubkey.as_slice()) {
                        Ok(p) => p,
                        Err(_) => continue,
                    };
                    if pubkey != pool_pubkey { continue; }

                    if let Some(state) = WhirlpoolState::from_account_data(&acc_info.data, acc_update.slot) {
                        pool_state.write().unwrap().insert(pubkey, state);
                    }
                }

                // ── Transaction → buscar víctima ──────────────────────────────
                Some(UpdateOneof::Transaction(tx_update)) => {
                    let Some(tx_info)   = tx_update.transaction else { continue };
                    let Some(vtx_proto) = tx_info.transaction   else { continue };
                    let Some(msg)       = vtx_proto.message     else { continue };

                    let sig = tx_info.signature.iter()
                        .map(|b| format!("{:02x}", b))
                        .collect::<String>();

                    // S3 — detección de v0 + ALT lookups (G77)
                    let is_v0 = msg.versioned;
                    let num_alt_lookups = msg.address_table_lookups.len() as u8;

                    // G58 — pre-cómputo: alguna account_key es Jito tip?
                    let has_jito_tip = account_keys_contain_jito_tip(&msg.account_keys);

                    // G75 — first signer = "victim_signer" (base58 del primer key)
                    // En Solana, el primer N keys son signers según msg.header.num_required_signatures
                    let victim_signer: Option<String> = msg.account_keys.first()
                        .map(|k| bs58::encode(k).into_string());

                    // Pre-pasada para extraer ComputeUnitPrice y detectar Orca swap
                    let mut cup: u64 = 0;
                    let mut orca_swap: Option<(u64, bool)> = None;

                    for ix in &msg.instructions {
                        let prog_idx = ix.program_id_index as usize;
                        let Some(prog_bytes) = msg.account_keys.get(prog_idx) else { continue };
                        let prog_key = bs58::encode(prog_bytes).into_string();

                        // ComputeBudget: SetComputeUnitPrice
                        if prog_key == COMPUTE_BUDGET_PROGRAM {
                            if let Some(price) = extract_compute_unit_price(&ix.data) {
                                cup = price;
                            }
                            continue;
                        }

                        // Orca Whirlpool swap
                        if prog_key == ORCA_WHIRLPOOL_PROGRAM && orca_swap.is_none() {
                            if let Some(info) = extract_swap_info(&ix.data) {
                                orca_swap = Some(info);
                            }
                        }
                    }

                    let Some((amount_in, a_to_b)) = orca_swap else { continue };

                    // Normalizar a USDC para filtro mínimo
                    let amount_usdc = if a_to_b {
                        let state_tmp = pool_state.read().unwrap()
                            .get(&pool_pubkey).cloned().unwrap_or_default();
                        amount_in as f64 / 1e9 * state_tmp.price_usdc_per_sol()
                    } else {
                        amount_in as f64 / 1_000_000.0
                    };
                    if amount_usdc < min_victim_usdc { continue; }

                    // G75 — registrar TODAS las TXs en BotDetector para blacklist dinámica.
                    // signer es el primer key (already extracted as victim_signer).
                    if let Some(signer_b58) = victim_signer.as_ref() {
                        if let Ok(signer_pk) = signer_b58.parse::<Pubkey>() {
                            bot_detector.observe(signer_pk, cup);
                        }
                    }

                    // G68 — clasificación pipeline (modo observación: NO descartamos,
                    // solo logueamos filter_reason para baseline data en paper mode).
                    let signer_pk_opt: Option<Pubkey> = victim_signer.as_ref()
                        .and_then(|s| s.parse::<Pubkey>().ok());

                    let filter_reason = if has_jito_tip {
                        Some("jito_tip_in_keys".to_string())
                    } else if cup > 100_000 {
                        Some(format!("high_cup_{}", cup))
                    } else if signer_pk_opt.as_ref().map_or(false, |s| bot_detector.is_blacklisted(s)) {
                        Some("blacklisted_signer".to_string())
                    } else {
                        None
                    };

                    let state = pool_state.read().unwrap()
                        .get(&pool_pubkey).cloned()
                        .unwrap_or_default();

                    let opp = SandwichOpportunity {
                        victim_sig:       sig.clone(),
                        victim_amount_in: amount_in,
                        victim_a_to_b:    a_to_b,
                        pool_state:       state,
                        detected_at:      Instant::now(),
                        detected_slot:    tx_update.slot,
                        is_v0,
                        num_alt_lookups,
                        victim_signer,
                        compute_unit_price: cup,
                        has_jito_tip,
                        filter_reason: filter_reason.clone(),
                    };

                    let v0_marker = if is_v0 { format!("v0+{}ALT ", num_alt_lookups) } else { String::new() };
                    let filter_marker = filter_reason.as_deref().map(|r| format!(" [BOT:{r}]")).unwrap_or_default();
                    println!(
                        "[sandwich] víctima {}detectada: amount=${:.0} cup={} slot={} sig={}...{}",
                        v0_marker, amount_usdc, cup, tx_update.slot, &sig[..8], filter_marker
                    );

                    let _ = opp_queue.push(opp);
                    metrics::inc_victim_detected();
                }

                // ── Slot confirmation → stale detection (G43) ─────────────────
                Some(UpdateOneof::Slot(slot_update)) => {
                    // El executor usa este slot para marcar bundles como stale.
                    // Por ahora solo logueamos cada 100 slots para diagnóstico.
                    if slot_update.slot % 100 == 0 {
                        println!("[sandwich_listener] slot confirmed: {}", slot_update.slot);
                    }
                }

                _ => {} // ignorar otros updates (block, ping, etc.)
            }
        }

        eprintln!("[sandwich_listener] stream cerrado — reconectando en 3s");
        tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;
    }
}
