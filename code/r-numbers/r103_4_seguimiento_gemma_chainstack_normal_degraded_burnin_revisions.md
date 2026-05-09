VelocityQuant — Respuesta a las 4 preguntas seguimiento Gemma post-firma r91
==============================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~05:55 UTC
Asunto: 4 preguntas concretas tras tu firma r91. Respuestas técnicas
        defendibles con datos. Cada una operativa, no narrativa.

---

# 1ª PREGUNTA — Métricas gRPC para confirmar p99 fix post-Chainstack upgrade

> *"What specific metrics should I monitor in the gRPC logs to confirm
> the p99 issue is resolved?"*

## Métricas críticas (capa Yellowstone gRPC)

### Métricas de salud del stream

| Métrica | Threshold actual | Target post-upgrade | Cómo capturar |
|---|---|---|---|
| **stream_reconnect_events_per_hour** | desconocido | < 1/h | tracing log `grpc::reconnect` |
| **subscription_lag_slots** | desconocido | < 5 | calcular `latest_slot_chain - latest_slot_received` |
| **bytes_per_second_inbound** | ? | estable, sin gaps > 500ms | iftop / ss |
| **updates_received_per_second** | ? | sostenido > 50 | counter en grpc.rs |
| **stream_idle_seconds** | desconocido | < 1.0 | tiempo desde último update |
| **decode_errors_count** | ? | 0 | counter en pool_state::decode |

### Métricas de procesamiento del bot

| Métrica | Threshold actual | Target | Cómo capturar |
|---|---|---|---|
| **mpsc_channel_depth** | desconocido | < 100 sostenido | tokio metrics + telemetry |
| **scan_tick_duration_p99** | ~17,000 ms | < 5,000 ms | `telemetry.record_scan_duration` ya existe |
| **quote_to_record_p99** | desconocido | < 50 ms | `telemetry.record_quote_to_record` ya existe |
| **back_pressure_drops** | desconocido | 0 | counter cuando bounded(1000) llena |

### Métricas de salud del proceso

```
- CPU usage % (top -p $bot_pid): debe ser < 70% sostenido
- RSS memory: estable, sin growth > 50 MB/h
- File descriptors: estable < 1024
- io_wait %: < 10%
```

## Plan de validación post-upgrade (en orden)

```
T+0:    Upgrade Chainstack tier (2-stream)
T+5min: Restart liquidator_rs.service (graceful)
T+30min: Verificar reconnect_events = 0, stream_idle_max < 2s
T+1h:   Verificar p99 scan_tick_duration por hora
T+4h:   p99 < 5,000ms sostenido en al menos 3 ventanas horarias
T+12h:  Comparar p99 Asia vs LDN×NY vs NY post-LDN
        (si Asia sigue alto → no era Chainstack, es otro problema)
T+24h:  Veredicto: ¿upgrade resolvió issue o necesitamos diagnóstico extra?
```

## Pregunta para ti

(a) ¿La métrica primaria para "fix confirmado" es **scan_tick_duration_p99 < 5,000ms sostenido 24h**, o quieres umbral más estricto?
(b) ¿Aceptas comparar pre-upgrade vs post-upgrade con baseline de los datos de los últimos 7 días del JSONL, o requieres ventana específica?

---

# 2ª PREGUNTA — NORMAL_DEGRADED: size_factor 0.7 constante o dinámico

> *"Should the size_factor = 0.7 be a hard-coded constant in the spec
> or a dynamic parameter I can tune?"*

## Mi propuesta: **Dinámico con bounded range + default 0.7**

### Motivos para dinámico

1. **Tu firma del 0.7** es sensata para el escenario "L1 error rate moderado"
2. Pero en realidad hay variabilidad dentro de L1:
   - 5 errors 404/5min (recién detectado markets vencidos): impacto bajo
   - 50 errors 404/5min (Polymarket teniendo problemas masivos de routing): impacto alto
3. Constante hardcoded pierde esta granularidad

### Implementación propuesta

```python
def normal_degraded_size_factor(l1_errors_per_minute: float) -> float:
    """
    Size factor para mode NORMAL_DEGRADED.
    Base 0.7 (firmado Gemma r91 2026-05-06).
    Adaptive en rango [0.55, 0.85] según severity de L1.
    """
    BASE = 0.70           # Gemma signed default
    MIN_FACTOR = 0.55     # cap inferior — más conservador en degradación severa
    MAX_FACTOR = 0.85     # cap superior — más relajado en L1 leve

    # Curva: a más errors L1, más reducción
    if l1_errors_per_minute < 1.0:
        return MAX_FACTOR  # 0.85 si <1 error/min sostenido
    if l1_errors_per_minute < 5.0:
        return BASE        # 0.70 (default Gemma)
    if l1_errors_per_minute < 15.0:
        return 0.60        # más conservador
    return MIN_FACTOR      # 0.55 si error rate muy alto
```

