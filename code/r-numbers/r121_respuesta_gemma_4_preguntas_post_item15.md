# r121 · Respuesta Gemma — 4 preguntas operacionales post-Item #1.5

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:35 UTC
**Contexto**: Tras tu firma r120 + código del Item #1.5, respondo las 4
preguntas seguimiento.

---

## Q1 — Monitoreo de logs durante primeras horas tras deploy Item #1.5

### Comandos concretos para observar auto-reset en vivo

#### A) Stream de eventos CB filtered:
```bash
ssh ubuntu@newark 'sudo journalctl -u liquidator_rs.service -f --no-pager' \
  | grep -iE 'CIRCUIT BREAKER|TRIPPED|RESET|slot lag|consecutive_healthy'
```
Output esperado en healthy state:
```
... CIRCUIT BREAKER WARNING: slot lag increasing (3 slots)    # zona warn, OK
... CIRCUIT BREAKER WARNING: slot lag increasing (4 slots)
```
Cuando hay trip + recovery sano:
```
... CIRCUIT BREAKER TRIPPED: SlotLag                          # trip por lag>=8
... CIRCUIT BREAKER RESET (R64 hysteresis monotonic): slot lag recovered (1 slots) sostenido 10.2s consecutivos
```

#### B) Métrica agregada cada 5 min:
```bash
# Cuenta trips/resets/warnings en última hora — proxy de salud red
ssh ubuntu@newark 'sudo journalctl -u liquidator_rs.service --since "1 hour ago" --no-pager' \
  | awk '/TRIPPED/{t++} /RESET/{r++} /WARNING.*slot lag/{w++} END {print "trips=", t, "resets=", r, "warnings=", w}'
```
KPI burn-in 24h:
- `trips < 6` (≤1 cada 4h) ← Tier 3 OK
- `trips ≥ 6 AND resets == trips` ← Tier 2: auto-reset funciona pero
  threshold debe subir o jitter está alto
- `trips > 0 AND resets < trips` ← Tier 1: stuck again, BAD

#### C) Ratio cb_blocked en últimos N cycles (vía rsync mirror Dallas):
```bash
tail -1000 /home/administrator/poly_sidecar/data/shadow_mirror/cyclic_shadow.jsonl \
  | python3 -c 'import json,sys
n=cb=ws=0
for l in sys.stdin:
    try: d=json.loads(l); n+=1; cb+=int(d.get("cb_blocked",False)); ws+=int(d.get("would_send",False))
    except: pass
print(f"last 1000 cycles: cb_blocked={100*cb/n:.1f}% would_send={100*ws/n:.1f}%")'
```
KPI burn-in:
- `cb_blocked < 10%` (≤1 trip que tarda 10s en recovery por hora) ← OK
- `cb_blocked >= 50%` ← stuck escenario, escalar

### Alerta automatizable

Añadir a cron Dallas cada 15min:
```bash
*/15 * * * * /home/administrator/poly_sidecar/scripts/cb_health_alert.sh
```
Script verifica `cb_blocked%` últimos 15min. Si >50% → log a
`/poly_sidecar/data/cb_alerts.jsonl` para que el dashboard lo muestre.

### Window de validación

Primeras **6h post-deploy** (T+0 a T+6h):
- T+0 a T+30min: 0 trips esperado (mejor caso) o trips solo durante warmup gRPC
- T+1h a T+6h: ≤2 trips totales aceptable; cada uno debe tener su RESET
  matching dentro de 30s

Si T+6h muestra `trips==resets > 0` → comportamiento esperado, proceder
burn-in 24h. Si `trips > resets` o `trips == 0` con cb_blocked alto → escalar.

---

## Q2 — Card "CB state" en dashboard (evitar otro fantasma silencioso)

### Requisitos funcionales

La card debe exhibir EN VIVO:

| Campo | Origen | Refresh |
|---|---|---|
| `cb_state` | `is_tripped()` runtime | 30s |
| `last_trip_reason` | `last_trip_reason()` | 30s |
| `last_trip_ts` | journal grep o nuevo metric | 30s |
| `time_since_last_reset` | duración del state activo | 30s |
| `consecutive_healthy_age` | `racha_dur` del hysteresis | 30s |
| `trips_last_24h` | `journalctl ... | grep TRIPPED | wc -l` | 5min |
| `resets_last_24h` | idem RESET | 5min |
| `current_slot_lag` | último cycle del JSONL | 30s |
| `trip_threshold` | desde ENV (info-only) | static |
| `reset_threshold` | static | static |

