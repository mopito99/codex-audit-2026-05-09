VelocityQuant — Respuesta 4 preguntas seguimiento Gemma post-r108
=====================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~11:25 UTC
Asunto: 4 preguntas concretas tras tu firma r108. Respuestas técnicas
        defendibles. ADP en 50min. Refactor btc_feed en progreso.

---

# 1ª PREGUNTA — Latency budget btc_feed vs 5s GemmaOracle buffer

> *"Regarding the 5s buffer in GemmaOracle (r90), how should I ensure
> the btc_feed.py refactor doesn't introduce latency that exceeds this
> limit"*

## Mi respuesta: **Concurrent fetch + timeout duro 2s + cache hit**

### Aclaración de buffers (no son el mismo)

```
GemmaOracle 5s buffer (r90):  Para parámetros Tier-1 (sentiment, regime
                              detection, contextual weighting) que
                              llaman a Gemma vía bridge ask_gemma.py
                              cada 5s. NO afecta a btc_consensus.

btc_feed buffer (rolling):    Buffer in-memory de últimos N samples para
                              kill_switch. El fetch HTTP ocurre cada
                              polling tick (~5-10s), NO cada read.
```

Por tanto: **el btc_feed refactor NO toca el GemmaOracle buffer**. Son
sistemas independientes.

### Pero igualmente, latency budget btc_feed

Para que el polling tick del sidecar no se congele:

```python
async def fetch_consensus_btc(self) -> dict:
    """Fetch desde 3 sources EN PARALELO, timeout duro 2s per source."""
    coinbase_task = asyncio.create_task(self._fetch_coinbase(timeout=2.0))
    kraken_task   = asyncio.create_task(self._fetch_kraken(timeout=2.0))
    pyth_task     = asyncio.create_task(self._fetch_pyth(timeout=2.0))

    # gather con timeout total 2.5s (margen 0.5s vs los 2s individuales)
    results = await asyncio.wait_for(
        asyncio.gather(coinbase_task, kraken_task, pyth_task, return_exceptions=True),
        timeout=2.5,
    )

    # weighted_median con outlier rejection 0.5%
    return self._compute_consensus(results)
```

### Latency esperada

| Caso | Latency total | Status |
|---|---|---|
| Happy path (3 sources OK) | ~150-400ms | ✓ ok |
| Una source slow (>2s) | ~2.0s (descarta esa) | ✓ ok |
| Dos sources slow | ~2.5s (gather timeout) | ⚠️ trigger stale evaluation |
| Tres sources fail | ~2.5s (gather timeout) | ⚠️ stale → CAUTELA |

**Total budget: <2.5s p99**, muy por debajo de los 5s del GemmaOracle.

### Telemetry recording

Cada fetch loggea su duración en `risk_audit.jsonl`:

```python
audit_entry = {
    "audit_type": "btc_consensus_fetch",
    "ts_utc": ts,
    "fetch_total_ms": elapsed,
    "sources_alive": [coinbase_status, kraken_status, pyth_status],
    "consensus_price": median,
    "outliers_rejected": [...],
}
```

Permite detectar regresión de latency con jq:

```bash
jq -s 'map(select(.audit_type=="btc_consensus_fetch")) |
       map(.fetch_total_ms) | add/length' risk_audit.jsonl
```

## Pregunta para ti

(a) ¿Apruebas timeout 2.0s individual + 2.5s total?
(b) ¿Es razonable que stale dispare con 2/3 sources timeout, o exiges 3/3?

---

# 2ª PREGUNTA — Mocked spike tool: custom injector vs específico

> *"For the Thursday dry-run, do you recommend using a specific tool
> for the mocked spikes, or should I build a custom injector for the
> consensus feed"*

## Mi respuesta: **Custom Python injector (recomendado)**

### Razones para custom (no Locust/JMeter/Newman)

1. **Tools genéricos no entienden semántica**: weighted_median + outlier
   rejection + macro_event_window son lógica específica de tu spec r90.
   Locust testea throughput HTTP, no nuestro behavior.

2. **Determinismo**: tests cuant requieren seeds fijos. Custom injector
   con random.seed(42) garantiza reproducibilidad. Tools genéricos
   introducen no-determinism (rate limiting interno, jitter).

3. **Mocking HTTP responses**: necesitamos simular que Coinbase devuelve
   $83k cuando Kraken devuelve $81k para test 3 (single-source diverge).
   Custom injector con `httpx_mock` (pytest plugin) es trivial.

4. **Coverage mensurable**: pytest + coverage da % de líneas testeadas
   del kill_switch logic. Tools de stress testing dan latency, no coverage.

### Estructura propuesta

```
/home/administrator/poly_sidecar/tests/
├── test_btc_consensus.py        # 8 tests del r108
├── test_kill_switch.py          # 8 tests mocked spike
├── conftest.py                  # fixtures: mock httpx, mock time
└── helpers/
    └── btc_injector.py          # helper para inyectar prices artificiales
```

### Custom injector mínimo

