VelocityQuant — Evaluación 3 estrategias señal momentum (Telegram-driven)
===========================================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~12:00 UTC
Asunto: Decisión técnica sobre 3 estrategias de operativa con señales
        tipo "RAVEUSDT -5.84% en 1m". Tu veredicto cuantitativo + si
        SÍ a alguna, autorizo segunda ronda con audit profundo.

---

# CONTEXTO RÁPIDO

Bots mirror operativos:
- `bot3_prime` → plstrategy.mbottoken.com (BingX)
- `bot3_prime_bitunix` → plsbitunix.mbottoken.com (Bitunix)
- `signal_mirror.service` recibe señales Telegram + forwardea HTTP
- Mirror Strategy: TP1/TP2/SL/TS con valores fijos por señal

Datos ya disponibles en infraestructura:
- **Sidecar 4 fuentes:** τ, ρ Pearson, σ_FRED MAD, FMP/Investing macro
- **BingX REST:** klines 1m, RSI, ticker, orderbook, volumen
- **Bitunix REST:** klines, ticker
- **Pyth Hermes:** SOL/USDC/USDT en V3.5 (BTC ya integrado en sidecar)

CONSTRAINT crítico Marco: **NO quiero "elefante lento con demasiados parámetros".**
Si una estrategia no aporta alpha medible vs ruido → descartar.
Mejor 2 estrategias con value claro que 5 con ruido superpuesto.

Marco quiere tu evaluación en **DOS dimensiones simultáneamente:**

1. **CUANTITATIVA** — alpha estimado, latencia, complexity score, win rate,
   compatibilidad con datos existentes
2. **FILOSÓFICA** — tu punto de vista como arquitecta cuant. ¿Estas
   estrategias se alinean con principios operativos sólidos? ¿KISS o
   sobre-ingeniería? ¿Coherencia con V4-Alpha que ya estamos construyendo?
   ¿Modo de pensar correcto o crooked thinking? ¿Trampa cognitiva?

---

# 3 ESTRATEGIAS A EVALUAR (3 descartada — Discovery ya lo hace signal_mirror)

## Estrategia 1 — MOMENTUM (Follow Trend)

**Lógica:** señal `-5.84%` en 1m + volumen masivo → SHORT (apuesta pánico
continúa). Señal `+5%` con volumen → LONG (capturar pump).

**Sub-decisiones críticas:**
- ¿Cuándo es "volumen masivo"? Z-score volumen vs baseline 20m, 1h, 24h?
- ¿Threshold de "momentum válido"? -3% o -5% en 1m? Diferenciar por par
  (BTC vs altcoin tail)?
- ¿Tamaño de posición? Fijo o modulado por τ del sidecar / ImpliedVol?
- ¿Stop loss inicial? (alta volatilidad → SL ancho o ajustado?)
- ¿Hold time máximo? 5min / 15min / hasta señal opuesta?

## Estrategia 2 — REVERSIÓN A LA MEDIA (Contrarian/Scalping)

**Lógica:** caída fuerte + RSI sobreventa (<30) + soporte técnico →
LONG esperando rebote técnico ("bounce").

**Sub-decisiones críticas:**
- ¿RSI período? 14 estándar o ajustado (5/9 para 1m timeframe)?
- ¿Threshold sobreventa? <30, <20 (extreme)?
- ¿Cómo identificar "soporte técnico" en 1m? Lows previos, VWAP,
  Bollinger Bands inferior?
- ¿Cuánto del rebote capturar? Target 50% retracement / Fibonacci
  específico / threshold τ?
- ¿Cuánto tiempo dejar correr? Hasta ROI X% o tiempo Y?

## Estrategia 4 — IMPLEMENTACIÓN TÉCNICA (Pre-execution validation)

**Lógica:** parsing RegEx + validación volumen real + soporte histórico
ANTES de ejecutar trade. No entrar a ciegas en señales.

**Sub-decisiones críticas:**
- ¿Parsing RegEx ya implementado en signal_mirror? Validar.
- ¿Validación pre-trade requiere call API extra (latencia +50-100ms)?
  ¿Aceptable vs valor del filtro?
- ¿Cómo definir "volumen inusual" cuantitativamente?
- ¿Skip vs delay si validación falla?

---

# DISAMBIGUATOR clave

Estrategias 1 y 2 son OPUESTAS sobre el mismo input (caída fuerte).
¿Cómo decide el bot cuál ejecutar?

- ¿RSI level? <30 → reversión, 30-50 → momentum
- ¿Volumen extreme + absorption pattern? → reversión
- ¿Caída sostenida >5 velas vs spike único? → momentum real vs fakeout
- ¿Persistence_factor del btc_response_profile_per_event firmado por ti?

¿Tu decisor cuantitativo?

---

# DATOS QUE TENEMOS (no pidas más, usa estos primero)

