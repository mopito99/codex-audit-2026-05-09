# 01_INVENTORY · VelocityQuant · 2026-05-09 07:15 UTC

Inventario completo del proyecto. Read-only. Sin recomendaciones.

---

## §1 · Componentes principales

| Componente | Path | Lenguaje | LOC | Tamaño | Estado |
|---|---|---|---|---|---|
| **Polymarket sidecar** | `/home/administrator/poly_sidecar/` | Python 3.12 | ~10,610 | 2.6 GB (con venv) | ACTIVO · soak P3.6.5 |
| **solana_executor_rs** (Dallas) | `/home/administrator/solana_executor_rs/` | Rust | ~3,463 | <100 MB | git tracked · activo |
| **newark_mirror cyclic_rs** | `/home/administrator/newark_mirror/cyclic_rs/` | Rust | parte de 15,300 | ~250 MB | mirror Newark V3.5 LIVE |
| **newark_mirror liquidator_rs** | `/home/administrator/newark_mirror/liquidator_rs/` | Rust | parte de 15,300 | ~150 MB | mirror Newark V3.5 LIVE |
| **newark_mirror solana_executor_rs** | `/home/administrator/newark_mirror/solana_executor_rs/` | Rust | parte de 15,300 | ~100 MB | mirror (con .backup dirs) |
| **v4_q1q4_patches** | `/home/administrator/v4_q1q4_patches/` | Rust | ~52 KB total | <1 MB | parches V4 pre-deploy |
| **profitlab_quantum** (LIVE paper) | `/srv/profitlab_quantum/` (symlink → `/nvme0n1-disk/srv/profitlab_quantum`) | Python | ~4,300 | 103 MB | activo paper trading BingX |
| **quantum_ppo** (lab offline) | `/srv/quantum_ppo/` | Python | ~3,000 | 8.7 GB (PPO weights + tensorboard) | activo training |
| **quantum_dashboard** | `/srv/quantum_dashboard/` | Flask | <500 | 24 MB | activo |
| **cuandeoro_xlm** | `/srv/cuandeoro_xlm/` | Soroban Rust | — | — | track XLM separado |
| **bot2_prime / bot3_prime** | `/srv/bot{2,3}_prime/` | Python | — | — | legacy HFT |

---

## §2 · Estructura `poly_sidecar/`

```
poly_sidecar/
├── sidecar.py              ← main loop (asyncio · 692 lines · MODIFICADO 9-may)
├── bls_client.py           ← BLS API client (319 lines · MODIFICADO 9-may con [SAFETY-DIM])
├── fmp_compat.py           ← drop-in para FRED+BLS (post-FMP migration)
├── fred_calendar_client.py ← FRED API client
├── fred_init.py            ← FRED bootstrap
├── investing_client.py     ← Investing.com fallback parser
├── poly_client.py          ← Polymarket client (volume, midpoints)
├── btc_feed.py             ← BTC spot price feed
├── tau_calc.py             ← Surprise factor τ formulas
├── sf_engine.py            ← SFEngine standalone (P3 · NO integrado main loop)
├── forecasts_loader.py     ← Loads forecasts.signed con validator gate
├── forecasts_validator.py  ← 6-gate validator
├── sign_forecasts.py       ← SHA-256 signer
├── log_rotator.py          ← P5.0 NUEVO 9-may
├── store.py                ← state persistence
├── health_api.py           ← FastAPI :8090 endpoints (audit + state)
├── forecasts.json          ← consensus forecasts manuales
├── forecasts.signed        ← hash sigado por Marco
├── macro_calendar.json     ← config calendar formula
├── risk_config.json        ← risk thresholds
├── data/
│   ├── tau_state.json      ← state file written each tick
│   ├── sidecar.log         ← log archivo
│   ├── audit/              ← audit MDs históricos
│   └── shadow_mirror/cyclic_shadow.jsonl ← V4-Alpha shadow log copy
├── tests/
│   ├── test_parser_and_sigma.py (208 lines)
│   ├── test_kill_switch.py (355 lines)
│   └── ...
├── synthetic_tests/run_test1_kill_switch_latency.py (233 lines)
├── scripts/burnin_sample.py (96 lines)
└── *.bak files (varios)
```

---

## §3 · Estructura `solana_executor_rs/` (Dallas, git tracked)

```
solana_executor_rs/                  ← /home/administrator/
├── Cargo.toml (1.7 KB · 2026-05-01)
├── Cargo.lock (182 KB)
├── .env.template (3.4 KB)
├── .git/ (tracked)
├── data/
└── src/
    ├── alt_cache.rs (173)
    ├── sandwich_executor.rs (406)
    ├── bot_detector.rs (187)
    ├── pool_state.rs (111)
    └── ... (3,463 total LOC)
```

Modificado más reciente: 2026-05-01.

---

