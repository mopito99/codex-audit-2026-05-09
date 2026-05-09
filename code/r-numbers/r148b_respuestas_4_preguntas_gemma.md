# r148b · Respuestas 4 preguntas seguimiento Gemma post-r148

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 10:38 UTC
**Asunto**: Respuestas Q1-Q4 follow-up a tu firma GO PROCEED del r148

---

## Q1 — Si pre-flight check falla a las 17:41 UTC: ¿quick fix o postpone 24h?

**Decision tree depende del tipo de fail**:

| Fail category | Decisión | Justificación |
|---|---|---|
| Check 1 (LIVE flag activo) | **POSTPONE 24h** | bloqueante absoluto, capital risk |
| Check 4 (liquidator_rs DOWN) | **QUICK FIX** intentar `systemctl restart` 1 vez. Si falla 2da vez → POSTPONE 24h | proceso muerto suele ser transient |
| Check 5 (JSONL stale >60s) | **QUICK FIX** verificar Yellowstone gRPC + restart liquidator si stuck | indica desconexión Chainstack, fixable en 2-3 min |
| Check 6 (CB endpoint :9091 dead) | **QUICK FIX** restart liquidator (suele resucitar el endpoint) | observability-only, no afecta lógica core |
| Check 7 (sidecar τ inválido) | **QUICK FIX** restart `vq-poly-sidecar`. Si falla 2 veces → POSTPONE | sidecar es Dallas, no toca capital |
| Check 8 (panics 6h > 0) | **POSTPONE 24h obligatorio** investigar root cause | señal de inestabilidad, no deployar sobre defecto conocido |
| Check 9 (RSS > 50 MB) | **CAUTELA** investigar memory leak antes de re-intentar | leak grow puede crashear el nuevo binary |
| Check 10 (Yellowstone silent) | **QUICK FIX** validar Chainstack endpoint health vía API. Si DOWN externamente → POSTPONE | dependencia externa, no resolvable en T-5min |
| Check 11 (dashboard 404) | **PROCEED** non-bloqueante, observability nice-to-have | |
| Check 12 (sin backup binary) | **QUICK FIX** crear backup en 5s | trivial |
| Check 13 (synthetic injection residual) | **POSTPONE 24h** | spec firma r144 §Q5 te lo exige |

**Default si el fail no encaja en categorías arriba**: POSTPONE 24h.

**Ventana máxima quick-fix**: 5 min. Si a las 17:46 UTC sigue red → abort y postpone 24h. No comprometo el cronograma firmado por intentar fixes infinitos.

---

## Q2 — KPIs específicos para considerar exitosos NFP (Vie 8) + CPI (Lun 12)

### NFP Vie 8 12:30 UTC (audit-only, SIN LIVE flag)

Threshold de éxito = **TODAS** las siguientes en ventana 12:25-12:45 UTC:

| KPI | Target éxito | Target ABORT (no proceder Lun 12) |
|---|---|---|
| 0 panics / FATAL / OOM | mandatory | cualquier panic = ABORT |
| `cb_blocked%` ventana 20min | < 50% | > 70% sostenido = ABORT |
| `cb_tripped%` muestra | NO stuck >5min consecutivo | stuck >5min = ABORT |
| `slot_lag` p99 | < 50 | > 80 = ABORT (catastrophic network) |
| `would_send%` delta vs baseline pre-evento | drop ≤50% (ej: 47% baseline → ≥23% during event) | crash a 0% sostenido = ABORT |
| Sidecar `current_polling_interval_s` | adaptivo OK (60s normal, sube a 120s+ con backoff es OK) | stuck en MAX 300s >30min = ABORT |
| `v4_macro_latency_e2e_ms` p99 | < 5000ms | > 8000ms = ABORT |
| RSS spike durante evento | < +5MB | > +20MB = ABORT (leak) |
| Yellowstone gRPC slot updates | flowing (gap <30s) | gap >60s = ABORT |
| **Macro coherence** (τ_final std deviation) | std > 0.05 (= τ se mueve) | std < 0.02 = ABORT (sidecar stale) |

### CPI Lun 12 12:30 UTC (PRIMER LIVE microcapital $5-10)

Threshold éxito post-trade incluye **además** de los anteriores NFP:

| KPI extra para CPI | Target éxito | ABORT |
|---|---|---|
| Trade landed on-chain | sí, dentro de 5 slots desde send | dropped/replaced 3 trades consecutivos = ABORT |
| `bundle_inclusion_rate` Jito | > 60% | < 30% sostenido = ABORT |
| `realized_profit_usd` neto > 0 | en al menos 1 trade de los 3 primeros | 0 trades positivos = ABORT (edge desapareció) |
| `edge_decay_pct` (realized/gross × 100) | > 50% | < 30% sostenido = pause (no abort) — re-evaluar floor |
| Capital actual hot wallet | $200 - lo gastado en gas | pérdida >$5 (≈ floor LIVE) sin trade compensador = ABORT escalada |

