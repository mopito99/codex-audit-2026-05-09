VelocityQuant — Brief consolidado: cross-check BTC + 4 follow-ups + arquitectura Gemma-Oracle
================================================================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~11:00 UTC
Asunto: Una sola respuesta para 5 preguntas. Formato JSON estructurado
        para que Claude pueda parsearla automáticamente. Nueva arquitectura
        "Gemma como Oracle Primario" con fallback.

---

# CONTEXTO RÁPIDO

Estado:
- σ_FRED MAD aplicado: NFP 1807k → 130.5k (✓ recovers sensitivity)
- 4 perfiles BTC segmentados firmados por ti
- Validation simulation: BTC T+5min Pyth Hermes <0.2% en TODOS los samples
  feb-mar 2026 → o régimen calmo o Pyth daily snapshots
- Mañana mié target: empezar wiring Rust V4-Alpha

---

# NUEVA ARQUITECTURA — "Gemma Oracle + Fallback" (TODOS los parámetros)

Marco decidió que **TODAS las fuentes y parámetros cuantitativos** del
sistema seguirán el patrón:

```
1. Tier 1 (PRIMARY)    → Gemma 4 vía bridge ask_gemma.py / brief MD
2. Tier 2 (FALLBACK)   → API externa (FRED / Pyth / Polymarket /
                          FMP / Investing / BingX / etc)
3. Tier 3 (DEFAULT)    → Static value en macro_calendar.json
```

**No solo BTC. Aplicar a:**
- BTC spot price → Gemma → Pyth → Coinbase fallback
- Polymarket probabilities → Gemma → CLOB direct → cached
- FRED σ histórica → Gemma → fred_init.py → defaults V4-Alpha
- FMP calendar → Gemma → FMP API → manual macro_calendar.json
- Investing actuals → Gemma → investpy → previous value
- btc_response_profile → Gemma firmados → spec V4-Alpha §4.7
- trigger_sf, capture_window, comparator criteria → Gemma → defaults

**Implicación práctica:**
- 1 brief Marco → 1 respuesta JSON tuya con N secciones (sea 5, 7 o 10)
- Claude parsea automáticamente y mapea a parámetros del sistema
- Tu valor cachea en `macro_calendar.json` con TTL (semana / día según tipo)
- Si tu respuesta missing un campo → sidecar usa fallback automático
- Menos ruido, decisiones rápidas, cero re-rondas

**No es realista** llamarte cada cycle 5min para datos live (BTC tick,
Polymarket midpoint en cada slot). Pero SÍ para:
- Parámetros estáticos refinables (σ_FRED, perfiles, triggers)
- Validaciones discretas (cross-check, GO/NO-GO)
- Análisis ad-hoc (backtest, regime shift detection)
- Calibración inicial / refresh semanal

---

# 5 PREGUNTAS — todas en una respuesta

## Q1 — Cross-check BTC reaction (mi pregunta original r88)

Mi Pyth Hermes histórico para los últimos 8 releases macro dio:

| Evento | Fecha | BTC T+5min (Pyth) |
|---|---|---|
| NFP | 2026-02-01 | +0.055% |
| NFP | 2026-03-01 | -0.181% |
| JOLTS | 2026-01-01 | -0.053% |
| JOLTS | 2026-02-01 | -0.116% |
| PCE | 2026-02-01 | +0.055% |
| PCE | 2026-03-01 | -0.181% |
| RETAIL | 2026-02-01 | +0.055% |
| RETAIL | 2026-03-01 | -0.181% |

Todos <0.2%. **¿Tu backtest interno confirma esos números o detecta
discrepancia significativa?**

## Q2 — Alternative data sources for high-resolution BTC event data

Tu sugerencia: si Pyth tiene staleness/granularidad insuficiente,
¿qué fuentes alternativas recomiendas para reemplazar?

Restricciones operativas:
- Sin geo-blocks (Binance bloqueado desde Newark/Dallas)
- Free tier o coste razonable
- Resolución intra-segundo o al menos 1-min
- API REST simple (sin SDKs propietarios)

## Q3 — Cómo verificar si Pyth Hermes da daily snapshots vs tick data

Mi sospecha: Pyth `/v2/updates/price/{ts}` puede devolver el precio
**closest** al timestamp, pero si la granularidad es a nivel de día,
voy a perder spikes intra-T+5min. ¿Cómo lo verifico empíricamente?

Tu propuesta de test (acepto cualquiera, dame uno simple):
- (a) Pedir N timestamps en intervalo de 1 minuto y ver si el precio
  cambia entre cada uno
- (b) Comparar Pyth response time vs frecuencia de publish de Pyth feed
- (c) Otra técnica que prefieras

## Q4 — ¿Esta discrepancia BTC cambia los requirements arquitecturales del Rust mañana?

Si confirmas que Pyth tiene staleness:
- ¿Necesito CAMBIAR el wiring Rust mañana para no depender de Pyth para
  ρ Pearson, o mantener Pyth con fallback agregado?
- ¿`AtomicPtr` vs `Arc<RwLock<MacroState>>` cambia tu recomendación si
  añadimos múltiples sources de BTC con consenso?

## Q5 — Raw tick-level volatility para March 1st NFP — análisis pattern

Para validar definitivamente si Pyth pierde el spike, necesito el
**tick-level BTC volatility para 2026-03-01 12:30:00 UTC ± 5min** (NFP).

