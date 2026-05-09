# r139 · Burn-in T+10h45min — KPIs + decisión calibración

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 04:35 UTC
**T+10h45min post-burn-in (T+0=2026-05-06T17:46:14Z)**
**T+9h41min post-r138-B (LIQ_CB_RESET_THRESHOLD=3 desde 18:54:34Z)**

---

## TL;DR (5 líneas)

Estabilidad **PASS** (RSS slope +0.08 MB/h excelente, 0 panics, V4 uptime
9h36min sin restarts). **Calibración FAIL** persistente: cb_blocked=77.7%,
would_send=17.6%, trips/h=31.8. La acción A automática (TRIP=10) que
firmaste en r138 **NO se ejecutó** (wakeup falló silencioso). Antes de
aplicar A te traigo distribución slot_lag observada — sugiere que TRIP=10
quizás no basta. Pido firma de calibración informada por data.

## Estabilidad ✅

```
RSS span 10.72h: initial=29.8MB → final=30.6MB
RSS slope: +78 KB/h (+0.08 MB/h)
  Criterio Gemma <1MB/h: ✅ PASS (margen 12×)
  Tier 1 threshold <2MB/h: ✅ PASS (margen 24×)
0 panics, 0 FATAL, 0 OOM
V4 binary uptime continuo: 9h36min PID 3610652
CB recovery funcional: 382 trips → 376 auto-resets (98.4% recovered)
```

## Calibración ❌

```
cb_blocked%:  77.7% (criterio post-r138 healthy <15%)
would_send%:  17.6% (criterio r138b firma <30% = FAIL zone)
trips/h:      31.8  (criterio firma r138 <5 = trigger A)
cb_tripped at sample: 77.6%
```

## Datos forenses — distribución slot_lag observada (5000 cycles recientes)

```
n=5000  min=0  max=63
p50=3   p75=8   p90=16   p95=22   p99=38

Histograma:
  [ 0- 1]: 1536 (30.7%) ###############
  [ 1- 2]:  519 (10.4%) #####
  [ 2- 3]:  403 ( 8.1%) ####
  [ 3- 5]:  556 (11.1%) #####
  [ 5- 7]:  416 ( 8.3%) ####
  [ 7- 8]:  179 ( 3.6%) #
  [ 8-10]:  295 ( 5.9%) ##  ← TRIP zone con threshold=8
  [10-15]:  486 ( 9.7%) ####
  [15-30]:  506 (10.1%) #####
```

**Lectura**: 25.7% de los samples tienen `slot_lag >= 8` (= trip rate).
El threshold 8 actual es esencialmente p75 — diseñado para tripping
**solo en el peor cuartil**, pero la realidad muestra que el 25% peor está
muy por encima del threshold (p90=16 ≈ 2× threshold).

## Implicaciones cuantitativas de cada threshold

| TRIP threshold | % samples >= threshold | trip-rate proyectado | cb_blocked proyectado |
|---|---|---|---|
| 8 (actual r120) | 25.7% | ~32 trips/h | ~78% (observado) |
| **10 (firma A r138)** | 19.7% | ~24 trips/h | ~70% (mejora marginal) |
| 15 | 12.3% | ~15 trips/h | ~50% |
| 20 | 6.5% | ~8 trips/h | ~30% |
| 22 (p95) | 5.0% | ~6 trips/h | ~25% |
| 25 | 3.5% | ~4 trips/h | ~18% |

**Para target cb_blocked<15% (criterio post-r138)**: necesitaríamos
TRIP_THRESHOLD ≈ **25** (>p95 de la distribución observada).

## Implicaciones de seguridad

- TRIP=8 fue spec original V4 (firmado r120) más conservador que V3.5=8.
- Subir a 10 (firma r138) = aceptar lag >= 10 como "normal jitter".
- Subir a 25 = aceptar Solana network bursts hasta 4s lag sin tripping.

**Trade-off**: cuanto más permisivo el threshold, más oportunidades capturadas
(would_send sube), pero menos protección contra degradación real de la red
durante eventos macro (NFP).

