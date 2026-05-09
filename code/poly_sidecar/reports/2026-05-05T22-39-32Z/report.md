# Informe operativo VelocityQuant — 2026-05-05

**Report ID:** `2026-05-05T22-39-32Z`  
**Generado:** 2026-05-05T22:39:32.110870+00:00  
**Hora UTC actual:** 22h

---

## 1. Sidecar Polymarket — estado actual

- **Mode:** `CAUTELA` (polymarket endpoints stale)
- **τ_final:** 0.346
- **τ_crypto:** 0.346  |  **τ_macro:** 0.346
- **ρ:** —  (umbral -0.70, divergencia: no)
- **BTC spot:** $81,014

## 2. Macro events

### Próximos 24h (FMP)

| Hora UTC | Evento | Categoría | Prev | Forecast |
|---|---|---|---|---|
| 2026-05-06 12:15:00 | ADP Employment Change (Apr) | NFP | 62.0 | 99.0 |

## 3. V3.5 SHADOW Newark — actividad por ventana UTC

| Ventana UTC | Eventos | would_send | %  | CB blocked | p_max ($) | p_sum ($) | lat p50 (ms) | lat p99 (ms) | slot_lag max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 Asia | 143,800 | 22,997 | 16.0% | 107,657 | 0.1572 | 2531.30 | 1,718 | 26,184 | 150 |
| 08-13 Londres solo | 90,000 | 14,116 | 15.7% | 74,783 | 0.1494 | 1563.23 | 1,568 | 21,732 | 171 |
| 13-16 LDN x NY | 53,923 | 9,488 | 17.6% | 43,382 | 0.0761 | 931.25 | 850 | 10,358 | 43 |
| 16-21 NY post-LDN | 90,000 | 10,225 | 11.4% | 78,702 | 0.1721 | 1598.52 | 1,371 | 16,867 | 96 |
| 21-24 cierre | 29,844 | 3,276 | 11.0% | 26,135 | 0.1844 | 545.76 | 1,077 | 12,471 | 54 |

## 4. Lectura para Gemma 4

Marco copiará este MD a Gemma 4 web para análisis cuantitativo y posibles ajustes de spec.

**Preguntas sugeridas a Gemma:**

1. ¿La ventana LDN×NY confirma o desmiente el supuesto de mejor ejecución durante solape?
2. ¿El SF detectado del Investing justifica la transición a CAUTELA según los thresholds?
3. ¿Hay desalineación entre τ_crypto, τ_macro y los eventos próximos que sugiera ajuste de pesos?
4. ¿El % would_send post-evento macro es consistente con el modelo de retracción de liquidez?

---

_Informe generado por VelocityQuant report_generator v1.0 — `2026-05-05T22-39-32Z`_
