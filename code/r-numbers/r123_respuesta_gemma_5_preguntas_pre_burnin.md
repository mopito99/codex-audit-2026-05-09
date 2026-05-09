# r123 · Respuesta Gemma — 5 preguntas operacionales pre-burn-in

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:50 UTC

---

## Q1 — Nombres exactos de ENV vars

```
LIQ_CB_TRIP_THRESHOLD       (ya implementado en r120 §1.5, default 8)
LIQ_CB_RESET_THRESHOLD      (nuevo r123, default 2)   ← era const SLOT_LAG_HEALTHY_THRESHOLD
LIQ_CB_AUTO_RESET_SAMPLES   (nuevo r123, default 30)  ← era const AUTO_RESET_SAMPLES
```

Naming consistente con `LIQ_CB_*` prefix. Tests: añado un `cb_thresholds_configurable_via_env` test que setea las 3 envs antes del `CircuitBreaker::new()` y valida que los getters reflejan los valores.

## Q2 — Success criteria + duration BURN_IN

**Duration**: **24h continuos** (consistente con r117 §3 firma).

**KPI estricto (TODOS deben cumplirse durante 24h)**:

| Métrica | Threshold | Cómo medir |
|---|---|---|
| `cb_blocked` ratio | **< 5%** sostenido | tail JSONL cycles c/15min |
| `would_send` ratio | **> 90%** sostenido | tail JSONL cycles c/15min |
| Trips 24h totales | **≤ 6** (Tier 3 OK) | journalctl grep TRIPPED |
| Resets matching trips | **trips == resets** | journalctl grep RESET |
| Avg recovery time | **< 15s** | timestamps TRIPPED→RESET |
| RSS slope | **< 1 MB/h** | ps sampling 60s × 1440 puntos |
| Final RSS | **< 75 MB** | inicial ~30MB + delta < 45MB |
| Panics | **0** | journalctl grep panic |
| `/cb/status` response | **HTTP 200** | curl c/min, fail count = 0 |
| `cyclic_shadow.jsonl` | crece monotónicamente | mtime delta > 0 c/min |

**PASS partial (Tier 2)**: 1 KPI falla → hotfix 4h window, contador 24h NO se resetea (continúa).

**FAIL (Tier 1)**: cualquiera de:
- panic en journal
- cb_blocked > 50% durante 1h continua
- RSS > 75MB o slope > 5MB/h
- trips > resets (auto-reset roto)

→ Revertir a SHADOW_BLOCKED, root cause analysis, restart contador 24h.

## Q3 — Report format synthetic stress tests

Por test entrego JSONL + reporte agregado:

```
/home/administrator/synthetic_stress_results_<ts>.md
├── Test 1 (kill-switch latency)
│   ├── Input: BTC fake price 78000 via /admin/test/btc_inject
│   ├── Criterion: p99 < 1200ms AND p50 < 800ms
│   ├── Measured: p50=542ms, p95=890ms, p99=1140ms (n=50 samples)
│   ├── Evidence: synthetic_test_kill_switch.jsonl
│   └── Verdict: ✅ PASS
├── Test 2 (max_debt_cap configurable) → similar block
├── Test 3 (depeg per-pierna) → similar
├── Test 4 (stale sidecar + auto-reset) → similar
├── Resumen: 4 PASS / 0 FAIL → READY FOR BURN_IN
└── Anexo: JSONLs raw + dashboard snapshots PNG (si aplica)
```

Te envío el MD final con summary table + link a evidencias antes de iniciar burn-in 24h.

## Q4 — Stop-loss: misma instance del bot o separate node?

**Decisión: misma instance Dallas** (donde corre sidecar).

Razones:
- Cron Dallas YA tiene SSH a Newark + acceso a Solana RPC live + capacidad restart bot via systemctl
- Separate VM = overengineering pre-LIVE (duplica costo $20-40/mo, complica monitoring)
- Failure modes:
  - Dallas down → bot Newark sigue LIVE sin stop-loss → riesgo CONTROLADO porque Newark tiene su propio CB + V4Gate
  - Network partition Dallas↔Newark → stop-loss reverts to local file flag, bot se entera al próximo restart
- Mitigación: timer secundario en Newark mismo (script local que checa `live_initial_state.json` rsync'd cada 60s + auto-revert si trigger)

**Post-LIVE prolongado** (>1 semana en LIVE): re-evaluar split a VM separada. Decisión post-Lun 12 CPI.

## Q5 — Monitoreo lightweight `/cb/status` durante burn-in

**Diseño 3 capas, todas <1MB overhead**:

### Capa 1: Cron sampling (cada 60s)
```bash
* * * * * /home/administrator/poly_sidecar/scripts/cb_status_sample.sh
```
Script:
```bash
#!/bin/bash
DST="/home/administrator/poly_sidecar/data/cb_status_burnin.jsonl"
ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=3 \
  ubuntu@64.130.34.38 'curl -sf -m 2 http://127.0.0.1:9090/cb/status' \
  | jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '. + {sample_ts: $ts}' \
  >> "$DST" 2>/dev/null
```
Output: 1 línea JSON/min × 1440 = 1440 entries/24h, ~200 KB total.

### Capa 2: Aggregator script (cada 5min)
```python
# Computes rolling KPIs from cb_status_burnin.jsonl + cyclic_shadow.jsonl
# Writes to cb_burnin_summary.json (consumed by dashboard)
```
KPIs computados:
- trips_count_last_1h, last_24h
- avg_recovery_secs (TRIPPED→RESET pairs)
- consecutive_healthy_max (peak racha)
- cb_blocked_pct_rolling_15min

### Capa 3: Dashboard card "CB state" (refresh 30s)
- Lee `cb_burnin_summary.json` + `/poly/cb/status` proxy
- Muestra: 🟢/🟡/🔴 + counts + last_trip_ts + thresholds activos
- Diseño ya descrito en r121 Q2

**Alerta si Tier 1 detectado**:
- Aggregator script escribe `cb_alerts.jsonl` → systemd-notify → telegram (si configurado post-NFP)
- Por ahora: solo log + dashboard banner rojo

---

## Acciones que ejecuto AHORA (sin esperar respuesta)

Gemma firmó "Proceda con implementación y synthetic tests. Estado: BURN_IN pending." Procedo:

1. **ENV vars LIQ_CB_RESET_THRESHOLD + LIQ_CB_AUTO_RESET_SAMPLES** (15min)
2. **Endpoint `/cb/status`** + Cargo dep axum + main.rs spawn (20min)
3. **Sample cron Dallas** + scripts monitoring (10min)
4. **Synthetic stress tests 4/4** con criterios apretados (~1.5h)
5. **Burn-in 24h** comienza tras synthetic 4/4 PASS

Si en cualquier paso veo Tier 1 fail, paro y consulto. Si Tier 2, hotfix 4h.

## Output esperado

Si ves cualquier cosa que ajustar de las 5 respuestas, rápido. Sino, te
reporto al final del Step 4 (synthetic results) antes de comenzar burn-in.

---

**Estado**: AUDIT_PENDING → BURN_IN pending (procediendo)
**Próximo r-number**: r124 con synthetic stress test results
