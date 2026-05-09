#![allow(dead_code)] // Phase 2 LIVE — paper mode no construye TXs todavía
// G24 — Orca Whirlpool CLMM swap instruction builder (local, sin Jupiter).
// Construye instrucciones de swap directamente → latencia <5ms vs 30ms+ HTTP Jupiter.
// Prerequisito para sandwich LIVE: necesita OrcaPoolInfo cargada al arrancar (fetch RPC).
//
// Offsets del Whirlpool account confirmados (Anchor, 8 bytes discriminador + struct fields).
// Gemma confirmó que los offsets IDL son correctos. G33 era incorrecto (ignoraba config fields).
//   whirlpools_config:   8..40   (32)
//   whirlpool_bump:     40..41   (1)
//   tick_spacing:       41..43   (2)
//   tick_spacing_seed:  43..45   (2)  ← 2 bytes NO 4 (validado on-chain)
//   fee_rate:           45..47   (2)
//   protocol_fee_rate:  47..49   (2)
//   liquidity:          49..65   (16) ✓ CONFIRMADO on-chain
//   sqrt_price:         65..81   (16) ✓ CONFIRMADO on-chain
//   tick_current_index: 81..85   (4)  ✓ CONFIRMADO on-chain
//   protocol_fee_owed_a: 85..93  (8)
//   protocol_fee_owed_b: 93..101 (8)
//   token_mint_a:      101..133  (32)
//   token_vault_a:     133..165  (32)  ← usamos este
//   fee_growth_global_a:165..181 (16)
//   token_mint_b:      181..213  (32)
//   token_vault_b:     213..245  (32)  ← usamos este

use anyhow::{Context, Result};
use solana_client::rpc_client::RpcClient;
use solana_sdk::{
    hash::hashv,
    instruction::{AccountMeta, Instruction},
    pubkey::Pubkey,
};
use std::str::FromStr;
use std::sync::Arc;

// ── Constantes de programa ────────────────────────────────────────────────────

pub const ORCA_WHIRLPOOL_PROGRAM_ID: &str = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc";
const TOKEN_PROGRAM_ID:   &str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const ATA_PROGRAM_ID:     &str = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bBJ";

// Mints conocidos para el pool SOL/USDC
pub const WSOL_MINT:  &str = "So11111111111111111111111111111111111111112";
pub const USDC_MINT:  &str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

// Pool Orca SOL/USDC principal (mismo que ORCA_SOL_USDC en sandwich_listener)
pub const ORCA_SOL_USDC_POOL: &str = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE";

// sqrt_price_limit sin restricción (G24/G29) — evita que el swap falle por precio
const SQRT_PRICE_MIN: u128 = 4_295_048_016;                         // a_to_b=true  (SOL→USDC)
const SQRT_PRICE_MAX: u128 = 79_226_673_515_401_279_992_447_579_055; // a_to_b=false (USDC→SOL)

// ── Anchor discriminator ──────────────────────────────────────────────────────

/// sha256("global:swap")[0..8] — discriminador de la instrucción swap de Orca Whirlpool.
/// Calculado en runtime con solana_sdk::hash::hashv (SHA256).
fn swap_discriminator() -> [u8; 8] {
    let hash = hashv(&[b"global:swap"]);
    hash.to_bytes()[..8].try_into().expect("discriminator slice")
}

// ── Pool info ─────────────────────────────────────────────────────────────────

/// Direcciones del pool necesarias para construir instrucciones de swap.
/// Cargadas una vez al arrancar — inmutables en runtime.
#[derive(Debug, Clone)]
pub struct OrcaPoolInfo {
    pub whirlpool:     Pubkey,
    pub token_vault_a: Pubkey, // vault SOL (wSOL)
    pub token_vault_b: Pubkey, // vault USDC
    pub oracle:        Pubkey, // PDA oracle del pool
}

impl OrcaPoolInfo {
    /// Parsea las vault addresses desde los bytes crudos del account Whirlpool.
    /// Offsets basados en el struct Anchor (ver cabecera de archivo).
    pub fn from_account_data(whirlpool: Pubkey, data: &[u8]) -> Result<Self> {
        if data.len() < 245 {
            anyhow::bail!("Whirlpool account data insuficiente: {} bytes (mínimo 245)", data.len());
        }

        let token_vault_a = Pubkey::try_from(&data[133..165])
            .context("parse token_vault_a @ 133..165")?;
        let token_vault_b = Pubkey::try_from(&data[213..245])
            .context("parse token_vault_b @ 213..245")?;

        // Oracle PDA: seeds = [b"oracle", whirlpool]
        let prog = Pubkey::from_str(ORCA_WHIRLPOOL_PROGRAM_ID).unwrap();
        let (oracle, _) = Pubkey::find_program_address(
            &[b"oracle", whirlpool.as_ref()],
            &prog,
        );

        Ok(Self { whirlpool, token_vault_a, token_vault_b, oracle })
    }

