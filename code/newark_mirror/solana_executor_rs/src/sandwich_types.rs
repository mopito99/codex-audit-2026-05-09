#![allow(dead_code)] // Future state — multi-pool refactor migrará desde sandwich_listener::SandwichOpportunity
// SandwichOpportunity — struct compartido Listener (Core 0) → Executor (Core 1).
//
// Diseño G75: Listener pre-computa TODO (filters, accounts resueltas, signer, cup).
// Executor solo hace: math → build → send. Cero parseo de proto en Core 1.
//
// Channel: crossbeam_channel::bounded(64) con política Drop New (G53).
// Si queue lleno, listener descarta nueva opportunity y loguea — NUNCA bloquea
// el gRPC stream.
//
// Generado a partir de respuesta Gemma I3.

use bytes::Bytes;
use solana_sdk::{pubkey::Pubkey, signature::Signature};
use std::sync::Arc;
use std::time::Instant;

/// Snapshot del estado del pool al momento de detectar la víctima.
/// Embebido (no Arc) para evitar race con state mirror update entre detect y build.
/// Tamaño: ~48 bytes — clonar es barato.
#[derive(Debug, Clone)]
pub struct WhirlpoolStateSnapshot {
    pub sqrt_price_x64: u128,
    pub liquidity: u128,
    pub tick_current: i32,
}

/// Oportunidad de sandwich con TODOS los datos pre-computados por el Listener.
/// Executor recibe este struct y solo necesita math/build/send.
#[derive(Debug, Clone)]
pub struct SandwichOpportunity {
    // Identidad
    pub victim_sig: Signature,
    pub detected_at: Instant,
    pub detected_slot: u64,
    pub pool_address: Pubkey,

    // Datos del swap
    pub victim_amount_in: u64,
    pub victim_a_to_b: bool,

    // Pool state al momento de detección
    pub pool_state: WhirlpoolStateSnapshot,

    // Pre-computados por Listener para filtrado ultra-rápido en Executor
    pub is_v0: bool,
    pub victim_signer: Pubkey,
    pub compute_unit_price: u64,
    pub passes_filters: bool, // false = víctima rechazada, paper mode aún logea

    // Cuentas resueltas (si v0, ya pasó por AltCache)
    pub resolved_accounts: Vec<Pubkey>,

    // Bytes raw de la TX (para incluir en bundle Jito).
    // Arc<Bytes> para evitar clonar 1.2KB en cada hop del pipeline.
    pub victim_tx_bytes: Arc<Bytes>,
}

/// Setup canal Listener → Executor con bounded crossbeam.
/// Capacity 64 = suficiente para picos (5-20 ops/s típico), pequeño para low queue latency.
pub fn setup_pipeline()
    -> (crossbeam_channel::Sender<SandwichOpportunity>,
        crossbeam_channel::Receiver<SandwichOpportunity>)
{
    crossbeam_channel::bounded(64)
}

// Política Drop New en el listener:
//   match tx_sender.try_send(opportunity) {
//       Ok(_) => {}
//       Err(crossbeam_channel::TrySendError::Full(_)) => {
//           metrics::inc_dropped_opportunity();
//           eprintln!("[listener] queue full, dropping opportunity");
//       }
//       Err(_) => {} // disconnected — executor murió
//   }