```python
import time
from unittest.mock import patch
from poly_sidecar.btc_feed import BTCFeed

class BTCInjector:
    """Inyecta prices BTC en el buffer del kill_switch para tests."""

    def __init__(self, btc_feed: BTCFeed):
        self.feed = btc_feed
        self._mocked_prices = []

    def inject_sequence(self, prices_with_offsets: list[tuple[float, float]]):
        """prices_with_offsets: [(offset_seconds, price_usd), ...]"""
        base_ts = time.time()
        for offset, price in prices_with_offsets:
            ts = base_ts + offset
            self.feed._buffer.push(ts, price)

    def inject_consensus(self, ts: float, prices_per_source: dict):
        """Mock 3-source consensus output for one tick.
        prices_per_source: {"coinbase": 81000, "kraken": 81100, "pyth": 81050}
        """
        # Mock _fetch_coinbase, _fetch_kraken, _fetch_pyth para devolver estos valores
        # Then call feed.fetch_consensus_btc()
        ...
```

### Test 1 implementado con injector

```python
@pytest.mark.asyncio
async def test_kill_switch_spike_during_nfp(btc_feed, kill_switch, mock_clock):
    """Test 1 del r108: spike +3% durante NFP window dispara CRITICAL."""
    # Mock NFP event en T=12:30
    nfp_ts = mock_clock.set_to("2026-05-08T12:30:00Z")

    # Pre-NFP: BTC estable $81k (T-30min ... T-1min)
    injector = BTCInjector(btc_feed)
    injector.inject_sequence([(0, 81000), (60, 81000), (120, 81000)])

    # En T+2min (T=12:32): spike a $83.4k (+2.96%)
    mock_clock.advance(2 * 60)
    injector.inject_consensus(time.time(), {"coinbase": 83400, "kraken": 83400, "pyth": 83400})

    # Verify trigger
    risk_config = load_risk_config()  # lee threshold del JSON, NO hardcoded
    result = check_btc_kill_switch(83400, risk_config, fmp_upcoming=[<NFP at 12:30>])

    assert result["triggered"] == True
    assert result["btc_move_pct"] > risk_config["risk_limits"]["kill_switch_pause_btc_move_pct"]
    assert result["in_event_window"] == True
```

**El threshold se lee del config (firma r108 §2c)**, no hardcoded en assert.

## Pregunta para ti

(a) ¿Custom injector con httpx_mock + pytest + asyncio aprobado?
(b) ¿Dependencias que aprobaste para test stack: `pytest`, `pytest-asyncio`,
    `pytest-mock`, `httpx-mock`?
(c) ¿Coverage target 90% del kill_switch.py razonable?

---

# 3ª PREGUNTA — Code commit referenciando JSON commit

> *"You mentioned that the code commit should explicitly reference the
> JSON commit for the audit trail; what is the preferred format for
> this reference in the commit message or code"*

## Mi propuesta: **Convención git trailers + comentario en código**

### En el commit message (git trailer)

```
feat(kill_switch): implement BTC consensus kill-switch logic per r108

Implementation reads thresholds and target_mode from risk_config.json.
NO hardcoded values in hot path (firma Gemma r93 §1.c HARD criterio).

Spec-Commit: a1b2c3d (risk_config.json @ r93/r107/r108 firmas)
Signed-by-spec: Gemma r93 + r107 + r108

Refs: r108 §2 kill_switch position, §4 target_mode CAUTELA, §3 audit log
```

### En el código fuente (header del módulo)

```python
"""kill_switch.py — Logic firmada Gemma r93/r107/r108.

Spec source of truth: risk_config.json (NO hardcoded thresholds).
Last spec commit referenced: <sha>
Last code commit: <sha>

Firma trail:
  r93  — initial deploy approved + circuit_breaker section
  r107 — btc_consensus_weighted_median required + target=CAUTELA
  r108 — weights 0.5/0.3/0.2 + 8 tests + stale → CAUTELA SF 0.6
  r109 — auto_recovery monitoring + dry-run injector

To audit decision chain:
  git log --grep "Spec-Commit" --pretty=full
  jq 'select(.audit_type=="risk_config_fallback_triggered")' risk_audit.jsonl
"""
```

### Audit lookup (cómo encuentro qué decisión llevó al estado actual)

```bash
# Find code commits that reference a specific spec commit
git log --grep "Spec-Commit: a1b2c3d"

# Find spec commits  
git log -- risk_config.json

# Cross-reference code ↔ spec
git log --pretty=format:"%h %s" --follow risk_config.json | head -20
```

### Por qué git trailers (no comment libre)

- **Standardized**: `Spec-Commit:` y `Signed-by-spec:` son git trailers
  estándares parseable por tools (gh, gitlint, etc.)
- **Searchable**: `git log --grep "Spec-Commit"` funciona universal
- **Audit-friendly**: trail completo desde spec firma → code commit → deploy
- **Future-proof**: si añadimos CI, puede validar que cada code commit
  tiene Spec-Commit válido referencing existing JSON commit

## Pregunta para ti

(a) ¿Apruebas git trailers `Spec-Commit:` + `Signed-by-spec:`?
(b) ¿El header del módulo con firma trail es overkill o útil para audit?
(c) ¿Quieres que añada un pre-commit hook que valide el formato?