    /// Fetch sincrónico desde RPC. Llamar en startup antes de arrancar el executor.
    pub fn fetch(rpc: &Arc<RpcClient>, pool_addr: &str) -> Result<Self> {
        let pool = Pubkey::from_str(pool_addr).context("parse pool pubkey")?;
        let account = rpc.get_account(&pool).context("get_account Whirlpool")?;
        Self::from_account_data(pool, &account.data)
    }

    /// Startup diagnostic: confirma precio SOL actual y direcciones de vault.
    pub fn verify_offsets(data: &[u8]) {
        println!("[orca_builder] Whirlpool account: {} bytes", data.len());
        if data.len() >= 86 {
            let liq  = u128::from_le_bytes(data[49..65].try_into().unwrap_or_default());
            let sqrt = u128::from_le_bytes(data[65..81].try_into().unwrap_or_default());
            let tick = i32::from_le_bytes(data[81..85].try_into().unwrap_or_default());
            let two64 = (1u128 << 64) as f64;
            let price = { let s = sqrt as f64 / two64; s * s * 1000.0 };
            println!("  sqrt_price_x64={sqrt} liquidity={liq} tick={tick} → price_sol=${price:.2}");
            if price < 50.0 || price > 2000.0 {
                eprintln!("  ⚠️  precio fuera de rango — verificar pool address o account data");
            }
        }
        if data.len() >= 245 {
            let va = Pubkey::try_from(&data[133..165]).map(|p| p.to_string()).unwrap_or("ERR".into());
            let vb = Pubkey::try_from(&data[213..245]).map(|p| p.to_string()).unwrap_or("ERR".into());
            println!("  vault_a={va}");
            println!("  vault_b={vb}");
        }
    }
}

// ── Tick Array PDA (G29) ──────────────────────────────────────────────────────

/// PDA del TickArray que contiene tick_current.
/// start_tick_index = floor(tick_current / 88) * 88 (división entera hacia -∞).
/// Siempre pasar 3 arrays DISTINTOS consecutivos — Solana rechaza accounts mutables duplicados.
pub fn tick_array_pda(whirlpool: &Pubkey, tick_current: i32) -> Pubkey {
    // División hacia -∞ para índices negativos (comportamiento CLMM correcto)
    let start = if tick_current >= 0 {
        (tick_current / 88) * 88
    } else {
        ((tick_current - 87) / 88) * 88
    };
    let prog = Pubkey::from_str(ORCA_WHIRLPOOL_PROGRAM_ID).unwrap();
    let (pda, _) = Pubkey::find_program_address(
        &[b"tick_array", whirlpool.as_ref(), &(start as i32).to_le_bytes()],
        &prog,
    );
    pda
}

// ── Associated Token Account (sin spl_associated_token_account crate) ─────────

/// ATA PDA: find_program_address([owner, token_program, mint], ATA_PROGRAM).
pub fn get_ata(owner: &Pubkey, mint: &Pubkey) -> Pubkey {
    let token_prog = Pubkey::from_str(TOKEN_PROGRAM_ID).unwrap();
    let ata_prog   = Pubkey::from_str(ATA_PROGRAM_ID).unwrap();
    let (pda, _) = Pubkey::find_program_address(
        &[owner.as_ref(), token_prog.as_ref(), mint.as_ref()],
        &ata_prog,
    );
    pda
}

// ── Swap instruction builder ──────────────────────────────────────────────────

