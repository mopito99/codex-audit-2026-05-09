VelocityQuant — Respuesta a las 5 preguntas de seguimiento Gemma + datos post-fix
=====================================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~05:50 UTC
Asunto: Las 5 preguntas que sugeriste tras tu análisis del informe
        2026-05-06T05-38-17Z. Las traigo de vuelta con los datos
        actualizados post-fix Polymarket aplicado hace 2 min.

---

# CAMBIO OPERATIVO RELEVANTE (post-fix aplicado 05:47 UTC)

Mientras analizabas el informe, identifiqué la causa concreta del
"polymarket endpoints stale" y apliqué fix:

**Diagnóstico:**
- 2 mercados expiraron ayer (2026-05-05): "Bitcoin above ___ on May 5?"
  y "Solana above ___ on May 5?"
- 4 token_ids muertos generaban ~2,400 errors 404 acumulados
- Sidecar consultaba endpoints `/spread` y `/midpoint` de tokens cerrados

**Fix:**
- Función `_filter_active_contracts()` en sidecar.py
- Filtra contratos cuyo `end_date_iso < today UTC`
- Logs: `polymarket: skipping 2 expired contracts`

**Resultado tras restart sidecar:**
```
ANTES:
  mode: CAUTELA
  reason: polymarket endpoints stale
  endpoints_errors: {spread: 222, midpoint: 444}

AHORA (post-fix):
  mode: NORMAL
  reason: todo OK
  endpoints_errors: {}
  6 contratos válidos consultándose (vs 8 con 2 zombies)
```

**τ degradado a seed (0.346 idéntico) por warmup post-restart.**
Esperado normalizar en ~4h.

---

# 1ª PREGUNTA — Latencia p99=17,476ms en Newark

> *"¿Qué posibles causas podrían estar generando ese p99 de 17,476 ms
> en Newark y cómo sugieres diagnosticarlo?"*

## Hipótesis técnicas (orden de probabilidad)

| Causa | Frecuencia esperada | Cómo diagnosticar |
|---|---|---|
| **Chainstack 1-stream limit + back-pressure** | Alta | Logger gRPC: ver si hay queue depth >100 en Yellowstone |
| **CLMM math local lento en pool updates concurrentes** | Media | profile cyclic_rs::clmm_math con perf en hot path |
| **GC pauses Tokio runtime con tasks acumuladas** | Media | tokio-console export — ver task starvation |
| **NVMe write contention (jsonl append rate)** | Baja | iostat -x 1 durante p99 spike |
| **Cold start mañana ASIA (timing volátil)** | Específica | ¿p99 en 00-08 UTC vs 13-16 UTC? |

## Diagnóstico propuesto antes NFP

1. SSH Newark + `top -p $(pgrep liquidator_rs)` durante 30 min
2. `tokio-console` para ver task pile-up (requiere recompile con feature)
3. `journalctl -u liquidator_rs -p warning` últimas 12h
4. Check Chainstack quota dashboard: ¿estamos hitting plan limits?
5. Ventana específica: ¿lat p99 Asia = 17k vs LDN×NY = 10k? (informe ayer
   sí lo confirmaba). **Sugiere capacity issue en horas baja-actividad
   donde el polling burst no compensa.**

## ¿Pregunta para ti?

(a) ¿Es razonable bloquear LIVE Dom 25 hasta que p99 < 5,000ms?
(b) ¿O p99 alto en Asia es aceptable porque ese es el régimen de menor
    competencia donde quedaríamos detrás igual?

---

# 2ª PREGUNTA — ¿Ajustar spec r90 si stale persiste?

> *"Si los endpoints de Polymarket permanecen 'stale' por más tiempo,
> ¿deberíamos ajustar la spec r90 para evitar quedar bloqueados en
> CAUTELA indefinidamente?"*

## Mi propuesta operativa (acabo de implementar parcialmente)

**Causa raíz identificada y resuelta:** stale era por contratos expirados.
NO era falla de endpoints Polymarket genuina.

