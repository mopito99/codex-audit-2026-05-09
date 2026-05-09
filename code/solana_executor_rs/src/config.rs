#![allow(dead_code)] // Constantes/funciones para Phase 2 LIVE (sandwich y cyclic activos)
// Constantes y carga de .env. Espejo de src/config.ts del bot Node.

pub const USDC: &str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
pub const SOL:  &str = "So11111111111111111111111111111111111111112";
pub const JUP:  &str = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN";

pub const JUPITER_QUOTE_URL: &str = "https://lite-api.jup.ag/swap/v1/quote";
pub const JUPITER_SWAP_URL:  &str = "https://lite-api.jup.ag/swap/v1/swap";

// Jito block engine endpoints — solo NY (G3: EU añade 150-200ms extra desde Newark)
pub const JITO_ENDPOINTS: &[&str] = &[
    "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
];

// Jito tip accounts oficiales (verificadas 2026-04-28)
pub const JITO_TIP_ACCOUNTS: &[&str] = &[
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
];

// Programas DEX a escuchar via WebSocket
pub const WATCH_PROGRAMS: &[&str] = &[
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc", // Orca Whirlpool
    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP", // Orca v2
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", // Raydium AMM v4
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK", // Raydium CLMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  // Meteora DLMM
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",  // Phoenix
];

pub fn decimals(mint: &str) -> u8 {
    match mint {
        USDC => 6,
        SOL => 9,
        JUP => 6,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB" => 6, // USDT
        _ => 6,
    }
}

pub fn name_for(mint: &str) -> &'static str {
    match mint {
        USDC => "USDC",
        SOL => "SOL",
        JUP => "JUP",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB" => "USDT",
        _ => "?",
    }
}

// Pares a escanear: (intermediate_mint, [probe_amounts_USDC])
// Tier para $1000 capital: probes $500 y $900 (deja $100 buffer fees)
pub fn scan_pairs() -> Vec<(&'static str, Vec<f64>)> {
    vec![
        (SOL, vec![500.0, 900.0]),
        (JUP, vec![500.0, 900.0]),
    ]
}

// Slippage por tier (bps)
pub fn tier_slippage_bps(mint: &str) -> u32 {
    match mint {
        SOL | "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB" | JUP => 15, // tier 1
        _ => 50,
    }
}

pub const SLIPPAGE_BPS_DEFAULT: u32 = 50;
pub const MIN_PROFIT_USDC: f64 = 0.05;
pub const MIN_PROFIT_BPS:  f64 = 0.5; // bajado: a probes $500-$2000 los bps típicos son 1-2. El filtro absoluto $0.05 ya garantiza rentabilidad real.
pub const POLL_INTERVAL_MS: u64 = 500;

// Kill-switch Fase 1: si la sesión pierde más de este importe, pausar 1h
pub const MAX_SESSION_LOSS_USDC: f64 = 50.0;
// Probe conservador para Fase 1 (primeros 10 bundles reales)
pub const FASE1_PROBE_USDC: f64 = 100.0;
// LOG_DIR: path absoluto en cada máquina. El sync to Dallas lo gestiona el systemd timer.
pub fn log_dir() -> String {
    std::env::var("LOG_DIR").unwrap_or_else(|_| "./data".to_string())
}
pub const LOG_DIR: &str = "./data"; // fallback compat

#[derive(Clone)]
pub struct EnvCfg {
    pub helius_api_key: String,
    pub helius_rpc: String,
    pub helius_wss: String,
    pub helius_gatekeeper: String,
    pub wallet_private_key: Option<String>,
    pub paper_mode: bool,
    pub jito_tip_lamports: u64,
    pub sol_price_usd: f64,
    // Ventana horaria LIVE (UTC fraccional, e.g. 17.5 = 17:30). None = 24h.
    pub live_hours_start: Option<f64>,
    pub live_hours_end: Option<f64>,
    // Segunda ventana (e.g. 3.0-5.0 UTC para sesión asiática, G10). None = inactiva.
    pub live_hours_start2: Option<f64>,
    pub live_hours_end2: Option<f64>,
    // Multiplicador de tip según hora UTC (G25). Cargado desde JITO_TIP_MULTIPLIER_PEAK/ASIA.
    pub tip_multiplier_peak: f64,  // 17-20h UTC (alta competencia)
    pub tip_multiplier_asia: f64,  // 03-05h UTC (apertura Asia)
    // Chainstack Yellowstone gRPC (G27)
    pub chainstack_grpc_url: String,   // e.g. "https://solana-mainnet.core.chainstack.com:2053"
    pub chainstack_grpc_token: String, // x-token header value
}

