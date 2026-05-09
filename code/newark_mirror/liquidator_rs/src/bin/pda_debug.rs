//! PDA debug: print all candidate seeds for obligation_farm_user_state
use solana_sdk::pubkey::Pubkey;
use solana_sdk::pubkey;
use std::str::FromStr;

fn main() {
    let farms_program = pubkey!("FarmsPZpWu9i7Kky8tPN37rs2TpmMrSpvw3DCyKqaWa");
    let farm_state = Pubkey::from_str("B7nzBEuViVtaQN8iEhhtBY4gQSxBY38ms31DUWUx1bza").unwrap();
    let obligation = Pubkey::from_str("AKbU9oGFYebVtz64RDJptjEH7vTSz8jFkX9PoF4oiRxk").unwrap();
    let owner = Pubkey::from_str("2BGSs7s5mSJgSCMcppAaQj5Ppp1kHmQNQ9ESoGWK2Hmx").unwrap();
    
    let candidates = vec![
        ("obligation_user_state, farm, obligation", vec![b"obligation_user_state".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("user, farm, obligation", vec![b"user".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("user_state, farm, obligation", vec![b"user_state".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("farm_user, farm, obligation", vec![b"farm_user".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("user, farm, owner", vec![b"user".as_ref(), farm_state.as_ref(), owner.as_ref()]),
        ("user, farm", vec![b"user".as_ref(), farm_state.as_ref()]),
        ("kfarm, farm, obligation", vec![b"kfarm".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("position, farm, obligation", vec![b"position".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
        ("user_position, farm, obligation", vec![b"user_position".as_ref(), farm_state.as_ref(), obligation.as_ref()]),
    ];
    
    for (label, seeds) in candidates {
        let (pda, bump) = Pubkey::find_program_address(&seeds, &farms_program);
        println!("{:50} → {} (bump={})", label, pda, bump);
    }
}
