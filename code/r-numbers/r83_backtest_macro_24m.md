# Backtest Macro 24m — Validación spec Gemma V4-Alpha §4.7

_Generado 2026-05-05T07:05:05.450934+00:00 UTC_


## Resumen por categoría

| Cat | N events | BTC \|move\| @+5min mean | std | events |SF|>1σ | events \|BTC\|>2% |
|---|---|---|---|---|---|

## Comparación vs spec Gemma

**Spec Gemma V4-Alpha §4.7:** mean 1.2%, std 0.8%, P(>2σ)≈15-20%


| Cat | Spec mean | Real mean | Diff | Spec P(>2σ) | Real P(>2σ) |
|---|---|---|---|---|---|

## Detalle por categoría (top eventos por |SF|)


---

## Conclusiones operativas

1. **σ_FRED defaults vs reales:** revisar cuántos eventos cruzaron |SF|>1σ.
   Si la frecuencia es <5% → σ_FRED demasiado alto, bot nunca reaccionaría.
   Si la frecuencia es >40% → σ_FRED demasiado bajo, demasiada reactividad.

2. **Validación spec Gemma BTC mean 1.2% std 0.8%:** comparar vs columna real.
   Categorías con mean < 0.5% → evento sobre-estimado. >2% → sub-estimado.

3. **Cobertura outliers:** NFP σ=1807k incluye COVID-19. Para los 24m post-2023
   probablemente el shock real está mucho más bajo que σ permite reaccionar.