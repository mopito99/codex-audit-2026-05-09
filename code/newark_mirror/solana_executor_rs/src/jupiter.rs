// Cliente HTTP de Jupiter lite-api para quotes y swap tx.
// JupiterQuote = serde_json::Value crudo. Así reenviamos byte-por-byte al swap endpoint
// y Jupiter no se queja por campos faltantes.

use crate::config::{decimals, JUPITER_QUOTE_URL, JUPITER_SWAP_URL, USDC};
use anyhow::{anyhow, Result};
use serde::Serialize;
use serde_json::Value;

pub type JupiterQuote = Value;

pub fn out_amount(q: &JupiterQuote) -> u64 {
    q.get("outAmount")
     .and_then(|v| v.as_str())
     .and_then(|s| s.parse().ok())
     .unwrap_or(0)
}

pub fn dexes_from_quote(q: &JupiterQuote) -> Vec<String> {
    q.get("routePlan")
     .and_then(|v| v.as_array())
     .map(|arr| arr.iter()
        .filter_map(|hop| hop.pointer("/swapInfo/label").and_then(|v| v.as_str()).map(String::from))
        .collect())
     .unwrap_or_default()
}

#[derive(Debug, Clone, Serialize)]
struct SwapRequest<'a> {
    #[serde(rename = "quoteResponse")] quote_response: &'a JupiterQuote,
    #[serde(rename = "userPublicKey")] user_public_key: &'a str,
    #[serde(rename = "wrapAndUnwrapSol")] wrap_and_unwrap_sol: bool,
    #[serde(rename = "dynamicComputeUnitLimit")] dynamic_compute_unit_limit: bool,
    #[serde(rename = "prioritizationFeeLamports")] prioritization_fee_lamports: u64,
}

pub fn to_atomic(amount: f64, mint: &str) -> u64 {
    (amount * 10f64.powi(decimals(mint) as i32)).floor() as u64
}

pub fn to_human(amount_atomic: u64, mint: &str) -> f64 {
    amount_atomic as f64 / 10f64.powi(decimals(mint) as i32)
}

#[derive(Debug)]
pub enum QuoteResult {
    Ok(JupiterQuote),
    NoRoute,
    ApiError,
}

pub async fn get_quote(
    client: &reqwest::Client,
    input_mint: &str,
    output_mint: &str,
    amount_atomic: u64,
    exclude_dexes: Option<&[String]>,
    slippage_bps: u32,
) -> QuoteResult {
    let mut url = format!(
        "{JUPITER_QUOTE_URL}?inputMint={input_mint}&outputMint={output_mint}&amount={amount_atomic}&slippageBps={slippage_bps}&onlyDirectRoutes=false"
    );
    if let Some(dexes) = exclude_dexes {
        if !dexes.is_empty() {
            url.push_str("&excludeDexes=");
            url.push_str(&dexes.join(","));
        }
    }

    for attempt in 0..3 {
        match client.get(&url).send().await {
            Ok(res) => {
                let status = res.status();
                if status.as_u16() == 429 {
                    tokio::time::sleep(std::time::Duration::from_millis(1000 * 2u64.pow(attempt))).await;
                    continue;
                }
                if status.as_u16() == 400 { return QuoteResult::NoRoute; }
                if !status.is_success() { return QuoteResult::ApiError; }
                match res.json::<Value>().await {
                    Ok(v) if v.get("outAmount").is_some() => return QuoteResult::Ok(v),
                    Ok(_) => return QuoteResult::NoRoute,
                    Err(_) => { if attempt == 2 { return QuoteResult::ApiError; } }
                }
            }
            Err(_) => { if attempt == 2 { return QuoteResult::ApiError; } }
        }
    }
    QuoteResult::ApiError
}

#[derive(Debug, Clone, serde::Deserialize)]
struct SwapResponse { #[serde(rename = "swapTransaction")] swap_transaction: String }

pub async fn get_swap_transaction(
    client: &reqwest::Client,
    quote: &JupiterQuote,
    user_pubkey: &str,
) -> Result<String> {
    let req = SwapRequest {
        quote_response: quote,
        user_public_key: user_pubkey,
        wrap_and_unwrap_sol: true,
        dynamic_compute_unit_limit: true,
        prioritization_fee_lamports: 0,
    };
    let res = client.post(JUPITER_SWAP_URL).json(&req).send().await?;
    let status = res.status();
    let text = res.text().await?;
    if !status.is_success() {
        eprintln!("    [jupiter swap] HTTP {} body: {}", status, &text[..text.len().min(300)]);
        return Err(anyhow!("swap http {}", status));
    }
    match serde_json::from_str::<SwapResponse>(&text) {
        Ok(body) => Ok(body.swap_transaction),
        Err(e) => {
            eprintln!("    [jupiter swap] parse error: {} body: {}", e, &text[..text.len().min(300)]);
            Err(anyhow!("swap parse: {}", e))
        }
    }
}

#[derive(Debug, Clone)]
pub struct CyclicArb {
    pub intermediate: String,
    pub input_usdc: f64,
    pub output_usdc: f64,
    pub gross_profit: f64,
    pub net_profit: f64,
    pub profit_bps: f64,
    pub leg1_dexes: Vec<String>,
    pub leg2_dexes: Vec<String>,
    pub leg1_quote: JupiterQuote,
    pub leg2_quote: JupiterQuote,
}

pub enum ArbResult {
    Ok(CyclicArb),
    NoProfit(CyclicArb),
    NoRoute,
    ApiError,
}

pub async fn find_cyclic_arb(
    client: &reqwest::Client,
    intermediate_mint: &str,
    probe_usdc: f64,
    total_cost_usdc: f64,
    slippage_bps: u32,
) -> ArbResult {
    let in_atomic = to_atomic(probe_usdc, USDC);

    let r1 = get_quote(client, USDC, intermediate_mint, in_atomic, None, slippage_bps).await;
    let leg1 = match r1 {
        QuoteResult::Ok(q) => q,
        QuoteResult::NoRoute => return ArbResult::NoRoute,
        QuoteResult::ApiError => return ArbResult::ApiError,
    };

    let leg1_dexes = dexes_from_quote(&leg1);
    let mid_atomic: u64 = out_amount(&leg1);
    if mid_atomic == 0 { return ArbResult::NoRoute; }

    let r2 = get_quote(client, intermediate_mint, USDC, mid_atomic, Some(&leg1_dexes), slippage_bps).await;
    let leg2 = match r2 {
        QuoteResult::Ok(q) => q,
        QuoteResult::NoRoute => return ArbResult::NoRoute,
        QuoteResult::ApiError => return ArbResult::ApiError,
    };
    let leg2_dexes = dexes_from_quote(&leg2);
    let out_atomic: u64 = out_amount(&leg2);

    let output_usdc = to_human(out_atomic, USDC);
    let gross = output_usdc - probe_usdc;
    let net = gross - total_cost_usdc;
    let bps = if probe_usdc > 0.0 { gross / probe_usdc * 10_000.0 } else { 0.0 };

    let arb = CyclicArb {
        intermediate: intermediate_mint.to_string(),
        input_usdc: probe_usdc,
        output_usdc,
        gross_profit: gross,
        net_profit: net,
        profit_bps: bps,
        leg1_dexes, leg2_dexes,
        leg1_quote: leg1, leg2_quote: leg2,
    };
    if gross > 0.0 { ArbResult::Ok(arb) } else { ArbResult::NoProfit(arb) }
}
