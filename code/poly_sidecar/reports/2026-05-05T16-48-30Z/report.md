# Informe operativo VelocityQuant — 2026-05-05

**Report ID:** `2026-05-05T16-48-30Z`  
**Generado:** 2026-05-05T16:48:30.707611+00:00  
**Hora UTC actual:** 16h

---

## 1. Sidecar Polymarket — estado actual

- **Mode:** `CAUTELA` (SF=-3.0 en ISM (|SF|>1σ))
- **τ_final:** 0.458
- **τ_crypto:** 0.550  |  **τ_macro:** 0.320
- **ρ:** 0.069  (umbral -0.70, divergencia: no)
- **BTC spot:** $81,104

## 2. Macro events

### ⚠️ Última sorpresa (|SF| > 1σ)

- **ISM Non-Manufacturing Prices  (Apr)** (united states)
  - actual: `70.7`  |  forecast: `73.7`  |  prev: `70.7`
  - **SF: -3.0σ**  (2026-05-05T15:00:00+00:00)
  - reaction_threshold_hit: True

### Próximos 24h (FMP)

| Hora UTC | Evento | Categoría | Prev | Forecast |
|---|---|---|---|---|
| 2026-05-06 12:15:00 | ADP Employment Change (Apr) | NFP | 62.0 | 99.0 |

### Reacciones últimas 6h (Investing)

| TS UTC | Evento | Cat | Actual | Fcst | SF |
|---|---|---|---|---|---|
| 2026-05-05T15:00:00+00:00 | ISM Non-Manufacturing Employment  (Apr) | ISM | 48.0 | 48.3 | -0.30σ |
| 2026-05-05T15:00:00+00:00 | ISM Non-Manufacturing PMI  (Apr) | ISM | 53.6 | 53.7 | -0.10σ |
| 2026-05-05T15:00:00+00:00 | ISM Non-Manufacturing Prices  (Apr) | ISM | 70.7 | 73.7 | -3.00σ |
| 2026-05-05T15:00:00+00:00 | JOLTS Job Openings  (Mar) | JOLTS | 6.866M | 6.860M | 16.65σ |

## 3. V3.5 SHADOW Newark — actividad por ventana UTC

| Ventana UTC | Eventos | would_send | %  | CB blocked | p_max ($) | p_sum ($) | lat p50 (ms) | lat p99 (ms) | slot_lag max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 Asia | 143,800 | 22,997 | 16.0% | 107,657 | 0.1572 | 2531.30 | 1,718 | 26,184 | 150 |
| 08-13 Londres solo | 90,000 | 14,116 | 15.7% | 74,783 | 0.1494 | 1563.23 | 1,568 | 21,732 | 171 |
| 13-16 LDN x NY | 53,923 | 9,488 | 17.6% | 43,382 | 0.0761 | 931.25 | 850 | 10,358 | 43 |
| 16-21 NY post-LDN | 14,541 | 1,713 | 11.8% | 12,662 | 0.0540 | 244.98 | 1,128 | 16,138 | 54 |
| 21-24 cierre | 0 | 0 | — | 0 | 0.0000 | 0.00 | — | — | — |

## 4. Lectura para Gemma 4

Marco copiará este MD a Gemma 4 web para análisis cuantitativo y posibles ajustes de spec.

**Preguntas sugeridas a Gemma:**

1. ¿La ventana LDN×NY confirma o desmiente el supuesto de mejor ejecución durante solape?
2. ¿El SF detectado del Investing justifica la transición a CAUTELA según los thresholds?
3. ¿Hay desalineación entre τ_crypto, τ_macro y los eventos próximos que sugiera ajuste de pesos?
4. ¿El % would_send post-evento macro es consistente con el modelo de retracción de liquidez?

---

_Informe generado por VelocityQuant report_generator v1.0 — `2026-05-05T16-48-30Z`_