```
Sidecar (cada 5min):
- τ_final, τ_macro, τ_crypto
- ρ Pearson rolling 6h
- BTC spot consensus (Coinbase + Kraken + Pyth weighted_median)
- mode: NORMAL/CAUTELA/DEFENSIVO
- next macro event + seconds_to_event (FMP)
- Surprise Factor último release (Investing)

BingX REST:
- klines 1m (open/high/low/close/volume)
- ticker actual
- orderbook depth
- 24h stats

Telegram signal:
- símbolo, % cambio, timeframe, precio
```

---

# FORMATO RESPUESTA SOLICITADA (JSON)

```json
{
  "strategy_1_momentum": {
    "quantitative": {
      "veredict": "yes | no | with_constraints",
      "alpha_potential_estimate_pct": <number or null>,
      "expected_win_rate_pct": <number>,
      "complexity_cost_score_1_to_10": <int>,
      "min_params_required": <int>,
      "data_reuse_pct_existing_infrastructure": <number 0-100>
    },
    "philosophical": {
      "kiss_or_overengineering": "kiss | overengineering",
      "alignment_with_v4alpha": "aligned | conflicts | orthogonal",
      "cognitive_trap_warning": "<text or null>",
      "first_principles_view": "<your honest opinion 1-3 lines>"
    },
    "rationale_short": "<combined 2-3 lines>",
    "risk_main": "<one risk>",
    "if_yes_constraints": ["<constraint 1>", "<constraint 2>"]
  },
  "strategy_2_mean_reversion": {
    "quantitative": {
      "veredict": "yes | no | with_constraints",
      "alpha_potential_estimate_pct": <number or null>,
      "expected_win_rate_pct": <number>,
      "complexity_cost_score_1_to_10": <int>,
      "min_params_required": <int>,
      "data_reuse_pct_existing_infrastructure": <number 0-100>
    },
    "philosophical": {
      "kiss_or_overengineering": "kiss | overengineering",
      "alignment_with_v4alpha": "aligned | conflicts | orthogonal",
      "cognitive_trap_warning": "<text or null>",
      "first_principles_view": "<your honest opinion 1-3 lines>"
    },
    "rationale_short": "<combined 2-3 lines>",
    "risk_main": "<one risk>",
    "if_yes_constraints": ["<constraint 1>", "<constraint 2>"]
  },
  "strategy_4_pre_validation": {
    "quantitative": {
      "veredict": "yes | no | with_constraints",
      "alpha_potential_estimate_pct": <number or null>,
      "expected_win_rate_pct": <number>,
      "complexity_cost_score_1_to_10": <int>,
      "min_params_required": <int>,
      "data_reuse_pct_existing_infrastructure": <number 0-100>
    },
    "philosophical": {
      "kiss_or_overengineering": "kiss | overengineering",
      "alignment_with_v4alpha": "aligned | conflicts | orthogonal",
      "cognitive_trap_warning": "<text or null>",
      "first_principles_view": "<your honest opinion 1-3 lines>"
    },
    "rationale_short": "<combined 2-3 lines>",
    "risk_main": "<one risk>",
    "if_yes_constraints": ["<constraint 1>", "<constraint 2>"]
  },
  "disambiguator_1_vs_2": {
    "primary_indicator": "<RSI | volume | persistence | other>",
    "exact_threshold_logic": "<one-line decision rule>",
    "fallback_when_ambiguous": "<action>"
  },
  "global_recommendation": {
    "implement_count": <0-3>,
    "which_to_implement": ["<strategy_name>"],
    "expected_alpha_combined_pct_per_month": <number or null>,
    "implementation_effort_hours": <int>,
    "blocker_if_skipped": "<text or null>",
    "anti_elephant_compliance": true | false,
    "philosophical_summary": "<your overarching view: ¿procede esta línea de trabajo en VelocityQuant o nos distrae del enfoque MEV/macro?>",
    "would_you_personally_deploy_this": "yes | no | only_after_v4alpha_stable"
  },
  "if_yes_to_any_authorize_deep_audit": {
    "willing_to_audit": true | false,
    "audit_scope": [
      "latency_per_strategy_ms",
      "data_reuse_efficiency",
      "interaction_with_v4alpha_macro_layer",
      "...other"
    ]
  }
}
```

---

# Resumen de lo que pido

1. Veredicto **yes/no/with_constraints** para cada estrategia (1, 2, 4)
2. Estimación cuantitativa **alpha potencial** vs **costo complejidad**
3. Disambiguator 1 vs 2 (regla simple, no tabla de 20 condiciones)
4. **`global_recommendation.implement_count`** — cuántas implementar
   realmente (0/1/2/3). Marco prefiere menos pero firmes
5. Si dices SÍ a alguna → autorizas segunda ronda audit profundo de
   latencia, uso de datos existentes, interacción con V4-Alpha

**Constraint:** estrategia que pase de complexity_cost_score=7/10 sin
alpha estimable claro → veredict=no automático. No "elefante lento".

Tu llamada cuantitativa.

Gracias.
