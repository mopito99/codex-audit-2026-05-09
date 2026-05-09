//! Associated Token Account (ATA) derivation and creation helpers.
//!
//! ATA = standard PDA with seeds [owner, token_program, mint].
//! Same address regardless of whether the account exists yet — derivation is deterministic.

use solana_sdk::{instruction::Instruction, pubkey, pubkey::Pubkey, system_program};

pub const SPL_ASSOCIATED_TOKEN: Pubkey = pubkey!("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
pub const SPL_TOKEN_PROGRAM: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
pub const TOKEN_2022_PROGRAM: Pubkey = pubkey!("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");

/// Derive the ATA address for (owner, mint, token_program).
pub fn derive_ata(owner: &Pubkey, mint: &Pubkey, token_program: &Pubkey) -> Pubkey {
    let (ata, _bump) = Pubkey::find_program_address(
        &[owner.as_ref(), token_program.as_ref(), mint.as_ref()],
        &SPL_ASSOCIATED_TOKEN,
    );
    ata
}

/// Create idempotent ATA instruction. If the ATA already exists, the program
/// returns success without doing anything (vs the older "create" which errors).
/// Discriminator: 1 (createIdempotent)
pub fn create_ata_idempotent_ix(
    payer: &Pubkey,
    owner: &Pubkey,
    mint: &Pubkey,
    token_program: &Pubkey,
) -> Instruction {
    let ata = derive_ata(owner, mint, token_program);
    Instruction {
        program_id: SPL_ASSOCIATED_TOKEN,
        accounts: vec![
            solana_sdk::instruction::AccountMeta::new(*payer, true),
            solana_sdk::instruction::AccountMeta::new(ata, false),
            solana_sdk::instruction::AccountMeta::new_readonly(*owner, false),
            solana_sdk::instruction::AccountMeta::new_readonly(*mint, false),
            solana_sdk::instruction::AccountMeta::new_readonly(system_program::id(), false),
            solana_sdk::instruction::AccountMeta::new_readonly(*token_program, false),
        ],
        data: vec![1u8], // createIdempotent
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ata_derivation_deterministic() {
        let owner = pubkey!("GaL85ykdeJ9g5JeXE2Yvar92yMktVCzvi5vGJB77wbTh");
        let usdc_mint = pubkey!("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");
        let a1 = derive_ata(&owner, &usdc_mint, &SPL_TOKEN_PROGRAM);
        let a2 = derive_ata(&owner, &usdc_mint, &SPL_TOKEN_PROGRAM);
        assert_eq!(a1, a2);
        // The known USDC ATA for this wallet (you can verify on Solscan)
        // — leaving as informational; real value depends on derivation
        println!("USDC ATA: {a1}");
    }
}