Si tu acceso histórico tiene resolución sub-segundo, dame:
- Precio BTC máximo entre 12:30:00 y 12:35:00
- Precio BTC mínimo entre 12:30:00 y 12:35:00
- Spread (max-min) %
- Tick más volátil (timestamp + magnitud %)

---

# FORMATO DE RESPUESTA SOLICITADO (JSON)

Para que Claude pueda parsearla automáticamente y reducir ronda extra
de "interpretación", devuelve tu respuesta en este JSON exacto:

```json
{
  "q1_cross_check_pyth": {
    "your_btc_reactions_t5_pct": {
      "NFP_2026-02-01": <number>,
      "NFP_2026-03-01": <number>,
      "JOLTS_2026-01-01": <number>,
      "JOLTS_2026-02-01": <number>,
      "PCE_2026-02-01": <number>,
      "PCE_2026-03-01": <number>,
      "RETAIL_2026-02-01": <number>,
      "RETAIL_2026-03-01": <number>
    },
    "verdict": "match | discrepancy",
    "interpretation": "<1-line explanation>"
  },
  "q2_alternative_btc_sources": {
    "primary_recommendation": "<source name>",
    "endpoint_or_method": "<URL or technique>",
    "advantages_vs_pyth": "<short>",
    "alternatives_ranked": ["<2nd best>", "<3rd best>"]
  },
  "q3_verify_pyth_granularity": {
    "test_method": "<description>",
    "expected_signature_if_daily": "<symptom>",
    "expected_signature_if_tick": "<symptom>"
  },
  "q4_rust_architecture_impact": {
    "change_required": true | false,
    "if_required": "<what changes>",
    "atomic_vs_rwlock_decision": "AtomicPtr | Arc<RwLock> | other",
    "consensus_logic_needed": true | false
  },
  "q5_nfp_march1_tick_data": {
    "btc_max_t0_to_t5": <number>,
    "btc_min_t0_to_t5": <number>,
    "intraday_range_pct": <number>,
    "most_volatile_tick": {
      "timestamp_utc": "<ISO8601>",
      "magnitude_pct": <number>
    },
    "interpretation": "<1-line: was there a spike Pyth missed? yes/no/inconclusive>"
  },
  "ready_to_proceed_with_rust_wiring_wed": true | false,
  "reasoning_for_proceed_decision": "<short>"
}
```

Si algún campo no puedes responder con confianza, déjalo como `null` y
añade `_note` con la razón. Marco prefiere null honesto antes que
fabricación.

---

# Resumen del flujo después

Tras tu respuesta JSON:

1. **Si `ready_to_proceed_with_rust_wiring_wed = true`** → mañana mié
   Claude arranca wiring Rust V4-Alpha con la spec definida
2. **Si `false`** → el campo `reasoning_for_proceed_decision` define
   qué bloqueador resolver primero
3. **Si Q1 verdict=discrepancy** → Claude swap Pyth → tu source
   recomendado en Q2 antes del wiring Rust
4. **Si Q5 confirma spike Pyth missed** → necesitamos consenso multi-source
   en Rust (Q4)

Marco aplica la decisión sin más rondas.

---

# PETICIÓN META — comunicación futura (importante)

Para CADA fuente del sistema, define en tu respuesta:

1. ¿Eres Tier 1 capable para esta fuente? (sí/no)
2. Si sí → ¿qué TTL refresh recomiendas? (1h / 1día / 1semana / on-demand)
3. ¿Cuál es el fallback Tier 2 que prefieres?
4. ¿Cuál es el default Tier 3 estático?

**Tabla solicitada en tu JSON respuesta** (sección final):

```json
"oracle_routing_table": {
  "btc_spot_price": {
    "tier1_gemma_capable": false,
    "tier1_reason": "tick data en tiempo real fuera de mi acceso",
    "tier2_fallback": "Pyth Hermes /v2/updates/price/latest",
    "tier3_default": "last cached price < 60s",
    "ttl_refresh": "5min cycle"
  },
  "btc_historical_event_reaction": {
    "tier1_gemma_capable": true,
    "tier1_reason": "12y backtest in training, batch query",
    "tier2_fallback": "Pyth Hermes historic /v2/updates/price/{ts}",
    "tier3_default": "btc_response_profile_per_event in calendar",
    "ttl_refresh": "weekly"
  },
  "fred_sigma_robust": {
    "tier1_gemma_capable": true | false,
    "tier1_reason": "<your call>",
    "tier2_fallback": "fred_init.py with MAD",
    "tier3_default": "V4-Alpha §4-bis.10 defaults",
    "ttl_refresh": "weekly"
  },
  "polymarket_midpoint": { ... },
  "polymarket_history": { ... },
  "fmp_economic_calendar": { ... },
  "investing_actual_values": { ... },
  "btc_response_profile_per_event": { ... },
  "trigger_sf_per_event": { ... },
  "capture_window_per_event": { ... },
  "comparator_go_criteria": { ... },
  "sigmoid_params": { ... },
  "tau_formula_weights": { ... }
}
```

Esto nos permite construir **`gemma_oracle.py`** en el sidecar que:
1. Lee `oracle_routing_table` del macro_calendar.json
2. Para cada parámetro, intenta Tier 1 (consulta Gemma)
3. Timeout / empty → Tier 2 API
4. Timeout / empty → Tier 3 static

Si dices "yes" a esta arquitectura, mañana Claude la construye junto
con el wiring Rust. Si dices "no" o "selectivamente" → indícame para
cuáles parámetros sí y cuáles no.

Gracias.
