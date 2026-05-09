#![allow(dead_code)] // Phase 2 LIVE — TODO completar sign+send Jupiter
// SafetyWorker — emergency exit si la wallet queda con token tóxico (G73, G78).
//
// Diseño: red de defensa secundaria. La atomicidad de Jito ya previene 99% de casos,
// pero un bug en min_amount_out_back podría devolvernos token inesperado.
//
// Workflow:
//   1. Cada 60s: scan token balances de hot_wallet
//   2. Si encuentra mint NO en whitelist con balance > 0:
//      - Llama Jupiter /v6/quote con slippageBps=1000 (10%)
//      - Llama Jupiter /v6/swap, deserializa, firma, envía
//   3. Si Jupiter retorna no_route: trigger pause_signal + alert Telegram CRITICAL
//
// Generado a partir de respuesta Gemma I2.
// TODO: completar antes de uso productivo:
//   - Manejo correcto de signature en solana-sdk 2.0 (sign API cambió)
//   - Telegram alerts integration
//   - tokens_to_avoid HashSet persistente
//   - Fallback Raydium directo si Jupiter no_route

use anyhow::{anyhow, Result};
use reqwest::Client;
use serde_json::Value;
use solana_client::rpc_client::RpcClient;
use solana_sdk::{pubkey::Pubkey, signature::Keypair, signer::Signer};
use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::time::{sleep, Duration};

pub struct SafetyWorker {
    pub hot_wallet: Arc<Keypair>,
    pub rpc: Arc<RpcClient>,
    pub http: Arc<Client>,
    pub whitelist: HashSet<Pubkey>,
    pub pause_signal: Arc<AtomicBool>,
}

impl SafetyWorker {
    pub fn new(
        hot_wallet: Arc<Keypair>,
        rpc: Arc<RpcClient>,
        whitelist: HashSet<Pubkey>,
        pause_signal: Arc<AtomicBool>,
    ) -> Self {
        Self {
            hot_wallet,
            rpc,
            http: Arc::new(Client::new()),
            whitelist,
            pause_signal,
        }
    }

    /// Main loop: chequeo periódico cada 60s.
    pub async fn run(&self) -> Result<()> {
        loop {
            sleep(Duration::from_secs(60)).await;
            if let Err(e) = self.check_and_liquidate().await {
                eprintln!("[safety_worker] error: {e}");
            }
        }
    }

    /// Trigger event-driven (G73): llamado después de cada bundle confirmado.
    pub async fn check_now(&self) -> Result<()> {
        self.check_and_liquidate().await
    }

    async fn check_and_liquidate(&self) -> Result<()> {
        // TODO: implementar get_token_accounts_by_owner correctamente con solana-client 2.0
        // Stub temporal — devolver Ok(()) hasta integración real
        Ok(())
    }

    /// Emergency sell vía Jupiter v6 con slippage 10%.
    /// Output: token → USDC (objetivo: recuperar capital, no maximizar precio).
    async fn emergency_sell(&self, mint: Pubkey, amount: u64) -> Result<String> {
        const USDC_MINT: &str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

        // 1. Quote
        let quote_url = format!(
            "https://quote-api.jup.ag/v6/quote?inputMint={mint}&outputMint={USDC_MINT}\
             &amount={amount}&slippageBps=1000"
        );
        let quote: Value = self.http.get(&quote_url).send().await?.json().await?;

        if quote.get("error").is_some() {
            // No route → token rugged completo
            self.pause_signal.store(true, Ordering::SeqCst);
            return Err(anyhow!(
                "Jupiter no_route for mint {mint}: {}",
                quote.get("error").unwrap()
            ));
        }

        // 2. Swap transaction
        let swap_payload = serde_json::json!({
            "quoteResponse": quote,
            "userPublicKey": self.hot_wallet.pubkey().to_string(),
            "wrapAndUnwrapSol": true,
        });
        let swap_resp: Value = self
            .http
            .post("https://quote-api.jup.ag/v6/swap")
            .json(&swap_payload)
            .send()
            .await?
            .json()
            .await?;

        let _tx_base64 = swap_resp["swapTransaction"]
            .as_str()
            .ok_or_else(|| anyhow!("Jupiter swap returned no swapTransaction"))?;

        // TODO: deserialize + sign + send con API correcta solana-sdk 2.0
        // El código de Gemma usa tx.sign() que cambió en 2.0 — fix durante integración

        Err(anyhow!("emergency_sell: integración firma TODO"))
    }
}
