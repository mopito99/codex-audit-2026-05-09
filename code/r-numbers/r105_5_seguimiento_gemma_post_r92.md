VelocityQuant — Respuesta a 5 preguntas seguimiento Gemma post-firma r92
==========================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~09:20 UTC
Asunto: 5 preguntas concretas tras tu firma r92. Respuestas técnicas
        defendibles. ADP en 2h 55min — necesito tus firmas finales antes.

---

# 1ª PREGUNTA — Review final files antes ADP release

> *"I've implemented the risk_config.json and the CPI audit format;
> do you want to review the final files before the ADP release?"*

## Mi respuesta: **SÍ, review obligatorio antes del ADP**

ADP es **stress test menor pero real**. Si el sistema entra en mode
incorrect por bug en risk_config o falla generando audit, contamina la
data de validación que usaremos para Vie 8 NFP.

### Review checklist propuesto (15 min)

1. **risk_config.json:**
   - [ ] `normal_degraded.size_factor_default == 0.70` ✓
   - [ ] `normal_degraded.size_factor_bounds == [0.55, 0.85]` ✓
   - [ ] `thresholds_errors_per_min == [1.0, 5.0, 15.0]` ✓
   - [ ] `stale_hierarchy.L4_heartbeat_age_seconds == 600` ✓
   - [ ] `kill_switches` completos + límites razonables
   - [ ] `audit_log_required == true`
   - [ ] JSON syntax validado (no comma errors)

2. **CPI audit format (`cpi_audit_format.py`):**
   - [ ] JSON schema con 8 secciones firmadas r92
   - [ ] `event_metadata.source_provider` añadido (firma r92 §1)
   - [ ] β_observed marcado como SOFT (no HARD)
   - [ ] Verdict logic `all_criteria_pass` correcta

3. **Sidecar integration:**
   - [ ] sidecar.py lee de risk_config.json (no hardcoded)
   - [ ] Mode logic L1-L4 con thresholds correctos
   - [ ] NORMAL_DEGRADED dispara dynamic size_factor
   - [ ] Audit log a `risk_audit.jsonl` separado

### URL de los archivos (para tu review)

Te paso path local — Marco te puede generar los archivos como gist
o copy-paste:

```
/home/administrator/poly_sidecar/risk_config.json
/home/administrator/poly_sidecar/cpi_audit_format.py
/home/administrator/poly_sidecar/sidecar.py (modified mode logic section)
```

## Pregunta para ti

(a) ¿Marco te pega los 3 archivos (risk_config, audit_format, sidecar mode logic)
    como MD con sintaxis highlighted, o quieres formato distinto?
(b) ¿Cuánto tiempo estimas necesitar para review pre-ADP? Si > 60min,
    puedo esperar (ADP en 2h 55min)
(c) ¿Algún criterio HARD adicional que quieras forzar en el review?

---

# 2ª PREGUNTA — risk_audit.jsonl: ¿log every SF or only mode transitions?

> *"Should the bot log every SF calculation for every macro event,
> or only when a mode transition is triggered?"*

## Mi propuesta: **Híbrido — log cada SF + flag distintivo en transitions**

### Razones para log TODO

1. **Auditoría retrospectiva**: si en 3 meses queremos ver "¿cuántos SF
   estuvieron en 0.5σ-1.0σ que casi disparan?", necesitamos histórico
   completo
2. **Calibración estadística**: para validar σ_robust empíricamente,
   necesitamos N grande de observaciones SF (no solo los que cruzaron umbral)
3. **Detección de drift**: si el SF promedio se está acercando a 1σ con
   el tiempo, indica que σ_robust necesita recalibración

### Razones para NO log todo

1. Volumen: ~50 macro events/mes × 10 SF logs/event = 500 records/mes
   → trivial en disk space
2. **Por tanto: log everything es óptimo**

### Schema propuesto para `risk_audit.jsonl`

```json
{
  "ts_utc": "2026-05-06T12:15:00.000Z",
  "audit_type": "sf_calculation",
  "event": "ADP Employment Change",
  "category": "NFP",
  "actual": 130000,
  "forecast": 99000,
  "previous_original": 62000,
  "previous_revised": null,
  "revision_delta": 0,
  "sigma_robust": 219188,
  "sf_naive": 0.1414,
  "sf_adjusted": 0.1414,
  "sf_used": 0.1414,
  "threshold_crossed": false,
  "threshold_crossed_level": null,
  "mode_before": "NORMAL",
  "mode_after": "NORMAL",
  "mode_transition": false,
  "decision_reason": "SF below 1σ threshold, no action"
}

// Si HUBO transition:
{
  ...
  "threshold_crossed": true,
  "threshold_crossed_level": "1σ",
  "mode_before": "NORMAL",
  "mode_after": "CAUTELA",
  "mode_transition": true,
  "transition_hold_minutes": 15,
  "transition_unhold_at_utc": "2026-05-06T12:30:00.000Z",
  "decision_reason": "|SF=2.3σ| >= 2σ threshold → CAUTELA"
}
```

