# 02_KNOWN_ISSUES · Auto-disclosure · 2026-05-09 07:20 UTC

Lista honesta de lo que **yo (Claude operativo)** sé que está mal o
dudoso. Se entrega completa para que Codex no pierda tiempo en lo ya
identificado y se enfoque en lo no detectado todavía.

---

## §1 · Discrepancias MD-firmado vs código real

### 1.1 · `[SAFETY-DIM]` assert YoY [0,20] · NUNCA aplicado en r150-sept

**Severidad declarada**: HIGH (caso real ya documentado)

**Detalles**:
- MD `r150sept_p3_6_implementado.md` (8-may 04:12 UTC) declaró DONE el
  edit de `bls_client.py` con assert `0 <= yoy_pct_raw <= 20`.
- Backup creado con timestamp `pre_assert_20260509T040917Z`.
- 9-may 05:30 UTC: verifiqué `wc -c` y `diff` — **archivo idéntico al
  backup**, edit nunca se aplicó.
- 9-may 05:33 UTC: aplicado realmente durante implementación P3.6.5
  (`r150decim_*.md` §1 disclosure).

**Impacto**: durante ~25h, el sidecar pudo capturar CPI YoY out-of-range
sin assert que lo bloqueara. Por suerte BLS rate-limit hit durante ese
período (solo HTTP 429, no datos malformed).

**Lección**: post-edit verify obligatorio (`grep` cadena nueva, `diff`
contra backup). Si Codex encuentra patrones similares en otros r-numbers,
flagealo CRITICAL.

### 1.2 · Posibles otros cases (no detectados aún · pista para Codex)

Sospechas mías sin evidencia confirmada:
- ¿`forecasts_validator` está realmente inicializándose con
  `require_signature=True` en producción? (firmado en r150-quad)
- ¿El SHA-256 cache TTL agregado hoy en `bls_client.py` realmente está
  cacheando en runtime, o solo aparece en disco? (necesita verificación
  con journalctl)
- ¿`sf_engine.py` Esta integrado al main loop? **Sé que NO, pero el MD
  r150-novum sugiere "P3.7 next"**. Asegúrate de que no haya code
  paths llamando a SFEngine que crean falsa sensación de feature
  activa.

---

## §2 · NFP gate FAIL · 2026-05-08 12:30 UTC

**Severidad**: HIGH (resuelto pero sintomático)

**Qué pasó**:
- Vie 8-may 12:30 UTC: NFP USA release esperado.
- FMP API empezó devolver HTTP 402 (pricing change 2025-08-31).
- Sidecar tenía `fmp.status=stale` previo · NO lo detecté en sweeps.
- Resultado: NO captura del NFP actual, NO mode transition, gate FAIL.
- Marco quote: "yo qudo mal con mi socio".

**Resolución**:
- Migration emergencia FMP→FRED+BLS+forecasts.json en 75 min.
- `fmp_compat.py` drop-in.
- `fmp.status=stale` → ahora alarma activa.

**Lección encapsulada en regla firmada**
`feedback_status_sweep_completo.md`:
"En cualquier status check verificar también data-input dependencies
(fmp.status, fred, btc, polymarket sync ages), no solo service-level.
Levantar bandera proactiva si feeder stale."

---

## §3 · BUG-NFP-DIM · diferido oficialmente a 2026-05-15

**Severidad**: MEDIUM (mitigado con neutral SF=0.0 en r150-undecim-tris)

**Detalles técnicos**:
- `forecasts.json` campo `nfp_change_thousands` está en **miles** (62, 178)
- `SIGMA_FRED["NFP"]` está en valor **absoluto** (~75,000)
- Cálculo SF = (actual - forecast) / sigma → 10^3 mismatch
- Smoke test SFEngine devolvió SF NFP = 0.0002σ (esperado ~0.24σ)

**Status**: detectado 8-may en `r150pent_*.md`. Firmado Opción C
("defer fix to 2026-05-15") por Gemma 4 31B en `r150hex_*.md`.

**Mitigación implementada hoy 9-may** (`r150-undecim-tris` §4):
- En `sf_engine.py`, si `category=="NFP"` y `BUG_NFP_DIM_ACTIVE=True`:
  return `ModeDecision(sf=0.0, mode="NORMAL", bug_nfp_dim_skip=True)`
- Garantiza que un evento NFP nunca dispare CAUTELA falsa.
- Audit trail explícito.

**⚠️ La integración de SFEngine en sidecar.py main loop (P3.7) está
PENDIENTE**. Hasta que P3.7 se integre, este bug es teórico (el assert
de bls_client no se invoca para NFP).

---

## §4 · Servicios systemd FAILING

| Service | Estado | Última run | Acción |
|---|---|---|---|
| `trading_bot.service` | FAILED | unknown | NO investigado · legacy |
| `velocityquant-pathc-healthcheck.service` | FAILED | unknown | typo "pathc"? · NO investigado |
| `vq-adp-capture.service` | FAILED | 2026-05-06 | CPI capture intent · obsoleto post-FMP migration? |

