// Decodifica cuentas de Orca Whirlpool y Raydium CLMM para extraer precio spot.
// No requiere RPC calls adicionales — usa los datos de cuenta crudos.
//
// Offset map verificado contra los logs de Newark (orca_price ~83, raydium_price ~83):
//   Orca Whirlpool  sqrt_price (u128 LE) → offset 65  (8 disc + 32 config + 1 bump + 2+2+2+2 = 49 → +16 liq = 65)
//   Raydium CLMM   sqrt_price_x64 (u128 LE) → offset 252 (8 disc + 7×32 + 1+1+2 + 16 liq = 252)

use std::time::Instant;

pub const ORCA_SOL_USDC:    &str = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE";
pub const RAYDIUM_SOL_USDC: &str = "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj";

// Offsets en el account data
const ORCA_SQRT_PRICE_OFFSET:    usize = 65;
const RAYDIUM_SQRT_PRICE_OFFSET: usize = 253;

// Orca fee_rate está en offset 45 como u16 (millonésimas: 300 = 0.03%)
const ORCA_FEE_RATE_OFFSET: usize = 45;
// Raydium CLMM fee está en el AmmConfig, no en el PoolState.
// Usamos el fee conocido del pool SOL/USDC de Raydium: 25 bps (0.0025)
const RAYDIUM_FEE_RATE_BPS: f64 = 25.0;

/// Pool SOL/USDC con token_a=SOL(9dec), token_b=USDC(6dec).
/// price_human = price_atomic × 10^(decimals_a - decimals_b) = price_atomic × 1000
const DECIMAL_ADJUSTMENT: f64 = 1_000.0; // 10^(9-6)

#[derive(Clone, Debug)]
pub struct PoolPrices {
    pub orca: f64,
    pub raydium: f64,
    pub updated_at: Instant,
}

impl PoolPrices {
    pub fn is_fresh(&self, max_age_ms: u64) -> bool {
        self.updated_at.elapsed().as_millis() < max_age_ms as u128
    }

    pub fn gap_pct(&self) -> f64 {
        let mid = (self.orca + self.raydium) / 2.0;
        if mid == 0.0 { return 0.0; }
        (self.orca - self.raydium).abs() / mid
    }

    /// Si Orca > Raydium: comprar SOL barato en Raydium, vender en Orca.
    /// Retorna (cheap_dex, expensive_dex, cheap_price, expensive_price).
    pub fn direction(&self) -> (&'static str, &'static str, f64, f64) {
        if self.orca >= self.raydium {
            ("Raydium", "Orca", self.raydium, self.orca)
        } else {
            ("Orca", "Raydium", self.orca, self.raydium)
        }
    }
}

fn read_u128_le(data: &[u8], offset: usize) -> Option<u128> {
    if data.len() < offset + 16 { return None; }
    let bytes: [u8; 16] = data[offset..offset + 16].try_into().ok()?;
    Some(u128::from_le_bytes(bytes))
}

fn read_u16_le(data: &[u8], offset: usize) -> Option<u16> {
    if data.len() < offset + 2 { return None; }
    let bytes: [u8; 2] = data[offset..offset + 2].try_into().ok()?;
    Some(u16::from_le_bytes(bytes))
}

/// Precio USDC/SOL desde cuenta Orca Whirlpool (token_a=SOL, token_b=USDC).
pub fn decode_orca_price(data: &[u8]) -> Option<f64> {
    let sqrt_x64 = read_u128_le(data, ORCA_SQRT_PRICE_OFFSET)?;
    if sqrt_x64 == 0 { return None; }
    let sqrt_p = sqrt_x64 as f64 / (1u128 << 64) as f64;
    let price_atomic = sqrt_p * sqrt_p;
    let fee_millionths = read_u16_le(data, ORCA_FEE_RATE_OFFSET).unwrap_or(300) as f64;
    let fee_factor = 1.0 - fee_millionths / 1_000_000.0;
    Some(price_atomic * DECIMAL_ADJUSTMENT * fee_factor)
}

/// Precio USDC/SOL desde cuenta Raydium CLMM PoolState (token_0=SOL, token_1=USDC).
pub fn decode_raydium_price(data: &[u8]) -> Option<f64> {
    let sqrt_x64 = read_u128_le(data, RAYDIUM_SQRT_PRICE_OFFSET)?;
    if sqrt_x64 == 0 { return None; }
    let sqrt_p = sqrt_x64 as f64 / (1u128 << 64) as f64;
    let price_atomic = sqrt_p * sqrt_p;
    let fee_factor = 1.0 - RAYDIUM_FEE_RATE_BPS / 10_000.0;
    Some(price_atomic * DECIMAL_ADJUSTMENT * fee_factor)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sqrt_price_round_trip() {
        // SOL ~$83, price_atomic = 83/1000 = 0.083
        // sqrt_price = sqrt(0.083) ≈ 0.28809, sqrt_x64 ≈ 5.32e18
        let price_target = 83.0_f64;
        let price_atomic = price_target / 1000.0;
        let sqrt_p = price_atomic.sqrt();
        let sqrt_x64 = (sqrt_p * (1u128 << 64) as f64) as u128;
        let mut data = vec![0u8; 256];
        data[ORCA_SQRT_PRICE_OFFSET..ORCA_SQRT_PRICE_OFFSET + 16]
            .copy_from_slice(&sqrt_x64.to_le_bytes());
        // fee_rate = 300 (0.03%)
        data[ORCA_FEE_RATE_OFFSET..ORCA_FEE_RATE_OFFSET + 2]
            .copy_from_slice(&300u16.to_le_bytes());
        let decoded = decode_orca_price(&data).unwrap();
        // Con fee 0.03%: precio efectivo = 83 * (1 - 0.0003) ≈ 82.975
        assert!((decoded - 82.975).abs() < 0.01, "got {decoded}");
    }
}