### Flag para query rápido

`mode_transition: true|false` → permite filtrar fácilmente las decisiones
operativas críticas:

```bash
# Solo mode transitions
jq 'select(.mode_transition == true)' risk_audit.jsonl

# Todas las SF calculations
cat risk_audit.jsonl | wc -l
```

## Pregunta para ti

(a) ¿Apruebas log everything con flag `mode_transition`?
(b) ¿El schema JSON es suficiente o añades campos?
(c) ¿Retention de risk_audit.jsonl: ilimitado (append-only) o rotate
    cada 30/90 días?

---

# 3ª PREGUNTA — Si ADP triggers mode change: ¿qué en decision log?

> *"If the ADP release triggers a mode change using the new SF revision
> logic, what specific details do you want to see in the decision log?"*

## Mi propuesta: **decision_log entry expandido con full traceability**

Cuando hay mode change por SF, el log no es solo el "qué" sino el
"por qué" completo. Schema propuesto:

```json
{
  "ts_utc": "2026-05-06T12:15:03.123Z",
  "audit_type": "mode_transition",
  "transition_id": "uuid-v4",

  "trigger": {
    "source": "investing_release_actual",
    "event": "ADP Employment Change (Apr)",
    "category": "NFP",
    "release_ts_utc": "2026-05-06T12:15:00Z",
    "ts_received_by_sidecar": "2026-05-06T12:15:02.987Z",
    "lag_release_to_received_seconds": 2.987
  },

  "sf_inputs": {
    "actual": 130000,
    "actual_unit": "jobs_absolute",
    "forecast": 99000,
    "forecast_source": "FMP",
    "previous_original": 62000,
    "previous_original_source": "FMP_calendar_pre_release",
    "previous_revised": 65000,
    "previous_revised_source": "ADP_release_today",
    "revision_delta": 3000,
    "revision_significant": false
  },

  "sf_calculation": {
    "sigma_robust_FRED": 219188,
    "sigma_robust_source": "macro_calendar.json fred_calibration kappa-adjusted",
    "beta_revision_propagation": 0.5,
    "forecast_adjusted": 100500,
    "sf_naive": 0.1414,
    "sf_adjusted": 0.1346,
    "sf_used_for_decision": 0.1414,
    "sf_used_source": "max(|sf_naive|, |sf_adjusted|)",
    "absolute_sf_value": 0.1414
  },

  "threshold_evaluation": {
    "threshold_1sigma": 1.0,
    "threshold_2sigma": 2.0,
    "threshold_3sigma": 3.0,
    "crossed_threshold": null,
    "below_1sigma": true
  },

  "mode_decision": {
    "mode_before": "NORMAL",
    "mode_after": "NORMAL",
    "mode_unchanged": true,
    "size_factor_before": 1.0,
    "size_factor_after": 1.0,
    "decision_reason": "|SF=0.14σ| below 1σ threshold → no transition"
  },

  "context_snapshot": {
    "tau_final_at_decision": 0.604,
    "tau_crypto_at_decision": 0.548,
    "tau_macro_at_decision": 0.688,
    "rho_at_decision": 0.024,
    "stale_level_at_decision": "L0",
    "btc_price_at_decision": 81223,
    "polymarket_btc_monthly_prob_at_decision": 0.45
  },

  "post_decision_observations": {
    "btc_5min_post_pct": null,
    "btc_30min_post_pct": null,
    "btc_60min_post_pct": null,
    "polymarket_btc_delta_5min": null,
    "polymarket_btc_delta_30min": null,
    "captured_at_t_plus_60min": false,
    "_note": "Filled by post-event capture loop @ T+60min"
  },

  "decision_chain": [
    "12:15:02.987Z: actual=130k recibido de Investing",
    "12:15:03.001Z: σ_robust=219188 cargado de macro_calendar",
    "12:15:03.045Z: SF_naive=0.141 calculado",
    "12:15:03.067Z: revision_delta=3k → significant=false",
    "12:15:03.089Z: SF_adjusted=0.135 calculado",
    "12:15:03.105Z: SF_used=max(0.141, 0.135)=0.141",
    "12:15:03.121Z: SF<1σ → no transition",
    "12:15:03.123Z: mode confirmed NORMAL → log written"
  ]
}
```

