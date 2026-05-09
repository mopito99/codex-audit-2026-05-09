VelocityQuant — Brief implementación: 5 preguntas técnicas para wiring miércoles
==================================================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~11:30 UTC
Asunto: Última ronda antes del wiring Rust mañana mié. Tus 5 follow-ups
        sugeridas — pido respuesta JSON estructurada para parsing
        automático y arranque código directo.

---

# CONTEXTO

Tu respuesta del JSON r89 firmó:
- Pyth daily snapshots → swap a Coinbase Advanced Trade
- `Arc<RwLock<MacroState>>` (no AtomicPtr)
- Source-Validator layer + consensus logic
- GO formal para wiring Rust mié
- Oracle Routing Table 13 parámetros (10 Tier 1 / 3 Tier 2)

Antes de programar mañana necesito **5 cosas concretas más** — son tus
follow-ups del último mensaje:

---

# Q1 — Rust implementation: Source-Validator layer + Arc<RwLock<MacroState>>

Necesito el esqueleto de código exacto. Mi propuesta:

```rust
use std::sync::{Arc, RwLock};
use std::time::{Instant, Duration};

#[derive(Clone, Debug)]
struct MacroState {
    tau_final: f64,
    mode: Mode,
    rho: Option<f64>,
    next_event: Option<EventInfo>,
    sources: SourceStatus,
    last_update: Instant,
}

struct SourceStatus {
    btc_spot: ValidatedSource<f64>,
    polymarket: ValidatedSource<f64>,
    fmp: ValidatedSource<EventInfo>,
    investing: ValidatedSource<f64>,
}

struct ValidatedSource<T> {
    primary: Option<T>,    // Coinbase / Pyth / Polymarket
    secondary: Option<T>,  // Kraken / fallback
    consensus: Option<T>,  // computed via consensus logic
    timestamp: Instant,
    is_stale: bool,
}

// Background thread cada 10s
fn refresh_macro_state(state: Arc<RwLock<MacroState>>) {
    loop {
        let new_state = read_atomic_store_with_validation();
        *state.write().unwrap() = new_state;
        thread::sleep(Duration::from_secs(10));
    }
}

// Dispatch loop (cada slot)
fn use_macro_state(state: &Arc<RwLock<MacroState>>) -> u8 {
    let s = state.read().unwrap();   // O(1) non-blocking
    final_threshold(base_th, &*s)
}
```

Devuelve en JSON respuesta:
- ¿Estructura aceptada o cambio?
- Si cambio → Rust snippet exacto
- ¿Cuál es la lógica de consenso para BTC (3 fuentes)?
  - Median? Mean? Si max(Δ) > X% entre fuentes → discard?

---

# Q2 — Coinbase Advanced Trade: implementación eficiente de 1-min candles

Para capturar spikes intra-evento, ¿cuál es la forma más eficiente:

- (a) Polling cada 60s del endpoint `/candles?granularity=ONE_MINUTE`
- (b) WebSocket subscription a `BTC-USD ticker` y agregación local en
  buckets de 1min
- (c) REST + cache circular en memoria con replacement strategy

Restricción: el sidecar ya hace polling 5min. El cycle BTC granularity
puede ser distinto (1min) sin desincronizar el resto?

Devuelve:
- método elegido + razón
- params endpoint exactos
- cómo manejar timestamps si vienen en ms vs unix
- TTL cache recomendada

---

# Q3 — `ask_gemma.py` bridge: JSON routing table + TTL caching

Mi `ask_gemma.py` actual hace 1 call → 1 respuesta texto. Ahora con
oracle routing necesito:

1. **JSON routing table** detect: si Gemma responde con campo
   `tier1_capable: false` → fallback automático
2. **TTL caching**: weekly params NO se reconsultan cada vez. Cached
   en `macro_calendar.json` con `last_gemma_refresh_utc`. Si TTL
   expirado → re-consultar.
3. **Batch query**: en lugar de 10 calls separadas para 10 params,
   1 call con prompt template estructurado pidiendo JSON con N campos.

Mi propuesta:
```python
class GemmaOracle:
    def __init__(self, calendar_path):
        self.calendar = load_calendar(calendar_path)
        self.cache = self.calendar.get("gemma_oracle_cache", {})
    
    def get(self, param_name):
        ttl = self.calendar["oracle_routing_table"][param_name]["ttl_refresh"]
        cached = self.cache.get(param_name, {})
        if cached and not self._ttl_expired(cached, ttl):
            return cached["value"]
        # Tier 1: try Gemma
        value = self._gemma_query(param_name) 
        if value is not None:
            self._update_cache(param_name, value)
            return value
        # Tier 2: fallback API
        return self._tier2_fallback(param_name)
```

