# r137 · Burn-in 24h T+1h status check — KPIs reales

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 18:48 UTC
**T+1h tras burn-in start (T+0 = 17:46:14 UTC)**

---

## TL;DR

T+62min de burn-in. **KPIs mixtos: 2/4 PASS, 2/4 FAIL importante**:

| KPI | Criterio r135 | Observado | Verdict |
|---|---|---|---|
| RSS slope | < 1 MB/h (Tier 1 fail si >2) | **+0.41 MB/h** | ✅ PASS |
| 0 panics / FATAL | mandatory | **0** | ✅ PASS |
| cb_blocked% | < 5% sostenido | **88.9%** (56/63 samples) | ❌ **FAIL Tier 1** según r135 |
| would_send% | > 90% sostenido | **6.3%** (4/63 samples) | ❌ **FAIL Tier 1** según r135 |

**Sistema funcional pero CB stuck en trip-loop**. Pido tu firma sobre cómo
proceder.

## Detalle KPIs

### Memoria (PASS)

```
RSS initial:  29.8 MB  (T+0)
RSS final:    30.3 MB  (T+62min)
Span:         61.8 min
Slope:        +423 KB/h = +0.41 MB/h
Criterio Gemma r123: <1024 KB/h ✅ PASS (margen ~60%)
Tier 1 threshold:    <2048 KB/h ✅ PASS
```

### CB recovery (orgánico funcional)

```
journalctl 60min: TRIPS=18 AUTO-RESETS=17
1 currently tripped esperando 30 healthy samples
Mean trips/h: 18 ← muy alto vs criterio r135 "<6/24h"
```

### Process health

```
V4 uptime: 4150s (69min) — sin restart
0 panics, 0 FATAL en journal
0 OOM kills
Process active continuamente
```

### CB trip frequency = bottleneck principal

18 trips en 60min = **1 trip cada 3.3 minutos**. Cada trip toma ~30s en
auto-resetear (12s de 30 healthy samples × 400ms/slot). Total trip-time:
18 × 30s = ~9min de los 62min en estado trip → eso es **15% downtime**.

PERO observamos `cb_blocked=88.9%`. Esto NO es solo SlotLag trip — quizá
también:
- Cycles registrados durante warning zone (slot_lag 2-7, no trip pero CB
  warning)
- Reflexión del `would_send` rule downstream que también checa otros gates
- O `cb_blocked` field en cyclic_shadow.jsonl tiene semántica más amplia
  que solo `is_tripped`

**Necesito investigar** la semántica exacta de `cb_blocked` field.

## Lectura honesta

Según protocolo r118 §Q5 + criterios r135:

```
cb_blocked > 50% durante 1h continua → Tier 1 FAIL
  → revert SHADOW_BLOCKED, RCA, restart contador 24h
```

Estamos a 88.9% → **técnicamente Tier 1 FAIL**.

Pero también:
- Sistema FUNCIONA (no crashes, RSS estable, 0 panics)
- El "bloqueo" es por slot_lag fluctuating cerca del threshold 8 — no
  representa daño LIVE (en LIVE estos cycles simplemente no se ejecutan,
  capital intacto)
- El auto-reset funciona (17/18 trips ya recovered, 1 pending normal)

## Hipótesis del bottleneck

El `LIQ_CB_TRIP_THRESHOLD=8` que firmaste en r120 puede ser **demasiado
sensible** para la condición real de Newark↔Solana network HOY. Slot_lag
fluctúa naturalmente 0-8 en horas pico. Cada vez que toca 8, trip.

**Opciones**:
- (a) Subir `LIQ_CB_TRIP_THRESHOLD=10` (firma r121 §Q4 condicional: "Si trips/h >
  5 después de 6h burn-in con threshold=8: subir a 10"). Estamos a 18/h.
- (b) Subir `LIQ_CB_RESET_THRESHOLD=3` (era 2). Permite acumular racha
  healthy más fácil con jitter normal.
- (c) Aceptar trip-loop como característica normal en SHADOW (Tier 2 conditional
  PASS) y proceder NFP audit-only Vie 8 — los 18 trips son data útil.
- (d) Tier 1 FAIL → revert + RCA profundo del slot_lag observed distribution
  + decidir thresholds basado en data real.

## Mi recomendación honesta

(b) PRIMERO seguido de (a) si persiste — exactamente el orden firmado
en r121 §Q4 cuando dijiste "RESET_THRESHOLD primero (bajo riesgo)".

Pero NO ejecuto sin tu firma. Ventana 21:05 UTC (~2h 17min restantes).

## Estado capital + sistema

```
hot200: $200 USDC INTACTO (SHADOW)
V4 binary: active, recibiendo state válido
sidecar Dallas: τ=0.36, btc=$81k, fluyendo OK
cyclic_shadow.jsonl: crece (cycles entrando incluso con cb_blocked)
RSS estable
```

NO toco nada hasta tu firma A/B/C/D.

---

**Spec firmadas previas**: r93 + r107-r136
**Próximo r-number**: r138 con tu decisión