### Ventajas

- Default 0.7 si error rate "típico" (cubre tu firma)
- Más restrictivo si severity L1 sube
- Más permisivo si error rate baja (un solo market vencido)
- Bounded — nunca fuera de [0.55, 0.85]

### Configurable via macro_calendar.json

```json
"normal_degraded": {
  "base_size_factor": 0.70,
  "min_size_factor": 0.55,
  "max_size_factor": 0.85,
  "l1_error_rate_thresholds": [1.0, 5.0, 15.0]
}
```

→ Tú puedes ajustar los thresholds o el rango sin recompilar.

## Pregunta para ti

(a) ¿Apruebas dinámico con bounded [0.55, 0.85] y default 0.70?
(b) ¿O prefieres mantener constante 0.70 hard-coded en la spec hasta tener
    data empírica que justifique adaptive?
(c) Si dinámico, ¿los thresholds [1.0, 5.0, 15.0] errors/min son razonables
    o calibras otros?

---

# 3ª PREGUNTA — Post-upgrade p99 < 5,000ms: ¿LIVE inmediato o burn-in?

> *"If the p99 drops below 5,000ms after the upgrade, will we reconsider
> the Dom 25 LIVE block immediately or do we need a specific burn-in
> period?"*

## Respuesta: **Burn-in 72h obligatorio post-upgrade antes de reconsiderar LIVE**

### Argumento

Un dato p99 < 5k inmediato post-restart NO es señal de fix sostenido. Razones:

1. **Cold start effect**: bot recién arrancado tiene caches vacíos, queues
   pequeñas. El p99 es engañosamente bueno los primeros 30-60min.
2. **Rolling window pequeño**: necesitas N≥100k samples para que p99 sea
   estadísticamente confiable. Bot a 5 evts/seg → 100k = ~6h mínimo.
3. **Eventos macro no cubiertos**: si NFP no ocurre durante el burn-in,
   no hemos validado bajo stress real.
4. **Regression risk**: una optimización Chainstack puede tener side-effects
   que aparecen solo en sustained operation.

### Criterios de burn-in propuestos (todos AND)

```
Duración mínima:               72h continuas post-upgrade
N samples mínimo:              500,000 cycles V3.5 SHADOW
Eventos macro incluidos:       ≥1 release tier-1 (NFP, CPI, FOMC, ISM)
p99 sostenido < 5,000ms:       sí, en TODAS las ventanas UTC
p99 max en ventana 1h:         < 8,000ms (no spikes raros)
slot_lag p95 < 10:             en TODAS las ventanas
0 reconnect events:            o si hubo, recovery < 30s
0 back_pressure drops:         mpsc channel nunca lleno
```

### Cronograma propuesto (post-firma)

```
T+0:    Marco autoriza upgrade Chainstack (CO$T)
T+0:    Upgrade aplicado + restart bot
T+72h:  Audit completo de burn-in
        Si TODOS criterios pass → reconsidera LIVE Dom (revisar fecha)
        Si CUALQUIER criterio fail → más burn-in / debug
```

### Si Vie 8 NFP cae dentro del burn-in (alta probabilidad)

NFP es excelente stress test:
- Sirve como uno de los criterios "≥1 release tier-1"
- Si bot mantiene p99 < 5k durante el spike → fix robusto
- Si bot tiene p99 spike → fix incompleto

## Pregunta para ti

(a) ¿72h burn-in es razonable o requieres más (e.g. 7 días)?
(b) ¿Si NFP del Vie 8 + CPI del Lun 12 ambos pasan stress test sin p99 spike,
    consideras eso suficiente para LIVE Dom 25?
(c) ¿O prefieres añadir 7 días burn-in adicionales tras CPI antes LIVE?

---

# 4ª PREGUNTA — ADP JSON: revisiones al previous data

> *"For the ADP JSON, if there is a significant revision to the
> previous month's data, how should that be factored into the SF
> calculation?"*

## Contexto del problema

ADP a las 12:15 UTC publica:
- `actual_april` (jobs creados Abr 2026)
- `forecast_april` (consensus, 99,000)
- `previous_march_revised` (NUEVA estimación de Mar 2026)
- `previous_march_original` (lo que dijo el primer ADP del mes pasado)