## §4 · Estructura `newark_mirror/`

```
newark_mirror/
├── cyclic_rs/        ← Cycle detector Raydium/Orca CLMM
│   ├── src/
│   │   ├── main.rs · lib.rs
│   │   ├── cycle_finder.rs · pool_state.rs · clmm_math.rs
│   │   ├── priority_fee.rs · grpc.rs · config.rs
│   │   └── shadow_logger.rs
│   └── Cargo.toml
├── liquidator_rs/    ← Solana on-chain liquidator + Jito MEV
│   ├── src/
│   │   ├── main.rs · rpc.rs · wallet_monitor.rs
│   │   ├── jito.rs · pyth_oracle.rs · pool_registry.rs
│   │   ├── safety_worker.rs · telegram_listener.rs
│   │   ├── wallet_rotator.rs · tip_stream.rs · observability.rs
│   │   └── ...
│   └── Cargo.toml
└── solana_executor_rs/   ← versión sincronizada del Dallas executor
    └── src/
        ├── execution_engine/ · main.rs
        └── .backup_pre_sandwich_20260429_113341/  (DEBRIS · 138+261+245 LOC)
```

Total: ~15,300 LOC Rust (incluye backups internos).

⚠️ **Pega: `vq-shadow-rsync.timer` está DEAD desde hace tiempo · este
mirror puede estar stale**.

---

## §5 · Estructura `v4_q1q4_patches/`

```
v4_q1q4_patches/                     ← parches V4 pre-deploy 2026-05-07
├── cyclic_rs/
│   └── shadow_logger.rs (9.0 KB)
└── liquidator_src/
    ├── config.rs (6.5 KB)
    ├── cyclic_dispatch.rs (26.9 KB)  ← lógica V4 cyclic dispatch
    └── main.rs (19.7 KB)
```

Estos son **diffs aplicados a Newark** en deploy 2026-05-07 (V4-Alpha
SHADOW). Útil para Codex porque muestran el delta V3.5 → V4-Alpha.

---

## §6 · Estructura `profitlab_quantum/` (LIVE paper)

```
profitlab_quantum/
├── app/
│   ├── engine.py (+ engine.py.bak* x8 DEBRIS)
│   ├── main.py (+ main.py.bak* x5 DEBRIS)
│   ├── config.py (líneas relevantes 220-224 PPO config)
│   ├── state_schema.py
│   ├── models/
│   │   ├── agent.py (PPO ActorCritic)
│   │   └── ppo_persistence.py (Postgres save/load)
│   └── ...
├── active_tokens.json (20 símbolos universo)
├── artifacts/ppo/by_symbol/<sym>/ppo.pt (checkpoints)
├── database.db (0 bytes placeholder)
├── profitlab_quantum.db (SQLite trades log)
└── balance_snapshots.jsonl
```

Postgres DB: `profitlab_quantum_db` con tablas:
- `ppo_memory` (~160 rows · 10/símbolo)
- `ppo_training_log` (~380 rows)
- `paper_trades_archive` (~89 rows · solo DOGE-USDT, Feb 24 - Mar 16)
- `paper_equity` · `paper_positions` · `decision_logs` (~38,247 last 7d)

---

## §7 · Servicios systemd (snapshot 2026-05-09 07:15 UTC)

### Activos (enabled · running)
- `vq-poly-sidecar.service` ← sidecar main loop
- `vq-poly-api.service` ← FastAPI :8090
- `profitlab_quantum_bot.service` ← QuantumBot LIVE paper
- `profitlab_quantum_web.service` ← FastAPI :8000
- `quantum_dashboard.service` ← Flask
- `bot2_prime.service` ← legacy HFT
- `bot3_prime.service` ← legacy HFT
- `profitlab_prime.service` · `profitlab_prime_bitunix.service` · `profitlab_prime_panel.service` ← legacy
- `vq-debatebots-upload.service` ← DebateBots

### Static (one-shot · invocados por timer u otros)
- `poly_log_rotator.service` ← P5.0 nuevo 9-may
- `velocityquant-refill-sol.service` · `velocityquant-refill-x402.service` ← gas refill
- `velocityquant-shadow-collector.service` · `velocityquant-v3-hourly.service`
- `vq-adp-capture.service` (CPI capture) · `vq-burnin-sample.service`
- `bot3_prime_git_backup.service` · `bot3_prime_bitunix_git_backup.service`

### FAILING / dudosos (FLAG · ver 04_SYSTEMD_STATE.md)
- `trading_bot.service` ← FAILED (legacy)
- `velocityquant-pathc-healthcheck.service` ← FAILED (typo "pathc"?)
- `vq-adp-capture.service` ← último run FAILED 2026-05-06

---

## §8 · Timers systemd

