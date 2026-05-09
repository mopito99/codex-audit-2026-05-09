//! Hot wallet keypair loader.
//!
//! Reads WALLET_PRIVATE_KEY (base58 single-string format, same as solana_executor_rs)
//! from .env and exposes a Keypair + Pubkey.

use anyhow::{Context, Result};
use solana_sdk::signature::{Keypair, Signer};
use solana_sdk::pubkey::Pubkey;

pub struct HotWallet {
    pub keypair: Keypair,
    pub pubkey: Pubkey,
}

impl HotWallet {
    pub fn from_env() -> Result<Self> {
        let key_b58 = std::env::var("WALLET_PRIVATE_KEY")
            .or_else(|_| std::env::var("LIQ_WALLET_PRIVATE_KEY"))
            .context("WALLET_PRIVATE_KEY env var missing")?;
        Self::from_base58(&key_b58)
    }

    /// R65 C.3 BLOCKING — load a wallet from an arbitrary env var name. Used
    /// by the cyclic worker to read LIQ_CYCLIC_WALLET_PRIVATE_KEY (isolated
    /// $200 hot wallet) so cyclic execute path NEVER signs with the master
    /// key (blast radius isolation per Gemma R64 B4).
    pub fn from_env_var(var_name: &str) -> Result<Self> {
        let key_b58 = std::env::var(var_name)
            .with_context(|| format!("{var_name} env var missing"))?;
        Self::from_base58(&key_b58)
    }

    fn from_base58(key_b58: &str) -> Result<Self> {
        let bytes = bs58::decode(key_b58.trim())
            .into_vec()
            .context("decode wallet key from base58")?;
        if bytes.len() != 64 {
            anyhow::bail!("expected 64-byte keypair, got {}", bytes.len());
        }
        let keypair = Keypair::from_bytes(&bytes).context("Keypair::from_bytes")?;
        let pubkey = keypair.pubkey();
        Ok(Self { keypair, pubkey })
    }
}

impl std::fmt::Debug for HotWallet {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Never print the private key
        write!(f, "HotWallet(pubkey={})", self.pubkey)
    }
}