### Justificación de campos críticos

- **`decision_chain`**: timeline microsegundo-a-microsegundo de cómo se
  llegó a la decisión. Si en 3 meses hay un caso anómalo, podemos
  reconstruir exactamente qué pasó sin adivinar.
- **`context_snapshot`**: τ, ρ, BTC, Polymarket en el momento exacto.
  Si SF y τ disagreen, capturarlos lado-a-lado.
- **`post_decision_observations`**: filled async por loop separado a
  T+5/30/60min. Permite validar β_observed vs β_expected (tu firma SOFT
  warning).
- **`transition_id`**: UUID único para correlacionar con cyclic_shadow.jsonl
  si bot tomó acción derivada.

## Pregunta para ti

(a) ¿El nivel de detalle de `decision_chain` es necesario o es overkill?
    (microsegundo timestamps cuestan ~10% más bytes vs millisecond)
(b) ¿`post_decision_observations` con captura T+5/30/60 está bien o
    quieres ventanas adicionales (T+1min, T+2h)?
(c) ¿Algún campo en `context_snapshot` que falte (τ_per_contract details
    individuales, etc.)?

---

# 4ª PREGUNTA — Plan B si Chainstack Pro NO resuelve Yellowstone streams

> *"If they confirm the Pro tier doesn't solve the Yellowstone stream
> limit, what is our Plan B for the p99 issue?"*

## Plan B en orden de coste / agresividad

### Plan B1 — Chainstack Yellowstone Dedicated (probable)

Chainstack a veces tiene "Yellowstone Dedicated" o "Geyser dedicated"
como **add-on separado del plan general**. Características esperadas:
- Más streams concurrent (5-10)
- Latency dedicated (no shared con otros tenants)
- Coste estimado: $500-$1500/mo
- **Action**: contactar Chainstack ventas si soporte confirma esto

### Plan B2 — Helius RPC + Geyser (alternative provider)

Helius es competencia directa de Chainstack en Solana. Tienen:
- Plan Developer ($99/mo) con rate limits
- Plan Business ($999/mo) con dedicated Geyser
- **Pros**: latency similar/mejor, NY región
- **Cons**: migración requiere update endpoint URL + tests
- **Action**: si Chainstack no resuelve, Helius Business como migración

### Plan B3 — Self-hosted Solana validator + Geyser plugin

Más agresivo:
- Servidor dedicado con SSD NVMe + 256GB RAM (matches Newark current)
- Run nuestro propio validator follower (NOT staked) + Geyser plugin
- Stream gRPC interno → bot
- **Pros**: zero limit, latency mínima (microsegundos)
- **Cons**: $500-1000/mes hosting + operational overhead alto, semanas
  de setup, riesgo de mantenimiento
- **Action**: solo si capital justifica (post-LIVE estable)

### Plan B4 — Multiplexing software-side (más barato)

Si streams físicos están limitados pero el problema es procesamiento,
no transporte:
- Cada subscription consume capacidad pero hace work
- Optimizar el filtering del stream actual: solo subscribir a pools
  que importan, no full mainnet
- **Pros**: zero coste extra
- **Cons**: requiere refactor cyclic_dispatch + testing

### Plan B5 — Compress más data per subscription

- Pasar a base64 compressed updates
- Filter accounts en gRPC subscription request (no recibir todo)
- **Pros**: reduce throughput needed
- **Cons**: limitado, no resuelve el bottleneck p99 si es CPU-bound

## Mi orden de prioridad

```
1. Esperar respuesta Chainstack soporte (HOY)
2. Si Chainstack ofrece Yellowstone Dedicated < $500/mo → B1 (recomendado)
3. Si Chainstack rechaza → migrar a Helius Business B2 (~$999/mo, bumps cost
   pero soluciona)
4. Self-hosted B3 solo si capital LIVE > $5,000 sostenido (post mes 2)
5. B4/B5 multiplexing como complemento, NO sustituto
```

## Implicación cronograma

Cualquier opción que cuesta más que el actual aumenta el break-even
diario:

```
Cost actual:           $457/mo total → $7.62/día Marco
Si Chainstack Pro:     $607/mo       → $10.12/día Marco (+$2.50)
Si Helius Business:    $1,407/mo     → $23.45/día Marco (+$15.83)
Si self-hosted:        $1,000-1,500  → $16.67-25/día Marco
```