/// Construye una instrucción swap Orca Whirlpool CLMM lista para incluir en un bundle.
///
/// - `a_to_b = true`:  SOL → USDC (front-run cuando víctima compra SOL con USDC)
/// - `a_to_b = false`: USDC → SOL (front-run cuando víctima vende SOL por USDC)
/// - `amount_in`:      lamports si a_to_b, microcents USDC si !a_to_b
/// - `min_amount_out`: precio límite estricto (G56): probe × (1 - impact) × 0.999
/// - `tick_current`:   del pool state mirror (WhirlpoolState.tick_current)
pub fn build_swap_ix(
    pool:           &OrcaPoolInfo,
    user:           &Pubkey,
    amount_in:      u64,
    min_amount_out: u64,
    a_to_b:         bool,
    tick_current:   i32,
) -> Instruction {
    let program_id   = Pubkey::from_str(ORCA_WHIRLPOOL_PROGRAM_ID).unwrap();
    let token_prog   = Pubkey::from_str(TOKEN_PROGRAM_ID).unwrap();
    let wsol         = Pubkey::from_str(WSOL_MINT).unwrap();
    let usdc         = Pubkey::from_str(USDC_MINT).unwrap();

    let user_ata_sol  = get_ata(user, &wsol);
    let user_ata_usdc = get_ata(user, &usdc);

    // 3 TickArrays consecutivos — Solana rechaza accounts mutables duplicados (S5 Gemma)
    // a_to_b=true (precio baja): necesitamos start, start-88, start-176
    // a_to_b=false (precio sube): necesitamos start, start+88, start+176
    let start = if tick_current >= 0 { (tick_current / 88) * 88 } else { ((tick_current - 87) / 88) * 88 };
    let tick_arr_0 = tick_array_pda(&pool.whirlpool, start);
    let tick_arr_1 = if a_to_b {
        tick_array_pda(&pool.whirlpool, start - 88)
    } else {
        tick_array_pda(&pool.whirlpool, start + 88)
    };
    let tick_arr_2 = if a_to_b {
        tick_array_pda(&pool.whirlpool, start - 176)
    } else {
        tick_array_pda(&pool.whirlpool, start + 176)
    };

    // sqrt_price_limit: sin restricción (swap siempre completa al precio de mercado)
    let sqrt_limit = if a_to_b { SQRT_PRICE_MIN } else { SQRT_PRICE_MAX };

    // Instrucción data: discriminator(8) + amount(8) + threshold(8) + sqrt_limit(16) + flags(2) = 42 bytes
    let mut data = Vec::with_capacity(42);
    data.extend_from_slice(&swap_discriminator());
    data.extend_from_slice(&amount_in.to_le_bytes());
    data.extend_from_slice(&min_amount_out.to_le_bytes());
    data.extend_from_slice(&sqrt_limit.to_le_bytes());
    data.push(1u8);                          // amount_specified_is_input = true
    data.push(u8::from(a_to_b));             // a_to_b direction

    // Account metas — orden exacto del IDL Orca Whirlpool swap (11 cuentas)
    let accounts = vec![
        AccountMeta::new_readonly(token_prog,         false), // token_program
        AccountMeta::new_readonly(*user,               true),  // token_authority (signer)
        AccountMeta::new(pool.whirlpool,               false), // whirlpool (writable)
        AccountMeta::new(user_ata_sol,                 false), // token_owner_account_a (wSOL)
        AccountMeta::new(pool.token_vault_a,           false), // token_vault_a
        AccountMeta::new(user_ata_usdc,                false), // token_owner_account_b (USDC)
        AccountMeta::new(pool.token_vault_b,           false), // token_vault_b
        AccountMeta::new(tick_arr_0,                   false), // tick_array_0 (current)
        AccountMeta::new(tick_arr_1,                   false), // tick_array_1 (adjacent in swap direction)
        AccountMeta::new(tick_arr_2,                   false), // tick_array_2 (next adjacent)
        AccountMeta::new(pool.oracle,                  false), // oracle
    ];

    Instruction { program_id, accounts, data }
}

/// Front-run: entra en la misma dirección que la víctima (adelantarnos).
/// probe_lamports si a_to_b (SOL→USDC), probe_microcents si !a_to_b (USDC→SOL).
pub fn build_front_run_ix(
    pool:             &OrcaPoolInfo,
    user:             &Pubkey,
    probe_amount:     u64,
    tick_current:     i32,
    victim_a_to_b:    bool,
) -> Instruction {
    // Front-run va en la MISMA dirección que la víctima para mover el precio antes
    build_swap_ix(pool, user, probe_amount, 0, victim_a_to_b, tick_current)
    // min_amount_out = 0 en el front-run: aceptamos cualquier cantidad (no sabemos exacto)
    // El profit real viene del back-run
}

/// Back-run: invertimos la dirección para cerrar la posición y capturar el spread.
/// min_amount_out calculado con G56: probe × (1 - victim_impact) × 0.999
pub fn build_back_run_ix(
    pool:             &OrcaPoolInfo,
    user:             &Pubkey,
    sol_or_usdc_in:   u64,   // lo que recibimos del front-run
    min_amount_out:   u64,   // precio límite estricto (G56)
    tick_current:     i32,
    victim_a_to_b:    bool,
) -> Instruction {
    // Back-run va en dirección OPUESTA a la víctima (cerramos posición)
    build_swap_ix(pool, user, sol_or_usdc_in, min_amount_out, !victim_a_to_b, tick_current)
}
