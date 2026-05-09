// Loader automático de TickArrays para Orca Whirlpool y Raydium CLMM (advisor 2026-04-29)
// Bug fix: importa FromStr.

use anyhow::Result;
use solana_client::rpc_client::RpcClient;
use solana_sdk::pubkey::Pubkey;
use std::collections::HashMap;
use std::str::FromStr;
use std::time::{Duration, Instant};

use crate::dex::clmm_tick_traversal::{Tick, TickArray};

const ORCA_TICK_ARRAY_SIZE: i32 = 88;
const RAYDIUM_TICK_ARRAY_SIZE: i32 = 60;
const CACHE_TTL: Duration = Duration::from_secs(5);

pub struct TickArrayCache {
    map: HashMap<Pubkey, (Instant, TickArray)>,
}

impl TickArrayCache {
    pub fn new() -> Self { Self { map: HashMap::new() } }
    pub fn get(&self, key: &Pubkey) -> Option<&TickArray> {
        self.map.get(key).filter(|(t,_)| t.elapsed() < CACHE_TTL).map(|(_,v)| v)
    }
    pub fn insert(&mut self, key: Pubkey, val: TickArray) {
        self.map.insert(key, (Instant::now(), val));
    }
}

fn orca_start_tick(tick_current: i32, tick_spacing: i32) -> i32 {
    let span = ORCA_TICK_ARRAY_SIZE * tick_spacing;
    let neg_adjust = if tick_current < 0 && tick_current % span != 0 { 1 } else { 0 };
    (tick_current / span - neg_adjust) * span
}

fn raydium_start_tick(tick_current: i32, tick_spacing: i32) -> i32 {
    let span = RAYDIUM_TICK_ARRAY_SIZE * tick_spacing;
    let neg_adjust = if tick_current < 0 && tick_current % span != 0 { 1 } else { 0 };
    (tick_current / span - neg_adjust) * span
}

fn derive_orca_pda(whirlpool: &Pubkey, start_tick: i32) -> Pubkey {
    let prog = Pubkey::from_str("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc").unwrap();
    let start_str = start_tick.to_string();
    let seeds: &[&[u8]] = &[b"tick_array", whirlpool.as_ref(), start_str.as_bytes()];
    Pubkey::find_program_address(seeds, &prog).0
}

fn derive_raydium_pda(pool: &Pubkey, start_tick: i32) -> Pubkey {
    let prog = Pubkey::from_str("CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK").unwrap();
    let seeds: &[&[u8]] = &[b"tick_array", pool.as_ref(), &start_tick.to_le_bytes()];
    Pubkey::find_program_address(seeds, &prog).0
}

fn parse_orca_tickarray(data: &[u8], start_tick: i32, spacing: i32) -> TickArray {
    let mut ticks = Vec::with_capacity(88);
    let mut offset = 8 + 4 + 32; // discriminator + start_tick_index + whirlpool
    for i in 0..88 {
        let idx = start_tick + i * spacing;
        if offset + 33 > data.len() { break; }
        let initialized = data[offset] != 0;
        offset += 1;
        let liquidity_net = i128::from_le_bytes(data[offset..offset+16].try_into().unwrap_or([0;16]));
        offset += 16;
        offset += 16; // skip liquidity_gross
        offset += 32; // skip fee_growth_outside_a/b (16 bytes c/u)
        if initialized {
            ticks.push(Tick { index: idx, liquidity_net });
        } else {
            ticks.push(Tick { index: idx, liquidity_net: 0 });
        }
    }
    TickArray { ticks }
}

fn parse_raydium_tickarray(data: &[u8], start_tick: i32, spacing: i32) -> TickArray {
    let mut ticks = Vec::with_capacity(60);
    let mut offset = 8 + 32 + 4; // discriminator + pool_id + start_tick_index
    for i in 0..60 {
        let idx = start_tick + i * spacing;
        if offset + 32 > data.len() { break; }
        offset += 4; // tick (i32) — redundante, lo calculamos
        let liquidity_net = i128::from_le_bytes(data[offset..offset+16].try_into().unwrap_or([0;16]));
        offset += 16;
        offset += 16; // skip liquidity_gross
        ticks.push(Tick { index: idx, liquidity_net });
    }
    TickArray { ticks }
}

pub fn load_tickarrays_orca(
    rpc: &RpcClient,
    cache: &mut TickArrayCache,
    whirlpool: Pubkey,
    tick_current: i32,
    tick_spacing: i32,
) -> Result<Vec<TickArray>> {
    let start = orca_start_tick(tick_current, tick_spacing);
    let span = ORCA_TICK_ARRAY_SIZE * tick_spacing;
    let starts = [start - span, start, start + span];
    let pdas: Vec<Pubkey> = starts.iter().map(|s| derive_orca_pda(&whirlpool, *s)).collect();
    let to_fetch: Vec<Pubkey> = pdas.iter().filter(|p| cache.get(p).is_none()).copied().collect();
    if !to_fetch.is_empty() {
        let accs = rpc.get_multiple_accounts(&to_fetch)?;
        for (pda, acc) in to_fetch.iter().zip(accs.into_iter()) {
            let s = starts[pdas.iter().position(|p| p == pda).unwrap()];
            let ta = if let Some(a) = acc { parse_orca_tickarray(&a.data, s, tick_spacing) } else { TickArray { ticks: vec![] } };
            cache.insert(*pda, ta);
        }
    }
    Ok(pdas.iter().filter_map(|p| cache.get(p).cloned()).collect())
}

pub fn load_tickarrays_raydium(
    rpc: &RpcClient,
    cache: &mut TickArrayCache,
    pool: Pubkey,
    tick_current: i32,
    tick_spacing: i32,
) -> Result<Vec<TickArray>> {
    let start = raydium_start_tick(tick_current, tick_spacing);
    let span = RAYDIUM_TICK_ARRAY_SIZE * tick_spacing;
    let starts = [start - span, start, start + span];
    let pdas: Vec<Pubkey> = starts.iter().map(|s| derive_raydium_pda(&pool, *s)).collect();
    let to_fetch: Vec<Pubkey> = pdas.iter().filter(|p| cache.get(p).is_none()).copied().collect();
    if !to_fetch.is_empty() {
        let accs = rpc.get_multiple_accounts(&to_fetch)?;
        for (pda, acc) in to_fetch.iter().zip(accs.into_iter()) {
            let s = starts[pdas.iter().position(|p| p == pda).unwrap()];
            let ta = if let Some(a) = acc { parse_raydium_tickarray(&a.data, s, tick_spacing) } else { TickArray { ticks: vec![] } };
            cache.insert(*pda, ta);
        }
    }
    Ok(pdas.iter().filter_map(|p| cache.get(p).cloned()).collect())
}
