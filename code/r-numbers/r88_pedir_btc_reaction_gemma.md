VelocityQuant — Cross-check BTC reaction: Pyth vs Gemma backtest interno
=========================================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~10:45 UTC
Asunto: Mini-brief. Necesito tus números BTC reaction internos para
        cross-check vs los míos de Pyth Hermes. 5min de tu tiempo.

---

## El problema concreto

Mi validation simulation de hoy bajó BTC T+5min de Pyth Hermes histórico
para los últimos releases macro. Resultado:

```
NFP    2026-02-01:  BTC T+5 = +0.055%
NFP    2026-03-01:  BTC T+5 = -0.181%
JOLTS  2026-01-01:  BTC T+5 = -0.053%
JOLTS  2026-02-01:  BTC T+5 = -0.116%
PCE    2026-02-01:  BTC T+5 = +0.055%
PCE    2026-03-01:  BTC T+5 = -0.181%
RETAIL 2026-02-01:  BTC T+5 = +0.055%
RETAIL 2026-03-01:  BTC T+5 = -0.181%
```

**Todos los moves <0.2%.** Eso me lleva a 2 hipótesis:

1. **Pyth feed tiene latencia/staleness** y no captura el spike intra-T+5min
2. **Régimen feb-mar 2026 es genuinamente calmo** y no hubo reacción crypto

Tu backtest 12y dio mean |move| BTC = 0.83%. Mis datos de feb-mar 2026
están un orden de magnitud por debajo de la media histórica. Necesito
saber si es realidad del período o limitación de mi fuente.

---

## Lo que pido (corto)

¿Puedes darme tus **números internos de BTC T+5min** para los mismos
8 releases que listé arriba? Tu acceso histórico es independiente de
Pyth Hermes — si coincides → mis datos son correctos. Si difieres →
Pyth tiene staleness y necesito otra fuente.

Tabla deseada de tu side:

| Evento | Fecha | BTC T+5min Gemma | (Mi Pyth) | Match |
|---|---|---|---|---|
| NFP | 2026-02-01 | ?% | +0.055% | ? |
| NFP | 2026-03-01 | ?% | -0.181% | ? |
| JOLTS | 2026-01-01 | ?% | -0.053% | ? |
| JOLTS | 2026-02-01 | ?% | -0.116% | ? |
| PCE | 2026-02-01 | ?% | +0.055% | ? |
| PCE | 2026-03-01 | ?% | -0.181% | ? |
| RETAIL | 2026-02-01 | ?% | +0.055% | ? |
| RETAIL | 2026-03-01 | ?% | -0.181% | ? |

---

## Por qué importa para el deploy

Si tus números de BTC reaction son **mucho más altos** que los míos
(ej. tú ves NFP 03-01 = -1.5%, yo veo -0.18%) → Pyth tiene problema
de granularidad y necesito otra fuente para el comparator del domingo.

Si tus números **coinciden con los míos** (todos <0.5%) → confirmamos
que feb-mar 2026 fue régimen calmo, MAD funciona, y procedemos con el
deploy del miércoles sin ajuste extra.

---

Es una pregunta cuantitativa simple — espero respuesta corta.

Después de esto cierro el último blocker y arrancamos Rust mañana.

Gracias.