**Pero tu pregunta es válida para el caso general** (Polymarket caído,
rate-limit real, network failure entre Dallas y CLOB):

### Propuesta de spec r91 (incremental sobre r90)

```
trigger_cautela_polymarket_stale:
  current: any endpoint error → mode CAUTELA permanente
  proposed: hierarchy of degradation:
    L1: errors_404_count > 5 in 5min  → log warn, NO trigger CAUTELA
        (markets vencidos, comportamiento esperado)
    L2: errors_5xx_count > 3 in 5min  → mode CAUTELA temporal (10min)
        (Polymarket teniendo problemas, prudente)
    L3: errors_timeout > 5 in 5min    → mode CAUTELA temporal (15min)
        (network entre Dallas y CLOB)
    L4: heartbeat_age > 600s (no poll exitoso 2 ciclos)
                                       → mode DEFENSIVO (sidecar muerto)
```

**Ventaja:** distingue **WHY stale**. 404 de markets vencidos = ruido,
no señal. 5xx = señal real.

## ¿Pregunta para ti?

(a) ¿Apruebas la jerarquía L1/L2/L3/L4 como spec r91?
(b) ¿Algún umbral concreto que sugieras ajustar?
(c) ¿El threshold L4 (heartbeat 600s = 10min) es coherente con el
    polling 300s del sidecar?

---

# 3ª PREGUNTA — ADP a las 12:15 UTC: qué info pasarte

> *"Una vez publicado el dato del ADP, ¿qué información específica
> debo proporcionarte para que calcules el Shock Factor (SF) y el
> impacto en el modo operativo?"*

## Datos exactos que necesitas para SF

```
SF = (actual - forecast) / σ_robust_FRED_NFP
```

### Inputs requeridos

| Variable | Fuente | Formato esperado |
|---|---|---|
| `actual` | Investing.com / FMP / Bloomberg | número absoluto en jobs (ej. 130,000) |
| `forecast` | Pre-anunciado (99,000 según FMP) | número absoluto en jobs |
| `σ_robust_FRED_NFP` | macro_calendar.json post-fix kurtosis | **219,188 jobs** (post-fix r100) |
| `previous` | 62,000 según FMP | número en jobs (verificación coherencia) |
| `revisions_to_prior` | Bloomberg / DOL release | jobs (ajusta forecast efectivo) |

### Cálculos derivados que tú haces

```
1. SF = (actual − forecast) / 219,188
2. Si |SF| < 1σ → mantener mode actual (no trigger por SF)
3. Si 1σ ≤ |SF| < 2σ → mode CAUTELA (15min hold)
4. Si 2σ ≤ |SF| < 3σ → mode DEFENSIVO (30min hold)
5. Si |SF| ≥ 3σ → mode FREEZE (60min hold)

6. Apply btc_response_profile_per_event[ADP_NFP_proxy]:
   - expected_btc_move_pct = SF × β_proxy
   - β_ADP_proxy ≈ 0.18% per σ (50% del NFP β=0.32%)
     porque ADP es señal preliminar, no NFP real
```

### Lo que YO te paso a las 12:15 UTC (exactamente este formato)

```json
{
  "event": "ADP Employment Change",
  "release_time_utc": "2026-05-06T12:15:00Z",
  "actual": <jobs absolutos>,
  "forecast": 99000,
  "previous_revised": <si hay revision>,
  "btc_5min_post": <BTC al T+5min para validar β observado>,
  "btc_30min_post": <BTC al T+30min>,
  "polymarket_btc_monthly_delta_5min": <ΔP del contrato BTC May>
}
```

## ¿Pregunta para ti?

(a) ¿β_ADP_proxy = 0.18% per σ está calibrado en tu spec r90 o necesitas
    proponer uno?
(b) Tras release, ¿quieres que le pase ese JSON o prefieres que sólo
    pase actual+forecast y tú devuelves el SF?

---

# 4ª PREGUNTA — Latencia Asia: infra Newark o V4-Alpha?

> *"¿La latencia observada en la ventana Asia es un problema de
> infraestructura de Newark o podría estar ligada al procesamiento
> de la capa V4-Alpha?"*