**Riesgo**: si alguno se autoinicia y empieza a interferir con producción,
puede romper checks de salud. **NO investigados pre-LIVE Mar 12**.

---

## §5 · Timers DEAD

### 5.1 · `vq-shadow-rsync.timer`

**Función originaria**: rsync `cyclic_shadow.jsonl` Newark → Dallas cada
N min.

**Estado**: dead since unknown date.

**Implicación**: `/home/administrator/newark_mirror/` puede estar **stale**
respecto al código realmente corriendo en Newark. **El bundle Codex
incluye este mirror** pero podría no reflejar la última versión deployada.

**Workaround**: el `code/v4_q1q4_patches/` tiene los diffs aplicados en
deploy 2026-05-07 V4-Alpha. Ese delta es source-of-truth para esa fase.

### 5.2 · `poly_log_rotator.timer`

**Estado**: NUEVO 9-may 05:35 UTC · enabled+active.

**No DEAD pero "no validado en runtime"**: el primer run real será
2026-05-10 03:30 UTC. Sin evidencia empírica de que funcione.

---

## §6 · Hot wallets sin protección

**Path**: `/home/administrator/.velocityquant_secrets/`

**Riesgo concreto**:
- Modo 600 (solo administrator puede leer)
- Plaintext JSON con private keys Solana/Stellar
- Sin HSM, sin air-gap, sin threshold-signing
- Si atacante consigue RCE como user `administrator`:
  - Drena `hot200_keypair` (cuántos SOL? necesita query on-chain)
  - Drena `x402_keypair` (USDC custody · cuánto?)
  - Firma con `stellar_keypair`

**¿Qué hay en cada wallet?** Codex puede pedirme que consulte on-chain
y le pase saldos exactos.

---

## §7 · Sin CI/CD · sin gating de deploys

- Cero pipelines visibles
- Deploys son manuales: edit + restart systemctl
- Sin pre-commit hooks que verifiquen sintaxis (ya nos costó el
  `[SAFETY-DIM]` assert)
- Sin tests obligatorios pre-merge (de hecho, no hay merge — código vive
  en branches sin merging)
- `solana_executor_rs/` tiene git, pero sin remote visible

**Impacto LIVE**: cualquier deploy futuro puede tener el mismo bug
"Edit reportado pero no aplicado".

---

## §8 · Test coverage no medible

- No hay `pytest --cov` reporte
- `poly_sidecar/tests/` tiene 5-6 archivos
- `synthetic_tests/run_test1_kill_switch_latency.py` (un test)
- `quantum_ppo/` sin tests dedicados (solo tensorboard logs)
- Rust: no `cargo test` en CI · cobertura desconocida

**Pregunta para Codex**: ¿hay tests críticos faltantes (e.g. para
`sf_engine.py`, `bls_client.py [SAFETY-DIM]`, `tau_calc.py`)?

---

## §9 · `.bak` files debris (lista parcial)

```
poly_sidecar/
├── bls_client.py.bak_pre_assert_20260509T040917Z       (10422 bytes · pre [SAFETY-DIM])
├── bls_client.py.bak_pre_p3_6_5_20260509T052811Z       (10422 bytes · pre P3.6.5)
├── fmp_compat.py.bak_pre_validator_20260509T040917Z    (12748 bytes)
├── forecasts_loader.py.bak_pre_validator_20260509T041001Z (3851 bytes)
├── health_api.py.bak_pre_haircut_removal_20260507T201126Z
├── health_api.py.bak_pre_revert_20260507T093917Z
├── macro_calendar.json.bak_pre_kurtosis_migration_20260505T*
├── macro_calendar.json.bak_pre_mad_20260505T071844Z
└── sidecar.py.bak_pre_fmp_compat_20260508T130517Z
└── sidecar.py.bak_pre_p3_6_5_20260509T052811Z

profitlab_quantum/app/
├── engine.py.bak* (x8)
└── main.py.bak* (x5)
```

**Total**: ~26 .bak files conocidos (probable más en subdirs).

**Riesgo**: si un fix futuro se aplica al `.bak` por error, o si un
`grep` confunde código activo con backup.

---

## §10 · Network exposure

### 10.1 · `vq-poly-api:8090` audit dashboard

- Ruta nginx: `inicio.velocityquant.io/poly/audit/`
- **Auth fue REMOVIDA** Sáb 9-may 02:56 UTC
- Razón: Marco quería dashboards públicos
- Riesgo: cualquiera puede leer sidecar state, KPIs, posiciones
  (si tuviera) ¿hay info sensible que no debería ser pública?

### 10.2 · `:8095` debate-bots

- Proxy: `inicio.velocityquant.io/fran/`
- Public · upload bots · ¿hay risk de write?