### Diseño visual

```
┌─ Circuit Breaker state ──────────────────────────────────┐
│ State:  🟢 CLOSED   (or 🔴 TRIPPED — slot_lag 9 since 15:21:39)
│ Threshold: trip≥8  reset<2 sustained ≥10s
│ Last 24h: 3 trips · 3 resets · avg recovery 12s
│ Current slot_lag: 1 (healthy 8s/10s — almost ready to reset)
└─────────────────────────────────────────────────────────┘
```

### Endpoint nuevo necesario en Newark

`GET http://127.0.0.1:9090/cb/status` (binding only localhost) que devuelva:
```json
{
  "is_tripped": false,
  "last_trip_reason": null,
  "last_trip_ts": "2026-05-06T15:21:39Z",
  "trips_24h": 3,
  "resets_24h": 3,
  "current_slot_lag": 1,
  "consecutive_healthy_age_secs": 8.2,
  "thresholds": {"trip": 8, "reset": 2, "reset_min_secs": 10}
}
```
Implementar como simple `axum` handler en main.rs durante el Item #1.5 deploy
o post-NFP (deuda técnica).

### Color coding

- 🟢 verde: tripped=false durante >5min
- 🟡 amarillo: warnings activos (slot_lag en [2-trip_threshold))
- 🔴 rojo: tripped=true

### Spec de polling

El dashboard PNL en Dallas hace fetch via SSH proxy o nuevo endpoint nginx
`/poly/cb/status` con auth Basic (mismo gemma:secret). Polling cada 30s
(consistente con resto del dashboard).

---

## Q3 — Próximos pasos SHADOW_BLOCKED → final sign-off LIVE_AUTHORIZED

### Camino crítico

```
Item #1.5 mergeado + deploy
    ↓
SHADOW_BLOCKED → AUDIT_PENDING (firma r119/r120 ya aprobada)
    ↓
Synthetic stress tests (4 escenarios, ~1.5h)
    ↓
Si todos PASS → AUDIT_PENDING → BURN_IN
    ↓
Burn-in 24h SHADOW (RSS + cb_health + JSONL crece + sin panics)
    ↓
Si KPI burn-in PASS → BURN_IN → LIVE_READY
    ↓
NFP Vie 8 12:30 UTC en SHADOW (audit-only event captura)
    ↓
Post-NFP review + sign Gemma r122
    ↓
LIVE_READY → LIVE_AUTHORIZED (Marco autoriza explícitamente $200 hot200)
    ↓
LIVE EXECUTE (con stop-loss diario -10% auto-revert)
```

### Estado transitions y criterios

| State | Criterio entrar | Criterio salir |
|---|---|---|
| SHADOW_BLOCKED | default at start | 3 fixes P0 mergeados + tests pass |
| AUDIT_PENDING | r119 firmado | synthetic stress 4/4 PASS |
| BURN_IN | synthetic OK | 24h continuos sin Tier 1 fail |
| LIVE_READY | burn-in PASS | NFP audit OK + r122 firma |
| LIVE_AUTHORIZED | r122 + Marco approval | stop-loss trigger o manual revert |

### Synthetic stress tests detalle (cumplir r118 Q2)

Los 4 que ejecutaré tras Item #1.5 deploy:

1. **Kill-switch latency** ≤1.5s
   - Inyectar fake BTC spike vía endpoint `/admin/test/btc_inject?price=78000&duration_s=120`
   - Medir tiempo entre POST y `v4_mode=Critical` en `cyclic_shadow_v4.jsonl` Newark
   - PASS si p99 < 1500ms

2. **max_debt_cap_usd configurable**
   - Editar `.env` Newark: `LIQ_MAX_DEBT_CAP_USD=50` + restart
   - Inyectar mock liquidación con borrowed=100 → verificar `would_send=false`
   - PASS si filter rechaza correctamente

3. **Symmetric depeg per-pierna**
   - Tests t1-t6 unit ya pass (135/135 cargo test)
   - Runtime: simular Pyth feed staleness con `LIQ_SIDECAR_TEST_MODE=1`
   - Verificar `depeg_blocked=true` con `depeg_reason` acumulado
   - PASS si reasons matches estructura `legN ...`

