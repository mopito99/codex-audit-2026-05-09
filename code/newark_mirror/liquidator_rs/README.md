# liquidator_rs

Kamino lending liquidations bot. Plan F2 de R9 (Gemma).

## Milestones
- **M0** (today): subscribe Yellowstone gRPC → parse Obligation accounts → log unhealthy to JSONL. PAPER detection only, no on-chain ix.
- **M1** (day 2): liquidate ix builder + simulator. Devnet test.
- **M2** (day 3): Jito bundle integration. Mainnet $200 probe.
- **M3** (day 4+): scale to $2000 if M2 OK. Add Drift handler.

## Run M0
```bash
cd ~/liquidator_rs
source ~/.cargo/env
cargo run --release
tail -f data/unhealthy_positions.jsonl
```

## Status
- M0 scaffold written 2026-05-01.
- Obligation offset for aggregate values uses tail-of-account heuristic (last 64 bytes). To be empirically validated against Kamino SDK in M1.