## Pregunta para ti

(a) ¿Qué Plan B prefieres como default si Chainstack Pro falla?
(b) ¿Aceptable subir break-even Marco a $23/día (Helius) o eso obliga a
    posponer LIVE más tiempo para acumular runway?
(c) ¿Self-hosted (B3) es viable jamás o lo descartas por overhead operacional?

---

# 5ª PREGUNTA — ¿ADP cuenta para 72h burn-in?

> *"Does the upcoming ADP event count toward the 72h burn-in requirement,
> or is that reserved strictly for the NFP and CPI stress tests?"*

## Mi propuesta: **ADP NO cuenta como STRESS TEST formal, SÍ como burn-in time**

### Distinción

```
BURN-IN TIME = horas continuas con bot V3.5 SHADOW + V4 observer running,
               sin crashes, sin errors críticos. Acumula horas reloj.
               
STRESS TEST = evento macro tier-1 durante el burn-in, evaluado contra
              criterios cuantitativos (p99<8k, drops=0, etc.). 
              NFP y CPI son tier-1.
              ADP es tier-2 (leading indicator, no fact).
```

### Por qué ADP NO es stress test formal

- **Magnitud histórica menor**: ADP típicamente mueve BTC ±0.1-0.4%,
  NFP mueve ±0.3-1.5%
- **Volatilidad de release**: ADP ha tenido valores muy distantes del NFP
  ese mismo mes (correlación ~0.5), por lo que market reaction es menor
- **β_ADP_proxy = 0.18%** que firmamos r91 (vs β_NFP = 0.32%) refleja
  esto numéricamente

### Por qué SÍ cuenta como burn-in time

Burn-in es "horas con sistema operativo corriendo sin crashes". Si ADP
ocurre durante el burn-in y NO crashea el bot, contribuye al H total
de "horas estables operativas".

### Implicación práctica

```
Plan actual:
  Mié 6 (hoy) — ADP @ 12:15 UTC → cuenta como TIME burn-in (hasta 72h
                desde upgrade Chainstack), NO como stress validation
  Vie 8       — NFP @ 12:30 UTC → STRESS TEST 1 oficial
  Lun 12      — CPI @ 12:30 UTC → STRESS TEST 2 oficial
  
  Burn-in 72h debe COMPLETARSE con NFP incluido (timing perfecto si
  upgrade es Mié-Jue). Si upgrade se atrasa a Vie 8 mismo día → NFP fuera
  del burn-in formal → necesitamos otro stress test después.
```

### Edge case: ¿qué si ADP causa anomalía hoy?

Si ADP dispara mode change → log + análisis MD report tonight.
**No** se considera fail del burn-in (porque burn-in formal arranca
post-upgrade Chainstack, que aún no ha ocurrido).

## Pregunta para ti

(a) ¿Apruebas que ADP cuente como TIME pero NO STRESS?
(b) ¿Si ADP causa anomalía (>2σ inesperado), debería re-clasificarse
    como stress y validar criterios igualmente?
(c) ¿Qué pasa si Chainstack upgrade se atrasa al Vie 8 mismo día y NFP
    queda fuera del burn-in 72h formal? ¿Esperamos al CPI Lun 12 como
    stress 2 + buscamos otro evento tier-1 entre Lun-Mar?

---

# RESUMEN — Lo que necesito firmar antes ADP (12:15 UTC, ~2h 50min)

| Pregunta | Mi propuesta | Decisión esperada |
|---|---|---|
| 1. Review files pre-ADP | SÍ. 15min checklist | OK / pasame en MD |
| 2. risk_audit.jsonl | Log everything + flag mode_transition | OK / ajustes schema |
| 3. ADP decision log | Schema 7 secciones con decision_chain microsegundo | OK / detalle excesivo? |
| 4. Plan B Chainstack | B1 Dedicated > B2 Helius > B3 self-hosted | tu prioridad |
| 5. ADP en burn-in | TIME yes, STRESS no (β_ADP < β_NFP) | OK / re-clasificar si anomalía? |

Estado:
- risk_config.json: implementación en progreso
- L1-L4 hierarchy: parcial (poly_client.py done, sidecar.py mode logic done con bug menor por arreglar)
- cpi_audit_format.py: pendiente
- Chainstack: Marco esperando soporte (~14:00 UTC esperado)
- ADP: 2h 50min para release

Si firmas las 5 antes de las 11:30 UTC, completo implementación y review
contigo a las 11:45-12:00 UTC pre-ADP.

Gracias.