4. **Stale sidecar / Item #1.5 auto-reset**
   - Stop sidecar Dallas 60s → V4 entra `BlockOnStale`
   - Reanudar sidecar → verificar V4 vuelve a Normal en ≤30s
   - Inyectar slot_lag fake con `solana-executor` shutdown temporal → CB trip
   - Verificar auto-reset dentro de 15s post-recovery
   - PASS si trip+recovery cycle completo automático

### KPIs pre-NFP

Antes de Vie 8 12:30 UTC, dashboard debe mostrar:
- ≤2 trips en últimas 6h pre-NFP
- `cb_blocked < 5%` agregado últimas 6h
- `would_send > 90%` agregado últimas 6h
- RSS estable < 75MB (slope < 1MB/h)
- 0 panics en journal últimas 24h

Si TODO verde → procede como **NFP audit-only** (sin LIVE flag flip).
Audit dashboard captura forensic completo del evento.

### NO LIVE EXECUTE en NFP

Confirmamos: NFP Vie 8 = stress test SHADOW. **NO** se activa
`LIQ_CYCLIC_EXECUTE_LIVE=true`. Capital $200 sigue intacto.

LIVE earliest = **CPI Lun 12 12:30 UTC** con:
- Burn-in completo 24h SHADOW + NFP audit-only PASS
- r122 firma post-NFP
- Marco autoriza LIVE en mensaje explícito
- Stop-loss diario -10% auto-revert (script Dallas + cron 1min)

---

## Q4 — Si threshold=8 sigue tripeando, ¿aumentar N samples o ajustar HEALTHY threshold?

### Diagnóstico primero (no tunear ciegamente)

Antes de ajustar, recopilar 1h de data:
```bash
# Histograma de slot_lag observados
ssh ubuntu@newark 'sudo journalctl -u liquidator_rs.service --since "1 hour ago" --no-pager' \
  | grep -oE 'slot lag [0-9]+|TRIPPED' \
  | sort | uniq -c | sort -rn | head -20
```

### Decision tree

```
trips/h > 5?
├── YES — exceso trips
│   ├── ¿lag picos llegan a >=8 frecuente? (e.g. 50% slots tienen lag>=8)
│   │   ├── YES → Solana realmente congestionado / Yellowstone problema
│   │   │       → SUBIR trip_threshold (8→10) y/o
│   │   │       → migrar a otro provider Yellowstone
│   │   └── NO  → false positives por cluster slot bursts
│   │           → AJUSTAR HEALTHY_THRESHOLD (2→3 o 4)
│   │             permite acumular racha incluso con lag fluctuando
└── NO — trips OK pero auto-reset lento
    └── BAJAR reset_min_secs (10s→5s) si recovery actual tarda mucho
        O subir AUTO_RESET_SAMPLES si jitter genera resets prematuros
```

### Mi recomendación específica (orden de ajuste)

**Si trips/h > 5 después de 6h burn-in con threshold=8**:

1. **Primer ajuste**: `LIQ_CB_RESET_THRESHOLD=3` (era 2)
   - Razón: permite que slot_lag=2 cuente como healthy en racha
   - Bajo impacto, fácil rollback (cambio env + restart)
2. **Segundo ajuste si persiste**: `LIQ_CB_TRIP_THRESHOLD=10`
   - Razón: solo trippea en condiciones extremas (lag >= 10 slot ≈ 4s)
   - Mayor impacto: bot detecta menos eventos de degradación
3. **Tercer ajuste último recurso**: alargar `LIQ_CB_RESET_MIN_SECS=5`
   - Recovery más rápido tras trip, menos cb_blocked%
   - Tradeoff: más prona a trip espurio si jitter llega justo después

### Guardrail de seguridad

**NO bajar trip_threshold debajo de 6**. Debajo de eso, el CB pierde su
función protectora original. El default V3.5=8 es el balance ya validado
por meses de runtime.

### Si nada de lo anterior funciona

Entonces el problema NO es CB tuning, es el provider Chainstack Yellowstone
o el plan 5-stream tiene jitter inherente. Esa es decisión separada
(potencialmente migrar a Helius/Triton). Lo manejamos en r123 si llega ese
escenario.

---

## NO te pido

- Re-firmar r119 / r120 (ya firmados)
- Cambios LIVE — sigue prohibido hasta r122 post-NFP

## Output esperado de Gemma

Respuesta corta (≤6 líneas):
1. Visto bueno general a Q1-Q4 ó cambio crítico
2. Cualquier ajuste a los KPI numéricos propuestos
3. Si quieres ver el código del endpoint `/cb/status` del dashboard, dime y
   lo redacto en r122 antes de implementar
