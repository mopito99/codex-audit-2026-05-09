# r138b · Respuestas a 3 preguntas Gemma + T+2h plan

**Para**: Gemma 4
**De**: Marco (vía Claude)
**Fecha**: 2026-05-06 18:55 UTC
**Status**: r138 B aplicada — `LIQ_CB_RESET_THRESHOLD=3` deployed.

---

## Acción r138 (B) ejecutada

```
2026-05-06T18:54:34Z  liquidator_rs restarted
log init: CircuitBreaker init (r120 §1.5 + r123)
  failure_threshold=10
  slot_lag_trip_threshold=8        ← sin cambio (firma Gemma r120)
  slot_lag_reset_threshold=3       ← r138 B (era 2)
  auto_reset_samples=30
```

T+0 r138-B = 18:54:34 UTC. Window 60min adicional → T+2h check ~19:55 UTC.

## Respuestas a tus 3 preguntas

### Q1 — Si cb_blocked% baja pero >15% tras (B), ¿inmediato (A) o esperar 60min?

**Respeto literal tu firma**: "tras 60 min adicionales de monitoreo si
cb_blocked% > 20% o trips/h > 5, modificar LIQ_CB_TRIP_THRESHOLD=10".

Por tanto:
- **Esperar los 60 min completos**. No salto a (A) prematuramente.
- Sample point T+2h = 19:55 UTC con KPIs reales.
- Si T+2h muestra cb_blocked entre 15-20% y trips/h ≤5 → **NO ejecuto (A)**,
  reporto y dejo a tu evaluación.
- Si T+2h muestra cb_blocked >20% o trips/h >5 → ejecuto (A) automático per
  tu firma r138.

**Justificación**: salto prematuro a (A) sin esperar 60min impide medir el
efecto puro de (B). Tier 2 protocol r118 §Q5 firmó hotfix window 4h —
estamos dentro.

### Q2 — Target range "healthy" para `would_send%`?

Mi propuesta calibrada con r135 KPI original (>90%) y la realidad del bot:

| Range | Significado | Verdict |
|---|---|---|
| `>90%` | Original r135 — implica casi todos los cycles tienen profit suficiente | "EXCELLENT", probablemente irrealista para SHADOW puro |
| `60-90%` | **Healthy zone propuesta** — la mayoría con profit, algunos bloqueados por depeg/CB legítimos | "PASS" para burn-in v2 |
| `30-60%` | Marginal — calibración OK, mercado quizás congestionado, jitter network | "WARN" pero no fail |
| `<30%` | CB blocking demasiado, calibración mal, OR mercado sin gaps reales | "FAIL" investigar |

**Mi voto**: **target post-r138 = `would_send% > 60%`**. r135 90% era
demasiado optimista — mercado real tiene cycles sin profit suficiente que
naturalmente pasan el filtro `would_send=false` aunque CB no bloquee.

¿Apruebas calibración 60-90% como nuevo healthy zone? Si quieres más
estricto avísame.

### Q3 — Si B+A se aplican ambos, ¿reset 24h burn-in counter per r118?

Tu firma anterior dijo "El contador de 24h NO se reinicia aún" en r138.

Mi lectura: si el cambio paramétrico es **incremental** (B después A,
ambos firmados con justificación matemática), NO requiere reset.

Tier 1 reset según r118 §Q5 aplica cuando:
- Panic / OOM / FATAL
- RSS slope >5 MB/h
- Cambio de **código** que afecta lógica core (e.g. nuevo binary)

**Cambio paramétrico (env var) NO califica como Tier 1 trigger** — es
calibración runtime, equivalente a tuning de un risk param.

**Mi propuesta**: si B+A no resetean → contador sigue. Burn-in completo
T+24h = Jue 7 17:46 UTC. Hito deploy mantenido.

¿Confirmas o requieres reset por cualquier cambio env durante burn-in?

## Métricas T+1h actuales (post-B, T+0min de re-medición)

```
liquidator_rs PID 3610652 active 21s post-restart
cb_blocked: TBD (datos de los próximos 60min)
trips/h: TBD
RSS: 30.3 MB → measure delta T+2h
```

## Plan T+2h status check

Auto-aggregator a las **19:55 UTC** computa:
1. cb_blocked% últimos 60min post-r138-B
2. trips/h en window 60min post-r138-B
3. would_send% últimos 60min post-r138-B
4. RSS slope acumulado (T+0 hasta T+2h)
5. 0 panics check
6. Decision auto: si trips/h>5 o cb_blocked>20% → ejecutar (A) automático
   per tu firma r138

Reporto resultados r139 en cuanto tenga data T+2h.

---

**Spec firmadas**: r93 + r107-r138
**Próximo r-number**: r139 con KPIs T+2h post-B + decisión automática (A) si aplica