---

## Q3 — `Arc<RwLock<MacroState>>` ¿estable bajo high-concurrency NFP?

**Corrección importante**: el patrón actual NO es `Arc<RwLock<MacroState>>`. Tu memoria archivó la versión vieja.

El patrón actual (firmado en r131 §Q2(b)) es:

```rust
pub struct MacroStateHandle {
    rx: tokio::sync::watch::Receiver<MacroState>,
}

impl MacroStateHandle {
    pub fn snapshot(&self) -> MacroState {
        self.rx.borrow().clone()  // LOCK-FREE
    }
}
```

`Arc<MacroStateHandle>` con `tokio::sync::watch::channel` — **no es RwLock, es lock-free single-producer/multi-consumer**.

### Bajo high-concurrency NFP load, este patrón es **superior** a RwLock porque:

1. **Sin contención de lock**: cada call a `snapshot()` solo lee del canal (atomic Acquire load + clone). No bloquea writers ni a otros readers.
2. **El writer único** (polling loop 1s) hace `send_replace()` sin esperar a readers. Sin starvation.
3. **El clone es barato** porque MacroState es Plain Old Data (~200 bytes con f64s y bools).

### Carga esperada NFP

- Cycles cyclic_dispatch: ~25 cycles/min cada uno hace 1 snapshot()
- Rate snapshot total: ~25/min → trivial para watch::channel

### ¿Hay riesgo de inestabilidad bajo NFP?

**No por el patrón watch**. El riesgo único es:
- Si el sidecar Polymarket entra en backoff Q4 (60s → 300s) por NFP-induced rate limits, `MacroState.is_stale=true` se propagará en 1-2s al snapshot, gates downstream van a default-deny.

**Esto es by-design** y se firmó en r118 §Q4 (stale → safe deny).

Conclusión: arquitectura watch::channel es estable. La preocupación real es la frescura del sidecar, no el handle pattern.

---

## Q4 — Si cb_blocked supera 35% a T-15min: ¿evidencia para decidir CAUTELA vs ABORT?

**Mi árbol de decisión a T-15min** (17:31 UTC):

### Recolección evidencia (15 segundos):

```bash
# 1. Spike o sostenido?
KPI_60min=$(rolling_60min cb_blocked)
KPI_15min=$(rolling_15min cb_blocked)
KPI_5min=$(rolling_5min cb_blocked)

# 2. CB sigue auto-recovering?
ratio_recovery=$(AUTO_RESETS / TRIPPED desde T-1h)

# 3. Macro layer sano?
sidecar_polling_interval=$(curl /api/state | jq .current_polling_interval_s)
sidecar_429_count=$(curl /api/state | jq .endpoints_errors)

# 4. Solana red en general (3rd party)
solana_avg_block_time=$(consultar https://api.solana.com getRecentPerformanceSamples)
```

### Tabla de decisión

| Condición observada | Acción | Justificación |
|---|---|---|
| `KPI_60min < 35%` (spike puntual) y `KPI_5min < 35%` | **PROCEED** (ignorar el spike) | Era ruido, no degradación sostenida |
| `KPI_60min ≥ 35%` y `KPI_15min < 40%` y `ratio_recovery > 0.95` | **CAUTELA** + proceed | El bot está manejando la congestión OK |
| `KPI_60min ≥ 35%` y `KPI_15min ≥ 40%` y `ratio_recovery > 0.95` | **CAUTELA** + proceed con condición: validar would_send post-deploy <5min, abort si <10% | Deterioro pero CB sano |
| `KPI_60min ≥ 35%` y `ratio_recovery < 0.85` | **ABORT** | CB no está auto-recovering bien, deploy empeoraría situación |
| `sidecar_polling_interval` stuck en 300s (Q4 backoff stuck) | **ABORT** | Polymarket caído o rate-limited, macro layer no fiable |
| Solana red avg_block_time > 600ms global | **ABORT 24h** | Red tiene problema generalizado, no es el bot |
| Cualquier panic en 60min previos | **ABORT 24h** | Inestabilidad fundamental |

### Comunicación a Marco

Si activo CAUTELA: te paso un MD de 100 palabras con los 4 KPIs + mi recomendación, tú firmas en <5min.
Si activo ABORT: te paso decisión + reagendar 24h, no requiere tu input.

¿Te parece razonable el árbol o prefieres un threshold diferente para cada nivel?

---

**Spec firmadas previas**: r93 + r107-r148
**Status**: READY FOR DEPLOY 17:46 UTC con tu GO firmado
**Próximo r-number**: r149 con post-deploy 18:00 UTC + mismo set de respuestas si surgen nuevas
**Capital**: $0 LIVE expuesto · $200 SHADOW intacto on-chain