## Por qué wakeup automático falló (no es trivial)

Schedulé wakeup a 19:54 UTC vía ScheduleWakeup tool del runtime. No
disparó. Posibles causas:
- ScheduleWakeup en /loop dynamic mode requiere conversación activa
- El runtime de Claude Code no garantiza wakeups durante 10+ horas idle
- Hubo desconexión de la sesión Claude

**Operacionalmente**: para burn-in 24h NO puedo confiar en mis wakeups —
necesitamos systemd timer o cron Dallas con script que aplique acción A
automáticamente o bien Marco vigilando directamente.

## 4 preguntas concretas a Gemma — qué ajustar

### Q1 — Aplicar A literal (TRIP=10) o más agresivo basado en data?

Según distribución observada, **TRIP=10 NO bajará cb_blocked al target
<15%**. Mi proyección: ~70% (improvement marginal). 4 opciones:

- (a) Aplicar A literal `TRIP=10` (per tu firma r138). Aceptar mejora
  marginal y seguir burn-in. Re-evaluar T+1h post.
- (b) Aplicar `TRIP=15` (cubre p87.7 de la distribución). Proyección
  cb_blocked ~50%. Más alineado con datos reales.
- (c) Aplicar `TRIP=22` (= p95). Proyección cb_blocked ~25%, alineado con
  criterio healthy <15% con cierto margen.
- (d) Aplicar `TRIP=25` (>p95 + margen). Proyección cb_blocked <15% target.

### Q2 — También subir RESET_THRESHOLD?

Currently `RESET=3`. La racha "healthy" requiere 30 samples consecutivos
con `slot_lag < 3`. Pero p50=3, **el 50% de samples están >=3** y rompen
la racha. Esto explica por qué auto-reset toma tanto en consolidar.

Propongo `LIQ_CB_RESET_THRESHOLD=5` (p50<5 entonces 50% de samples cuentan
como healthy, racha se acumula 2× más rápido).

### Q3 — Reset burn-in 24h al aplicar nuevos thresholds?

Si A=literal (TRIP=10) → cambio incremental, NO reset (consistente con tu
firma r138 sobre cambios paramétricos).

Si A=agresivo (TRIP=22 o 25) → es un cambio mayor de calibración. ¿Reset
contador o acumular?

Mi voto: **NO reset incluso para cambios mayores** — son tuning de safety
threshold sobre código firmado, no cambio de lógica core. El RSS slope
+0.08 MB/h ya validó estabilidad fundamental durante 10h45min.

### Q4 — Recalibrar would_send% target?

Con TRIP nuevo (10/15/22/25), el cb_blocked baja → would_send sube
mecánicamente. Pero **no necesariamente al 60% target r138b**.

Propongo medir post-cambio sin pre-juzgar: si tras 1h post-A el
would_send queda en 30-50% → conditional PASS Tier 2. Si <30% → FAIL real
(otra causa, no CB).

¿Apruebas medición post-A antes de decidir would_send target final?

## Mi recomendación honesta

**Q1: opción (c) TRIP=22**. Razones:
- Alineado con p95 distribución real observada
- Proyección cb_blocked ~25% (zona Tier 2 conditional pass)
- Aún protege contra catastrofic events (lag >22 = >9s atraso, definitivamente
  network degradation real)
- TRIP=10 (a) probablemente trae siguiente round de "still failing"
- TRIP=25 (d) es óptimo pero conservador para baseline; mejor empezar 22

**Q2: SÍ subir RESET=5** complementariamente.

**Q3: NO reset burn-in counter** (tuning paramétrico).

**Q4: medir post-cambio**, decidir target real con data.

NO toco nada hasta tu firma. Capital intacto $200.

---

**Spec firmadas previas**: r93 + r107-r138
**Estado**: AUDIT_PENDING — burn-in en curso pero calibración fail
**Próximo r-number**: r140 con tu firma de calibración
**Cronograma**: ventana deploy V4-Alpha **Jue 7 17:46 UTC** (T+24h end) sigue alcanzable si calibración converge en próximas 2-3h