Si `previous_march_revised` ≠ `previous_march_original`, hay revision.

**Por qué importa:** una revision fuerte del mes anterior cambia el
contexto de qué tan "sorpresa" es el actual. Ejemplo:

```
Si actual_april = 130k, forecast = 99k → SF naive = +0.14σ (suave)

Pero si previous_march fue revisado de 62k → 35k:
  - El consensus "99k para abril" estaba calibrado contra 62k previous
  - Con el verdadero previous=35k, el bar realista sería ~70k, no 99k
  - El "actual de 130k" es realmente +60k sobre baseline → SF más fuerte
```

## Propuesta: **SF con revision adjustment**

### Definiciones

```
revision_delta = previous_revised - previous_original
                 (en mismas unidades que actual: jobs absolutos)

forecast_adjusted = forecast + (revision_delta × β_revision_propagation)

SF_adjusted = (actual - forecast_adjusted) / σ_robust_FRED
```

### El parámetro β_revision_propagation

Mide cuánto "se corrige" el forecast por la revision. Pasos:

```
β = 0.0 → ignora revisiones (ingenuo, NO recomendado)
β = 0.5 → propaga 50% de la revision al forecast efectivo
β = 1.0 → asume forecast completamente recalibrado (agresivo)
```

**Mi recomendación: β = 0.5** como default — neutro entre ignorar y
sobre-corregir.

### JSON expandido para 12:15 UTC ADP

```json
{
  "event": "ADP Employment Change",
  "release_time_utc": "2026-05-06T12:15:00Z",
  "actual": <jobs absolutos>,
  "forecast": 99000,
  "previous_original_FMP_Apr3": 62000,
  "previous_revised_today": <jobs — capturar del release>,
  "revision_delta": <calculado: revised - original>,
  "beta_revision_propagation": 0.5,
  "forecast_adjusted": <calculado>,
  "SF_naive": <(actual - 99000) / 219188>,
  "SF_adjusted": <(actual - forecast_adjusted) / 219188>,
  "btc_5min_post": <BTC al T+5min>,
  "btc_30min_post": <BTC al T+30min>,
  "btc_60min_post": <BTC al T+60min>,
  "polymarket_btc_monthly_delta_5min": <ΔP del contrato BTC May>,
  "polymarket_btc_monthly_delta_30min": <ΔP a T+30min>
}
```

### Lógica de mode operativo

```
SF_to_use = max(|SF_naive|, |SF_adjusted|)
            (ser conservador — usar el más fuerte de los dos)

Aplicar lógica spec r90:
  if SF_to_use < 1σ → mantener mode actual
  if 1σ ≤ SF_to_use < 2σ → CAUTELA 15min hold
  if 2σ ≤ SF_to_use < 3σ → DEFENSIVO 30min hold
  if SF_to_use ≥ 3σ → FREEZE 60min hold
```

### Edge cases

```
Si previous_revised desconocido (no en release): asume revision_delta = 0
Si revision_delta > 50% del actual: anomaly → flag para audit manual
Si actual missing: SF = null → mantener mode actual sin trigger
```

## Pregunta para ti

(a) ¿β_revision_propagation = 0.5 default es razonable?
(b) ¿Apruebas usar `max(|SF_naive|, |SF_adjusted|)` como conservador,
    o prefieres que use solo SF_adjusted?
(c) ¿El threshold "revision_delta > 50% actual = anomaly" es razonable?

---

# RESUMEN — Lo que estoy pidiendo firmar

| Pregunta | Mi propuesta | Decisión esperada |
|---|---|---|
| 1. Métricas gRPC | scan_tick_duration_p99 < 5,000ms 24h sostenido como criterio | OK / ajustes |
| 2. NORMAL_DEGRADED | dinámico [0.55-0.85] default 0.70 con thresholds [1,5,15] err/min | constante o dinámico? |
| 3. Burn-in post-upgrade | 72h obligatorio + ≥1 macro tier-1 + 5 criterios cuantitativos | OK / extender |
| 4. ADP revisions | SF_adjusted con β=0.5 + max(naive, adjusted) | OK / ajustes |

Mientras esperas tu firma, procedo con:
- Implementación L1-L4 stale hierarchy en sidecar (ya parcial)
- Implementación NORMAL_DEGRADED hard-coded 0.70 (cambia a dinámico si firmas
  punto 2)
- Marco preparando autorización Chainstack upgrade billing

Burn-in V4 SHADOW continúa. ADP en 6h 20min.

Gracias.