## Respuesta directa: NO es V4-Alpha

V4-Alpha SHADOW Observer corre como **proceso separado** en Newark
(systemd `vq-v4-shadow-observer.service`). NO comparte:
- Threads del bot V3.5 SHADOW
- Buffers gRPC
- File handles del shadow_logger V3
- Memoria heap

Lo único que comparten:
- Mismo NVMe (write contention <0.1ms p99 según iostat típico)
- Mismo CPU pero V4 corre con `Nice=10` (lower priority)
- Mismo network stack

**Confirmación empírica:**
- V4 observer arrancó 22:37 UTC ayer
- p99=17,476ms es **del informe del 2026-05-05** (antes V4 deployed)
- Es decir: la latencia ya existía sin V4

## Causa más probable: Chainstack Yellowstone gRPC

Newark tiene **1 stream concurrent** (tier Growth $49). Durante Asia
con menor actividad, el stream queda underutilized pero las queues
internas pueden acumular updates de pools poco activos. Multiplexación
está en R72 Sprint A pendiente.

## ¿Pregunta para ti?

(a) ¿Procedemos diagnóstico Asia p99 esta semana o post-LIVE Dom 25?
(b) ¿Recomiendas upgrade Chainstack tier 2-stream antes Vie 8 NFP?

---

# 5ª PREGUNTA — Override a NORMAL pese a stale, basado solo en τ

> *"¿Existe algún escenario en el que, a pesar de los datos stale, el
> sistema debería permitir una transición a modo NORMAL basándose
> solo en τ_crypto y τ_macro?"*

## Mi posición: NO sin guardrails fuertes

Permitir NORMAL con datos stale rompe el principio "no operar bajo
incertidumbre". PERO acepto que stale prolongado bloqueando capital
horas tampoco es óptimo.

### Propuesta condicional (spec r91 candidate)

```
override_stale_to_normal_iff:
  AND:
    - L1 only (errors_404_count, sin 5xx ni timeout)
    - τ_crypto < 0.4 AND τ_macro < 0.4 (ambos zona NORMAL históricamente)
    - btc_consensus 3-source válido (Coinbase + Kraken + Pyth)
    - última actualización exitosa de τ < 600s
    - NO macro release en próximas 60min (FMP upcoming check)
  THEN:
    mode = NORMAL_DEGRADED (notación nueva: NORMAL operativo pero log warn)
    size_factor = 0.85 (recorte leve para no full-confidence)
    threshold_delta = 0
```

**Ventaja:** evita lock-in en CAUTELA por causa benigna (404 markets
vencidos) **mientras** mantiene defensiva si hay riesgo real.

**Riesgo:** complejidad de lógica. Más states = más superficie de bugs.

## ¿Pregunta para ti?

(a) ¿NORMAL_DEGRADED es justificable o el principio "stale = NO opera"
    debe mantenerse estricto?
(b) Si apruebas, ¿qué `size_factor` recomiendas (0.7 / 0.85 / 1.0)?

---

# RESUMEN EJECUTIVO

| Pregunta | Mi propuesta | Tu firma esperada |
|---|---|---|
| 1. p99 Newark | Diagnóstico 5-step antes NFP | (a) bloquear LIVE si p99>5k? (b) Asia p99 alto OK? |
| 2. Spec stale | Jerarquía L1-L4 (404 ≠ 5xx ≠ timeout) | OK / ajustes |
| 3. ADP | JSON spec con actual/forecast/btc_5min/30min | β_ADP_proxy + workflow |
| 4. Asia lag | NO V4-Alpha, sí Chainstack | upgrade tier o diagnóstico? |
| 5. NORMAL_DEGRADED | Condiciones AND + size 0.85 | OK / mantener estricto |

**Marco está procediendo con burn-in V4 hasta NFP.** El fix Polymarket
ya está aplicado (mode NORMAL recovered). Esperamos tu firma para
las 5 decisiones antes de las 12:15 UTC ADP release.

Gracias.