impl EnvCfg {
    pub fn load() -> Self {
        // Intenta varios paths comunes en orden de prioridad
        for p in &[
            ".env",
            "/opt/solana_executor_rs/.env",
            "/home/ubuntu/solana_executor_rs/.env",
            "/home/administrator/solana_executor/.env",
        ] {
            if dotenvy::from_path(p).is_ok() { break; }
        }

        let helius_api_key = std::env::var("HELIUS_API_KEY").unwrap_or_default();
        let paper_mode = std::env::var("PAPER_MODE").unwrap_or_else(|_| "true".into()) != "false";
        let jito_tip_lamports = std::env::var("JITO_TIP_LAMPORTS")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(100_000);
        let sol_price_usd = std::env::var("SOL_PRICE_USD")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(175.0);
        let wallet_private_key = std::env::var("WALLET_PRIVATE_KEY").ok().filter(|s| !s.is_empty());

        let live_hours_start  = std::env::var("LIVE_HOURS_START").ok().and_then(|s| s.parse().ok());
        let live_hours_end    = std::env::var("LIVE_HOURS_END").ok().and_then(|s| s.parse().ok());
        let live_hours_start2 = std::env::var("LIVE_HOURS_START2").ok().and_then(|s| s.parse().ok());
        let live_hours_end2   = std::env::var("LIVE_HOURS_END2").ok().and_then(|s| s.parse().ok());
        let tip_multiplier_peak = std::env::var("JITO_TIP_MULT_PEAK")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(1.8);
        let tip_multiplier_asia = std::env::var("JITO_TIP_MULT_ASIA")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(1.3);

        // Chainstack endpoints (reemplazan Helius para RPC + WSS + gRPC)
        // Formato: CHAINSTACK_RPC_URL=https://solana-mainnet.core.chainstack.com/XXXX
        //          CHAINSTACK_WSS_URL=wss://solana-mainnet.core.chainstack.com/XXXX
        //          CHAINSTACK_GRPC_URL=https://solana-mainnet.core.chainstack.com:2053
        let chainstack_rpc = std::env::var("CHAINSTACK_RPC_URL").ok();
        let chainstack_wss = std::env::var("CHAINSTACK_WSS_URL").ok();
        let chainstack_grpc_url = std::env::var("CHAINSTACK_GRPC_URL")
            .unwrap_or_else(|_| "https://solana-mainnet.core.chainstack.com:2053".to_string());
        let chainstack_grpc_token = std::env::var("CHAINSTACK_GRPC_TOKEN").unwrap_or_default();

        // RPC activo: Chainstack si está configurado, Helius como fallback
        let rpc_url = chainstack_rpc.clone().unwrap_or_else(||
            format!("https://mainnet.helius-rpc.com/?api-key={helius_api_key}"));
        let wss_url = chainstack_wss.clone().unwrap_or_else(||
            format!("wss://mainnet.helius-rpc.com/?api-key={helius_api_key}"));

        Self {
            helius_rpc: rpc_url.clone(),
            helius_wss: wss_url,
            helius_gatekeeper: rpc_url,  // usar mismo endpoint para tx de keypair
            helius_api_key,
            wallet_private_key,
            paper_mode,
            jito_tip_lamports,
            sol_price_usd,
            live_hours_start,
            live_hours_end,
            live_hours_start2,
            live_hours_end2,
            tip_multiplier_peak,
            tip_multiplier_asia,
            chainstack_grpc_url,
            chainstack_grpc_token,
        }
    }
}
