# Informe operativo VelocityQuant — 2026-05-06

**Report ID:** `2026-05-06T05-38-17Z`  
**Generado:** 2026-05-06T05:38:17.739095+00:00  
**Hora UTC actual:** 5h

---

## 1. Sidecar Polymarket — estado actual

- **Mode:** `CAUTELA` (polymarket endpoints stale)
- **τ_final:** 0.604
- **τ_crypto:** 0.548  |  **τ_macro:** 0.688
- **ρ:** 0.024  (umbral -0.70, divergencia: no)
- **BTC spot:** $81,223

## 2. Macro events

### Próximos 24h (FMP)

| Hora UTC | Evento | Categoría | Prev | Forecast |
|---|---|---|---|---|
| 2026-05-06 12:15:00 | ADP Employment Change (Apr) | NFP | 62.0 | 99.0 |

## 3. V3.5 SHADOW Newark — actividad por ventana UTC

| Ventana UTC | Eventos | would_send | %  | CB blocked | p_max ($) | p_sum ($) | lat p50 (ms) | lat p99 (ms) | slot_lag max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 Asia | 101,482 | 6,705 | 6.6% | 93,811 | 0.2293 | 1801.34 | 1,587 | 17,476 | 79 |
| 08-13 Londres solo | 0 | 0 | — | 0 | 0.0000 | 0.00 | — | — | — |
| 13-16 LDN x NY | 0 | 0 | — | 0 | 0.0000 | 0.00 | — | — | — |
| 16-21 NY post-LDN | 0 | 0 | — | 0 | 0.0000 | 0.00 | — | — | — |
| 21-24 cierre | 0 | 0 | — | 0 | 0.0000 | 0.00 | — | — | — |

## 4. V4-Alpha Macro Layer — observer paralelo

**Records observados hoy:** 20,262 (V4 observer Newark, ~1 record/s)

### 4.1 Distribución de modes

| Mode | Records | % |
|---|---:|---:|
| Cautela | 20,262 | 100.0% |

### 4.3 τ (tensión) y ρ (Pearson) percentiles

| Métrica | p10 | p50 | p90 | extremo |
|---|---:|---:|---:|---:|
| τ_final | 0.603 | 0.673 | 0.739 | max 0.821 |
| τ_crypto avg | — | 0.694 | — | — |
| τ_macro avg | — | 0.636 | — | — |
| ρ | -0.033 | -0.009 | 0.029 | min -0.041 |

### 4.4 V3 vs V4 — ¿hubieran decidido distinto?

- V3 `would_send=true` total: 0
- V3-V4 disagreement (V3 sí, V4 no): **0** (0.00% del total)
- Decision_allowed por V4: 100.0%
- ρ divergencia activa: 0.00%

### 4.5 Health del macro layer

- is_warmup pct: 46.6% (warmup threshold 4h)
- is_stale pct: 0.0%
- sidecar_error_count_max: 0
- BTC range observado: $80,839.21 — $81,653.35 (median $81,299.18)

## 5. Lectura para Gemma 4

Marco copiará este MD a Gemma 4 web para análisis cuantitativo y posibles ajustes de spec.

**Preguntas sugeridas a Gemma:**

1. ¿La ventana LDN×NY confirma o desmiente el supuesto de mejor ejecución durante solape?
2. ¿El SF detectado del Investing justifica la transición a CAUTELA según los thresholds?
3. ¿Hay desalineación entre τ_crypto, τ_macro y los eventos próximos que sugiera ajuste de pesos?
4. ¿El % would_send post-evento macro es consistente con el modelo de retracción de liquidez?
5. **V4-Alpha:** ¿La distribución de modes observada (§4.1) es coherente con tu spec r90?
6. **V4-Alpha:** ¿Algún disagreement V3↔V4 (§4.4) sugiere ajuste de thresholds?

---

_Informe generado por VelocityQuant report_generator v1.1 — `2026-05-06T05-38-17Z`_
