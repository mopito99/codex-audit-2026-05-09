//! Wallet query helper para SafetyWorker (R62 wire-up).
//!
//! HTTP JSON-RPC `getTokenAccountsByOwner` — devuelve todos los SPL token
//! accounts de una wallet. Usado por SafetyWorker en background scan
//! cada 60s (no hot path).
//!
//! NO usa gRPC porque:
//!   - Frequency 60s makes streaming overkill
//!   - Subscribir 1 wallet via Yellowstone consume slot del stream existente
//!   - Per Principio #1 R62: SafetyWorker NO está en hot path → HTTP es fine
//!
//! Pricing USD:
//!   Sin Pyth integration aún, este módulo retorna `estimated_value_usd = 0.0`.
//!   El SafetyWorker.decide_action() ignora tokens con value < min_value_usd.
//!   Cuando PythCache esté funcional con 100+ tokens, el caller puede
//!   computar value usando token mint → Pyth feed map. Por ahora, fallback
//!   conservador: tratar todo token NO whitelist como sospechoso (caller decide).

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use solana_sdk::pubkey::Pubkey;

#[derive(Debug, Deserialize)]
struct RpcResponse<T> {
    result: T,
}

#[derive(Debug, Deserialize)]
struct GetTokenAccountsResponse {
    value: Vec<TokenAccountEntry>,
}

#[derive(Debug, Deserialize)]
struct TokenAccountEntry {
    account: TokenAccountInfo,
}

#[derive(Debug, Deserialize)]
struct TokenAccountInfo {
    data: ParsedTokenData,
}

#[derive(Debug, Deserialize)]
struct ParsedTokenData {
    parsed: ParsedTokenContent,
}

#[derive(Debug, Deserialize)]
struct ParsedTokenContent {
    info: TokenAccountFields,
}

#[derive(Debug, Deserialize)]
struct TokenAccountFields {
    mint: String,
    #[serde(rename = "tokenAmount")]
    token_amount: TokenAmount,
}

#[derive(Debug, Deserialize)]
struct TokenAmount {
    amount: String,
    decimals: u8,
    #[serde(rename = "uiAmount")]
    ui_amount: Option<f64>,
}

/// Token program (SPL classic) — se usa como filtro programId del query.
pub const SPL_TOKEN_PROGRAM: &str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";

/// Fetch token accounts owned by `wallet`.
///
/// Para cada cuenta retorna mint + balance + decimals. Estimated value USD
/// no se calcula aquí — es responsabilidad del caller (consultar PythCache).
///
/// Retorna Vec<WalletToken> compatible con SafetyWorker.
pub async fn fetch_wallet_tokens(
    rpc_url: &str,
    wallet: &Pubkey,
) -> Result<Vec<liquidator_rs_wallet_token::WalletToken>> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()?;

    let body = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet.to_string(),
            { "programId": SPL_TOKEN_PROGRAM },
            { "encoding": "jsonParsed", "commitment": "confirmed" }
        ]
    });

    let resp = client
        .post(rpc_url)
        .json(&body)
        .send()
        .await
        .context("rpc post getTokenAccountsByOwner")?;

    if !resp.status().is_success() {
        return Err(anyhow!("getTokenAccountsByOwner status {}", resp.status()));
    }

    let parsed: RpcResponse<GetTokenAccountsResponse> = resp
        .json()
        .await
        .context("parse getTokenAccountsByOwner response")?;

    let mut out = Vec::with_capacity(parsed.result.value.len());
    for entry in parsed.result.value {
        let fields = entry.account.data.parsed.info;
        let mint = match fields.mint.parse::<Pubkey>() {
            Ok(p) => p,
            Err(_) => continue,
        };
        let amount: u64 = fields.token_amount.amount.parse().unwrap_or(0);
        if amount == 0 {
            continue; // skip empty token accounts
        }
        out.push(liquidator_rs_wallet_token::WalletToken {
            mint,
            balance_raw: amount,
            decimals: fields.token_amount.decimals,
            ui_amount: fields.token_amount.ui_amount.unwrap_or(0.0),
            // estimated_value_usd = 0.0 hasta que PythCache pueda valorar.
            // SafetyWorker tratará todo token no-whitelist con value 0 como
            // dust → ignore (sub-threshold). Esto es FAIL-OPEN por defecto.
            // Mejora futura: caller pasa PythCache + mint→feed map y aquí
            // se computa value real.
            estimated_value_usd: 0.0,
        });
    }
    Ok(out)
}

/// Variant que enriquece value usando price hint mint→USD.
/// Si el mint no está en `price_map`, value=0 (caller decide tratar como dust).
pub async fn fetch_wallet_tokens_priced(
    rpc_url: &str,
    wallet: &Pubkey,
    price_map: &std::collections::HashMap<Pubkey, f64>,
) -> Result<Vec<liquidator_rs_wallet_token::WalletToken>> {
    let mut tokens = fetch_wallet_tokens(rpc_url, wallet).await?;
    for t in tokens.iter_mut() {
        if let Some(price_usd) = price_map.get(&t.mint) {
            t.estimated_value_usd = t.ui_amount * price_usd;
        }
    }
    Ok(tokens)
}

// Re-export tipo desde safety_worker para evitar dependencia cíclica.
mod liquidator_rs_wallet_token {
    pub use crate::safety_worker::WalletToken;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_module_compiles() {
        // Solo smoke test — el fetch real requiere RPC live.
        // Si este test corre, los types compilan y las imports están bien.
        let _: &str = SPL_TOKEN_PROGRAM;
        assert!(SPL_TOKEN_PROGRAM.starts_with("Tokenkeg"));
    }
}