### Activos
- `vq-pnl-snapshot.timer` ← snapshots ~3min
- `vq-pnl-shadow-cache.timer` ← jsonl cache refresh
- `velocityquant-refill-sol.timer` · `velocityquant-refill-x402.timer` ← gas ~15min
- `hftbots-evaluator.timer` · `hftbots-pair-scanner.timer` ← MEV scanners
- `velocityquant-v3-hourly.timer` ← H1-H6 auto-fill+rollback
- `bot3_prime_git_backup.timer` · `bot3_prime_bitunix_git_backup.timer`
- `poly_log_rotator.timer` ← NUEVO 9-may · next 2026-05-10 03:30

### Dead / suspectos
- `vq-shadow-rsync.timer` ← DEAD · Newark→Dallas mirror stale
- `vq-adp-capture` (no aparece como timer activo) · ¿auto-disabled?

---

## §9 · Nginx vhosts

### `velocityquant.io`
- Root: `/home/administrator/hftbots/`
- Locations: `/cyclic/` · `/liquidator/` · `/gemma/`
- SSL: Certbot
- Backup configs: 5 `.bak_pre_*`

### `inicio.velocityquant.io`
- Root: `/home/administrator/liquidator/`
- Proxy: `:8090` (vq-poly-api) · `:8095` (debatebots)
- Locations: `/poly/` · `/fran/` · `/codex/` · `/audit/`
- Auth REMOVIDA Sáb 9-may 02:56 UTC (Marco quiso público)

### `toxicflow.velocityquant.io`
- Root: `/srv/toxicflow/web/`
- Status: WIP placeholder
- API: comentada

---

## §10 · Secrets / credentials (paths · NO contenidos)

```
/home/administrator/.velocityquant_secrets/    [drwx------ 700]
├── hot200_keypair.json                        [Solana wallet activa]
├── x402_keypair.json                          [USDC custody]
├── stellar_keypair.json                       [Stellar signing]
├── internal_ledger.json                       [trade history encrypted?]
├── audit_dashboard_shared_secret.txt          [rate-limit shared key]
└── *_meta.json                                [keypair metadata]

/home/administrator/.config/fred/api_key       [600]
/home/administrator/.config/bls/api_key        [600 · creado 9-may]
```

⚠️ Plaintext keypairs · sin HSM · sin threshold-signing · escalation
RCE → drain.

---

## §11 · MDs firmados (selección representativa en bundle)

Path: `code/r-numbers/`

Selección:
- `r93_*.md` (firma Gemma original)
- `r107_*.md` ... `r150_*.md` (cadena completa)
- `r150-bis-RCA_*.md` (NFP gate FAIL post-mortem)
- `r150-quad_*.md` (validator + sign Q1)
- `r150-pent_*.md` (BUG-NFP-DIM detected)
- `r150-hex_*.md` (Opción C firmada)
- `r150-sept_*.md` (P3.6 implementado · ⚠ caso assert no aplicado)
- `r150-oct_*.md` (restart smoke test)
- `r150-novum_*.md` (BLS API key activada)
- `r150-decim_*.md` (P3.6.5 + P5.0 · disclosure honesto)
- `r150-undecim_*.md` (restart KPIs)
- `r150-undecim-{bis,tris,quad}_*.md` (cierre Q&A Gemma)

Total: ~30 MDs en bundle.

---

## §12 · Outputs y datos en bundle

```
codex_audit_2026-05-09/
├── 00_BRIEF.md (~10 KB)
├── 01_INVENTORY.md (este file)
├── 02_KNOWN_ISSUES.md (auto-disclosure)
├── 03_TIMELINE.md (track-record r-numbers)
├── 04_SYSTEMD_STATE.md (snapshot servicios)
├── 05_NGINX_CONFIGS.md (vhosts producción)
├── code/ (~rsync sanitizado)
├── logs_sample/ (7d journals sanitized)
├── configs/ (nginx + systemd unit files)
├── systemd_units/ (unit files completos)
└── SHA256SUMS (hash de cada archivo)
```

---

## §13 · Cosas EXCLUIDAS del bundle (deliberadamente)

- `**/venv/` (deps externas)
- `**/__pycache__/`, `*.pyc`
- `**/target/` (Rust build artifacts)
- `**/.cargo/` (Cargo cache)
- `**/.git/objects/pack/` (objetos git pesados; .git struct sí incluido)
- `**/tensorboard_logs/` (PPO training logs · GBs)
- `**/eval_logs/` (PPO eval logs)
- `**/*.pt`, `**/*.bin`, `**/*.safetensors` (model weights)
- `*.json` keypair files
- `.env` files
- `api_key` files
- `internal_ledger.json` (trade history)
- `audit_dashboard_shared_secret.txt`

Si Codex requiere alguno explícito, Marco decide caso por caso.

---

**Generador**: Claude Opus 4.7 vía Explore agent + verificación directa
**Fecha snapshot**: 2026-05-09 07:15 UTC