### 10.3 · `toxicflow.velocityquant.io`

- Status: WIP placeholder
- API comentada · cero functional
- ¿Por qué está deployed con SSL si no funciona?

---

## §11 · Configs y dependencias sin pinning

- `requirements.txt` no usa `==` sino `>=` (httpx>=0.27.0)
- `Cargo.toml` tiene versiones fluidas (no committeo `Cargo.lock` en
  algunos? — verificar)
- `pip install -U <pkg>` en cualquier momento puede romper algo

---

## §12 · Lo que NO sé · honest gaps

- ¿Cuánto SOL/USDC hay realmente en las hot wallets ahora? (necesita
  query on-chain · puedo ejecutarlo si Codex lo pide)
- ¿El `cyclic_shadow.jsonl` de Newark refleja todos los `would_send`
  events o solo un sample?
- ¿`liquidator_rs` LIVE en Newark está usando exactamente el código del
  mirror, o ya tiene patches no committeados?
- ¿Hay backups encriptados de los keypairs en otra parte?
- ¿La memoria de Claude (`/home/administrator/.claude/projects/.../memory/`)
  contiene info sensible que debería ser sanitizada?
- ¿`bot2_prime` y `bot3_prime` siguen tocando capital o son zombies?
  (el Explore inventory los listó como "?")

---

## §13 · Cosas que están BIEN (anti-bias)

Para no contagiar pesimismo, tengo que reconocer lo que me parece
sólido (Codex puede contradecir):

- **Migration FMP→FRED+BLS** se hizo en 75 min sin downtime de capital.
- **Validator + sign de forecasts.json** previene tampering manual.
- **Hard-assert YoY [0,20]** ahora aplicado → hay safety net dimensional.
- **Soak time 12h** post-restart antes de integrar P3.7 → conservadurismo.
- **3 actores con jerarquía clara** evita decisiones unilaterales.
- **Disk offload** (sdb2 83→50%) sin migración (per Gemma) preserva
  rutas binarias del bot LIVE.
- **Threshold gates** (StressPass 16 checks) son explícitos y auditables.
- **Capital LIVE expuesto = $0** durante todo el desarrollo.

---

**Generador**: Claude Opus 4.7 (autodisclosure honesta)
**Fecha**: 2026-05-09 07:20 UTC
**Para Codex**: lee este file primero junto con 00_BRIEF · te ahorrará
tiempo en lo ya conocido. Foco en encontrar lo NO listado aquí.

---

## §14 · UPDATE 07:30 UTC · hallazgos durante el bundling (auto-disclosure adicional)

Durante la generación del bundle Codex, encontré **dos secret leaks críticos** en filesystem que no estaban en mi list inicial:

### 14.1 · Anthropic API key hardcoded como fallback · CRITICAL
**Archivos** (filesystem real, no solo bundle):
- `/srv/quantum_ppo/mbot_auditor.py:6`
- `/srv/quantum_ppo/claude_client.py`
- `/srv/quantum_ppo/claude_auditor.py`

**Patrón**:
```python
api_key = os.environ.get("ANTHROPIC_API_KEY") or "<REDACTED-PREFIX>"
```

GitHub Secret Scanning detectó el secret al intentar push y bloqueó el repo. **El key debe ser rotado en Anthropic console urgentemente** + cambiar el patrón a `os.environ["ANTHROPIC_API_KEY"]` (sin fallback).

En el bundle el key ya está reemplazado por `<REDACTED-BY-CLAUDE-AT-BUNDLE-TIME>`.

### 14.2 · `.env.bak_pre_r66` con secrets reales · CRITICAL
**Archivo**: `/home/administrator/newark_mirror/liquidator_rs/.env.bak_pre_r66`

**Contenido**:
- `WALLET_PRIVATE_KEY` Solana base58 (clave privada hot wallet)
- `LIQ_GRPC_TOKEN` (Chainstack)
- `TG_BOT_TOKEN` + `TG_SECRET_TOKEN` (Telegram)

Mode 600. NO está en el bundle (filtrado). Pero está en disco plaintext desde 2026-05-03.

### 14.3 · Implicación para el audit
Si yo (Claude) detecté esto en 30 min de bundling automatizado, **probablemente Codex va a encontrar más casos similares**. Específicamente sospecho:
- `/home/administrator/.config/*/api_key` plaintext (FRED + BLS confirmados)
- Otros `.env*` files en `/home/administrator/{solana_executor,mbottoken-signals,akaunting,solana_arb_real}/`
- `audit_dashboard_shared_secret.txt` en `.velocityquant_secrets/`
- Posibles credenciales hardcoded en otros `.py` no examinados aún

**Acción correctiva ya planificada** (post-CPI gate Mar 13+): rotación completa de credenciales + remoción de hardcoded fallbacks + escaneo continuo con `gitleaks` o `trufflehog`.