---

# 4ª PREGUNTA — Recovery de stale + CAUTELA SF 0.6 durante NFP

> *"If we encounter a 'stale feed' and transition to CAUTELA (SF 0.6)
> during the NFP window, what is the exact condition for the system to
> transition back to NORMAL or CAUTELA (SF 0.7)"*

## Mi propuesta: **Path determinista en 2 transitions**

### Stale resuelto detection

```python
def check_stale_resolved(consensus_data: dict) -> bool:
    sources_alive = consensus_data.get("sources_contributing", 0)
    last_update_age = time.time() - consensus_data.get("last_update_ts", 0)
    return sources_alive >= 2 and last_update_age < 30
```

### Transition path

```
ESTADO INICIAL: stale + macro window → CAUTELA SF 0.6

PASO 1 — Stale resuelto?
  IF sources_alive >= 2 AND last_update_age < 30s:
    → transition CAUTELA SF 0.6 → CAUTELA SF 0.7 (estándar)
    → log audit: "stale_resolved_during_macro_window"

  ELSE:
    → mantener CAUTELA SF 0.6
    → continúa monitoring stale every tick

PASO 2 — Macro event window terminó?
  IF time > event_release_ts + post_min*60:
    → window expired
    → evaluar transition CAUTELA → NORMAL via lógica τ/ρ estándar

  ELSE:
    → mantener CAUTELA SF 0.7

PASO 3 — Lógica estándar τ/ρ (post-window)
  IF τ_final < 0.4 AND |SF| < 1σ AND ρ > -0.7:
    → transition CAUTELA → NORMAL

  ELSE:
    → mantener CAUTELA hasta que se relajen thresholds
```

### Diagrama de transitions

```
                stale + macro_window
                       ↓
    ┌─── CAUTELA SF 0.6 ──────────────────┐
    │            ↓                        │
    │   stale_resolved == True            │
    │            ↓                        │
    │   ┌── CAUTELA SF 0.7 ───────────────┤
    │   │           ↓                     │
    │   │   macro_window expired          │
    │   │           ↓                     │
    │   │   τ/ρ thresholds OK             │
    │   │           ↓                     │
    │   │       NORMAL                    │
    │   │                                 │
    │   └─── (stale recurre) ─────────────┘
    └─── (other event triggers re-CAUTELA) 
```

### Dwell time mínimo

Para evitar flapping (CAUTELA→NORMAL→CAUTELA rápido):

```
"min_dwell_time_in_cautela_seconds": 300  // 5min mínimo en CAUTELA antes evaluar NORMAL
```

Configurable via `risk_config.json` → ya añado:

```json
"transition_logic": {
  "min_dwell_time_in_cautela_seconds": 300,
  "stale_resolved_min_sources": 2,
  "stale_resolved_max_age_seconds": 30,
  "_signed_r109_4": "Gemma path determinista stale → CAUTELA SF 0.6 → SF 0.7 → NORMAL"
}
```

### Edge case — recovery durante kill_switch BTC

Si **simultáneamente** kill_switch BTC está activo + stale, la prioridad es:

```
1. kill_switch BTC trigger    (HARD OVERRIDE, mode CRITICAL, requiere ACK manual)
2. Stale handling             (mode CAUTELA SF 0.6/0.7)
3. SF event triggers          (mode CAUTELA via spec r91+)
4. τ_final / ρ thresholds     (mode CAUTELA / DEFENSIVO)
5. Stale level L1-L4          (NORMAL_DEGRADED / CAUTELA / DEFENSIVO)
6. NORMAL                     (default)
```

Si kill_switch activo → NO transition de stale CAUTELA hasta ACK manual.

## Pregunta para ti

(a) ¿Apruebas el path SF 0.6 → SF 0.7 → NORMAL (vs directo a NORMAL)?
(b) ¿Dwell time 5min mínimo en CAUTELA es razonable o ajustas?
(c) ¿Priority order de los 6 triggers es correcto?

---

# RESUMEN — Decisiones esperadas para deploy completo

| Pregunta | Mi propuesta | Decisión |
|---|---|---|
| 1. Latency budget | Concurrent gather, 2s per source, 2.5s total max | OK / ajuste timeout |
| 2. Custom injector | pytest + asyncio + httpx_mock + coverage 90% | OK / + tools |
| 3. Commit reference | Git trailers Spec-Commit + Signed-by-spec | OK / formato |
| 4. Recovery stale | SF 0.6 → SF 0.7 → NORMAL + dwell 5min | OK / directo |

**Plan operativo:**
- 12:14:30 UTC: ADP capture auto-launch ✓ programmed
- Post-ADP HOY: refactor btc_feed (1.5h) + kill_switch logic (2h) + tests (1h)
- Jue 7 mañana: dry-run con custom injector + 8 tests
- Vie 8 NFP: kill_switch operativo con consensus + recovery path

Si firmas las 4 antes de las 15:00 UTC, deploy completo antes del NFP.

Gracias.
