// local_quote.rs — Quote de arb cíclico SOL/USDC sin llamada HTTP a Jupiter.
//
// Usa PoolPriceState (ya en cache desde accountSubscribe) + simulate_clmm_swap
// para calcular si USDC→SOL→USDC es rentable en <1ms.
//
// Limitación: válido solo para el par SOL/USDC (Orca+Raydium en cache).
// Para otros pares (jitoSOL, mSOL, etc.) seguir usando Jupiter API como fallback.
//
// NO construye transacciones — solo calcula el profit para decidir si intentar.
// La construcción de TX sigue pasando por Jupiter swap API (get_swap_transaction).

use crate::dex::clmm_tick_traversal::{simulate_clmm_swap, PoolState, TickArray};
use crate::state_engine::PoolPriceState;

#[derive(Debug)]
pub struct LocalArb {
    pub input_usdc:   f64,
    pub gross_profit: f64,
    pub net_profit:   f64,
    pub profit_bps:   f64,
    pub buy_on_orca:  bool,   // true = comprar SOL en Orca, vender en Raydium
}

/// Calcula arb SOL/USDC usando los precios del cache local.
/// Retorna None si la diferencia de precio no cubre costos.
pub fn quote_sol_usdc(
    orca: &PoolPriceState,
    raydium: &PoolPriceState,
    input_usdc: f64,
    total_cost_usdc: f64,
) -> Option<LocalArb> {
    // Determinar dirección: comprar en el DEX más barato
    let buy_on_orca = orca.price < raydium.price;
    let (cheap, expensive) = if buy_on_orca {
        (orca, raydium)
    } else {
        (raydium, orca)
    };

    let gap_pct = (expensive.price - cheap.price) / cheap.price;
    if gap_pct <= 0.0 { return None; }

    // Estimate con PoolState del tick actual (sin cruzar ticks — aproximación rápida)
    // Para probe sizes de $1000-$2000, SOL/USDC CLMM rara vez cruza un tick.
    let pool_cheap = PoolState {
        sqrt_price_x64: cheap.sqrt_price_x64,
        liquidity:      cheap.liquidity,
        tick_current:   cheap.tick_current,
        tick_spacing:   cheap.tick_spacing,
    };

    // Leg 1: USDC → SOL en el DEX barato
    let empty_arrays: &[TickArray] = &[];
    let leg1 = simulate_clmm_swap(pool_cheap, empty_arrays, input_usdc, true).ok()?;
    let sol_received = leg1.amount_out;

    // Leg 2: SOL → USDC en el DEX caro
    let pool_exp = PoolState {
        sqrt_price_x64: expensive.sqrt_price_x64,
        liquidity:      expensive.liquidity,
        tick_current:   expensive.tick_current,
        tick_spacing:   expensive.tick_spacing,
    };
    let leg2 = simulate_clmm_swap(pool_exp, empty_arrays, sol_received, false).ok()?;
    let usdc_out = leg2.amount_out;

    let gross = usdc_out - input_usdc;
    let net   = gross - total_cost_usdc;
    let bps   = (gross / input_usdc) * 10_000.0;

    if net <= 0.0 { return None; }

    Some(LocalArb {
        input_usdc,
        gross_profit: gross,
        net_profit:   net,
        profit_bps:   bps,
        buy_on_orca,
    })
}
