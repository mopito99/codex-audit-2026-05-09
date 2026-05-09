// Motor de traversal CLMM exacto (advisor 2026-04-29)
// Para Raydium CLMM y Orca Whirlpool — recorre ticks aplicando liquidity_net.

use anyhow::{anyhow, Result};

#[derive(Clone, Copy, Debug)]
pub struct Tick {
    pub index: i32,
    pub liquidity_net: i128,
}

#[derive(Clone, Debug)]
pub struct TickArray {
    pub ticks: Vec<Tick>,
}

#[derive(Clone, Copy, Debug)]
pub struct PoolState {
    pub sqrt_price_x64: u128,
    pub liquidity: u128,
    pub tick_current: i32,
    pub tick_spacing: i32,
}

#[derive(Debug)]
pub struct SwapResult {
    pub amount_out: f64,
    pub final_price: f64,
    pub crossed_ticks: u32,
}

fn sqrt_price_from_tick(tick: i32) -> f64 {
    1.0001_f64.powi(tick / 2)  // sqrt(1.0001^tick) = 1.0001^(tick/2)
}

pub fn simulate_clmm_swap(
    pool: PoolState,
    tick_arrays: &[TickArray],
    mut amount_in: f64,
    buy: bool,
) -> Result<SwapResult> {
    let mut sqrt_p = (pool.sqrt_price_x64 as f64) / (1u128 << 64) as f64;
    let mut liquidity = pool.liquidity as f64;
    let mut tick = pool.tick_current;
    let mut out = 0.0;
    let mut crossed = 0u32;

    for _ in 0..100 {  // máx 100 ticks por seguridad
        if amount_in <= 0.0 || liquidity <= 0.0 { break; }

        let next_tick = if buy { tick + pool.tick_spacing } else { tick - pool.tick_spacing };
        let sqrt_target = sqrt_price_from_tick(next_tick);

        let (dx_to_next, dy_to_next) = if buy {
            let dx = liquidity * (1.0/sqrt_target - 1.0/sqrt_p).abs();
            let dy = liquidity * (sqrt_target - sqrt_p).abs();
            (dx, dy)
        } else {
            let dx = liquidity * (1.0/sqrt_p - 1.0/sqrt_target).abs();
            let dy = liquidity * (sqrt_p - sqrt_target).abs();
            (dx, dy)
        };

        if amount_in < dx_to_next {
            // No cruzamos tick — partial fill
            let inv_old = 1.0 / sqrt_p;
            let sqrt_new = if buy {
                let inv_new = inv_old - (amount_in / liquidity);
                if inv_new <= 0.0 { return Err(anyhow!("trade too large")); }
                1.0 / inv_new
            } else {
                let s = sqrt_p - (amount_in / liquidity);
                if s <= 0.0 { return Err(anyhow!("trade too large")); }
                s
            };
            let dy_partial = liquidity * (sqrt_new - sqrt_p).abs();
            out += dy_partial;
            sqrt_p = sqrt_new;
            break;
        }

        // Cruzamos tick completo
        amount_in -= dx_to_next;
        out += dy_to_next;
        sqrt_p = sqrt_target;
        tick = next_tick;
        crossed += 1;

        // Aplicar liquidity_net del tick cruzado
        for arr in tick_arrays {
            for t in &arr.ticks {
                if t.index == tick {
                    if buy {
                        liquidity = (liquidity + t.liquidity_net as f64).max(0.0);
                    } else {
                        liquidity = (liquidity - t.liquidity_net as f64).max(0.0);
                    }
                }
            }
        }
    }

    Ok(SwapResult {
        amount_out: out,
        final_price: sqrt_p * sqrt_p,
        crossed_ticks: crossed,
    })
}