Devuelve:
- ¿OK con esta arquitectura o cambio?
- ¿Prompt template estándar para batch query?
- ¿Cómo formatear el JSON request para que tu respuesta sea parseable?

---

# Q4 — Deep dive: sigmoid_params + tau_formula_weights para régimen actual

Antes del wiring, validar para régimen mercado actual (mayo 2026):

**Sigmoid params actuales firmados:**
```
ΔProb     : k=10  x0=0.10
VolZScore : k=2   x0=1.0
ImpliedVol: k=50  x0=0.02
```

**τ formula weights actuales:**
```
τ = 0.5·norm(ΔProb) + 0.3·norm(VolZScore) + 0.2·norm(ImpliedVol)
τ_final = 0.7·τ_crypto + 0.3·τ_macro
```

**Pregunta:** ¿estos valores siguen óptimos para el régimen de mayo
2026, o requieren ajuste basado en tu backtest? Considera:
- Calmness reciente feb-mar 2026 (BTC reactions <0.2% según Pyth, pero
  spikes reales >2% según tu backtest tick-level)
- Régimen post-2021 inflación → CPI sensitivity +210%
- τ_macro/τ_crypto split — si crypto va más calmo, ¿re-balancear
  hacia macro?

Devuelve:
- Si actuales OK: confirma sin cambio
- Si requiere ajuste: nuevos valores + razón cuantitativa

---

# Q5 — Pyth Sequential Timestamp Probe: multi-source consensus o swap directo

Tu test que sugieres:
> "Request price for T+1min, T+2min, T+3min, T+4min, T+5min. If delta=0
> across all 5, it's a snapshot."

Lo voy a ejecutar HOY antes del wiring.

**Si confirma staleness (probable):** ¿multi-source consensus en Rust
(Coinbase + Kraken + Pyth con majority vote) o hardcode swap directo
(Coinbase only, Pyth deprecated)?

Trade-offs:
- **Consensus 3 fuentes:** redundancia, detecta outliers, latencia
  +50ms por la 3ra source
- **Coinbase only:** simplicidad, latencia mínima, single point of failure

Devuelve:
- recomendación específica
- si consensus → algoritmo (median? majority? weighted?)
- si swap → confirmar Coinbase como única primary

---

# FORMATO DE RESPUESTA (JSON exacto)

```json
{
  "q1_rust_validator_layer": {
    "structure_accepted": true | false,
    "rust_snippet_corrections": "<code or null>",
    "consensus_logic_btc": {
      "method": "median | mean | majority | weighted",
      "outlier_rejection_threshold_pct": <number>,
      "min_sources_required": <int>
    }
  },
  "q2_coinbase_implementation": {
    "method": "polling | websocket | hybrid",
    "rationale": "<short>",
    "endpoint_params": {
      "url": "<full URL>",
      "granularity": "<ONE_MINUTE | etc>",
      "...": "..."
    },
    "timestamp_format": "ms | unix_seconds",
    "cache_ttl_seconds": <int>
  },
  "q3_gemma_oracle_bridge": {
    "architecture_accepted": true | false,
    "corrections": "<text or null>",
    "batch_prompt_template": "<template string with {placeholders}>",
    "json_response_schema_for_batch": "<JSON schema or example>"
  },
  "q4_sigmoid_tau_weights_review": {
    "current_optimal": true | false,
    "if_not_optimal": {
      "new_sigmoid_params": { ... },
      "new_tau_weights": { ... },
      "rationale": "<short>"
    }
  },
  "q5_pyth_decision": {
    "approach": "consensus | swap",
    "if_consensus": {
      "algorithm": "<median | weighted etc>",
      "sources": ["Coinbase", "Kraken", "Pyth"],
      "weights": [0.5, 0.3, 0.2]
    },
    "if_swap": {
      "primary": "Coinbase",
      "deprecate_pyth": true | false,
      "fallback_chain": ["Kraken", "CryptoCompare"]
    }
  },
  "ready_to_code_tomorrow_morning": true | false,
  "any_blockers_remaining": "<text or null>"
}
```

---

Después de tu respuesta JSON, mañana mié 09:00 UTC arranco código.
Tu última firma cuantitativa.

Gracias.
