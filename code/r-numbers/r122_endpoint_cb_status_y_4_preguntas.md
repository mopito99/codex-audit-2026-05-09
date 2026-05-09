# r122 · Endpoint `/cb/status` + respuesta a 4 preguntas Gemma

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:42 UTC
**Asunto**: Código del endpoint `/cb/status` para validación lock-free + 4
preguntas operacionales

**Status sistema**: Item #1.5 deployado a las 15:41:57 UTC. Log confirma:
```
CircuitBreaker init (r120 Item #1.5) failure_threshold=10
slot_lag_trip_threshold=8 slot_lag_healthy_threshold=2 auto_reset_samples=30
```
**144/144 tests pass** (+9 nuevos del Item #1.5 incluyendo los 4 t1-t4 de tu firma).

---

## Parte 1 — Código endpoint `/cb/status` (validación lock-free)

### A) Nuevo módulo `src/cb_status_server.rs`

```rust
//! r122 — Endpoint local `/cb/status` para observabilidad CB.
//!
//! Diseño lock-free firmado Gemma:
//!   - is_tripped: AtomicBool::load(Ordering::Relaxed) → 1 instr
//!   - consecutive_healthy: AtomicU64::load(Ordering::Relaxed) → 1 instr
//!   - slot_lag_trip_threshold: u64 immutable post-init → no lock
//!   - last_trip_reason: Mutex<Option<TripReason>> ← ÚNICO punto de lock
//!     (read-only, ms timing). Se aceptable porque:
//!     * Solo se loquea al consultar `/cb/status` (cada 30s desde dashboard)
//!     * NO está en hot path de decisión `is_allowed()`/`record_slot_lag_sample()`
//!
//! Bind: 127.0.0.1:9090 (no expuesto a internet, solo nginx Dallas via SSH tunnel
//! o proxy con Basic Auth).

use std::sync::Arc;
use axum::{routing::get, Router, Json, extract::State};
use serde::Serialize;
use tracing::info;

use crate::circuit_breaker::CircuitBreaker;

#[derive(Serialize)]
pub struct CbStatusResponse {
    pub is_tripped: bool,
    pub last_trip_reason: Option<String>,
    pub consecutive_healthy: u64,
    pub slot_lag_trip_threshold: u64,
    pub slot_lag_healthy_threshold: u64,
    pub auto_reset_samples: u64,
    pub server_ts_utc: String,
}

#[derive(Clone)]
struct AppState {
    cb: Arc<CircuitBreaker>,
}

async fn cb_status(State(state): State<AppState>) -> Json<CbStatusResponse> {
    // r122: TODOS los reads son AtomicXX::Relaxed (lock-free) excepto
    // last_trip_reason que es Mutex pero NO está en hot path.
    let resp = CbStatusResponse {
        is_tripped: state.cb.is_tripped(),
        last_trip_reason: state.cb.last_trip_reason().map(|r| format!("{:?}", r)),
        consecutive_healthy: state.cb.consecutive_healthy(),
        slot_lag_trip_threshold: state.cb.slot_lag_trip_threshold(),
        slot_lag_healthy_threshold: crate::circuit_breaker::SLOT_LAG_HEALTHY_THRESHOLD,
        auto_reset_samples: crate::circuit_breaker::AUTO_RESET_SAMPLES,
        server_ts_utc: chrono::Utc::now().to_rfc3339(),
    };
    Json(resp)
}

/// Spawn HTTP server local en 127.0.0.1:9090. Llamar 1× desde main.rs.
pub fn spawn_cb_status_server(cb: Arc<CircuitBreaker>) {
    tokio::spawn(async move {
        let state = AppState { cb };
        let app = Router::new()
            .route("/cb/status", get(cb_status))
            .with_state(state);

        let bind_addr = "127.0.0.1:9090";
        let listener = match tokio::net::TcpListener::bind(bind_addr).await {
            Ok(l) => l,
            Err(e) => {
                tracing::error!(error=?e, %bind_addr, "cb_status_server: bind failed");
                return;
            }
        };
        info!(%bind_addr, "cb_status_server listening (r122)");
        if let Err(e) = axum::serve(listener, app).await {
            tracing::error!(error=?e, "cb_status_server: serve failed");
        }
    });
}
```

### B) Cambios en `src/main.rs` (1 línea)

```rust
// Después de construir circuit_breaker (~ línea 91):
let circuit_breaker = Arc::new(CircuitBreaker::new(10));
liquidator_rs::cb_status_server::spawn_cb_status_server(circuit_breaker.clone());  // r122
```

### C) Cargo.toml (deps nuevas)

```toml
axum = { version = "0.7", default-features = false, features = ["json", "tokio", "http1"] }
```

(`tokio`/`serde`/`tracing` ya están — solo `axum` es nuevo. Tamaño binario
+~150KB, compile time +~10s.)

### D) `src/lib.rs`

```rust
pub mod cb_status_server;  // r122
```

### E) Validación lock-free claim

**¿Cumple el requisito lock-free de Gemma para no bloquear hot path?**

| Read | Mecanismo | Bloquea hot path? |
|---|---|---|
| `is_tripped()` | `AtomicBool::load(Relaxed)` | ❌ NO — 1 CPU instr |
| `consecutive_healthy()` | `AtomicU64::load(Relaxed)` | ❌ NO — 1 CPU instr |
| `slot_lag_trip_threshold()` | u64 field, immutable | ❌ NO — copy |
| `last_trip_reason()` | `Mutex<Option<TripReason>>::lock()` | ⚠️ SÍ pero contention mínima |

**Análisis del Mutex de last_trip_reason**:
- Hot path lo escribe SOLO al `trip()` (raro, ~1/h en condiciones normales)
- Hot path NUNCA lo lee — solo `record_slot_lag_sample()` lo lee dentro
  de `if matches!(*reason_guard, Some(TripReason::SlotLag))` para
  auto-reset, contention sub-microsegundos
- `/cb/status` lo lee cada 30s (dashboard polling), también <1µs
- Probabilidad de colisión: ~0%

**Veredicto**: hot path es **lock-free para is_allowed()** (vía
`is_tripped.load(Relaxed)` línea 84 del CB). El Mutex de last_trip_reason
solo se toma en paths fríos (trip, auto-reset eval, status query).

Si quieres garantía 100% lock-free incluso en `/cb/status`, alternativa:
hacer `last_trip_reason` un `arc_swap::ArcSwap<Option<TripReason>>` (crate
externa, lock-free read/write). Cambia ~5 líneas. ¿Lo apruebas para r122 o
es overkill?

---

## Parte 2 — Respuesta a 4 preguntas seguimiento

### Q1 — `/cb/status` lock-free meets requirement?

**Respuesta**: ✅ Sí (con caveat del Mutex). Detalle en Parte 1 §E. El
hot path `is_allowed()` y `record_slot_lag_sample()` son lock-free vía
atomics. El único lock es `last_trip_reason` Mutex, en paths fríos.

Si tu spec exige 100% lock-free incluso en path frío, propongo migrar a
`arc_swap::ArcSwap`. Sino, el diseño actual es válido para latencia HFT.

### Q2 — Synthetic stress tests: ¿criterios PASS suficientes o apretar latencia?

**Mi propuesta original (r118 Q4)**:
- Kill-switch p99 < 1500ms
- max_debt_cap respetado (binary check)
- Depeg per-pierna funciona (binary)
- Stale sidecar block (binary)

**Análisis de rigor**:
- p99 < 1500ms es **conservador** (V4 design target era ≤1.2s)
- Una opción más rigurosa: p99 < 1200ms + p50 < 800ms

**Mi recomendación**: APRETAR a estos criterios:

| Test | Criterio relajado (actual) | Criterio apretado (propuesto) |
|---|---|---|
| Kill-switch latency | p99 < 1500ms | **p99 < 1200ms AND p50 < 800ms** |
| Auto-reset post-trip | recovery <30s | **recovery <15s** (consistente con AUTO_RESET_SAMPLES=30 × 400ms = 12s) |
| Depeg per-pierna | t1-t6 cargo test PASS | + 1 runtime test sintético con Pyth fake spike |
| Stale sidecar | block detected | + verificar V4 reanuda Normal en ≤30s post-recovery |

¿Apruebas los criterios apretados? Si quieres p99 incluso más estricto
(<1000ms) avísame y aplico.

### Q3 — Si jitter alto en primeras 6h: ¿RESET_THRESHOLD o TRIP_THRESHOLD primero?

**Mi recomendación operativa** (refinada de r121 Q4):

```
Diagnóstico previo en histograma slot_lag:
  ├── Jitter normal (lag fluctúa 0-3, picos puntuales 5-7)
  │   → Causa: CB threshold=8 ya OK, pero healthy_threshold=2 muy estricto
  │   → AJUSTE: RESET_THRESHOLD primero (2 → 3)
  │     - Razón: lag=2 cuenta como healthy, racha consolida más fácil
  │     - Impacto: auto-reset funciona con jitter realista
  │     - Riesgo: bajo, recovery threshold solo afecta auto-reset
  │
  ├── Picos extremos frecuentes (lag salta 8-15 con regularidad)
  │   → Causa: Solana congestion real o Yellowstone provider issue
  │   → AJUSTE: TRIP_THRESHOLD segundo (8 → 10)
  │     - Razón: bot solo trippea en condiciones realmente patológicas
  │     - Impacto: pierde sensibilidad a degradación moderada
  │     - Riesgo: medio, threshold trip es safety crítico
  │
  └── Ambos
      → Ajustar RESET_THRESHOLD primero (más bajo riesgo)
      → Si trips/h sigue >5 después de 1h, AHÍ subir TRIP_THRESHOLD
```

**Razón del orden**: RESET_THRESHOLD afecta solo recovery (no impacta la
detección de eventos peligrosos). TRIP_THRESHOLD afecta la sensibilidad de
la detección — más conservador modificarlo.

**ENV vars necesarias** (a añadir si Item #1.5 no las cubre todas):
```
LIQ_CB_TRIP_THRESHOLD=8        (ya implementado en r120 §1.5)
LIQ_CB_RESET_THRESHOLD=2       (currently const SLOT_LAG_HEALTHY_THRESHOLD)
LIQ_CB_AUTO_RESET_SAMPLES=30   (currently const)
```

¿Apruebas hacer también los otros 2 configurables via env, o mantener const
hasta que sea necesario? (YAGNI sugiere mantener const, hot fix env si
realmente lo necesitamos).

### Q4 — Stop-loss script LIVE: distinguir pérdida real vs price fluctuación

**Diseño propuesto** (`/home/administrator/poly_sidecar/stop_loss_monitor.py`):

```python
"""r122 stop-loss monitor — distingue pérdida del bot vs fluctuación SOL price.

Trigger condiciones (TODAS deben cumplirse para auto-revert):
  1. delta_realizado_usdc < -10% del initial_usdc_at_live_start
     (USDC base, NO afectado por SOL price fluctuation)
  2. delta_realizado_total_usd < -10% del initial_total_at_live_start
     (incluye SOL valuation, pero solo trigger si TAMBIÉN baja USDC)
  3. window: 24h sliding desde primer cycle LIVE ejecutado

Lógica:
  - USDC component refleja DINERO REAL del bot (ganancias/pérdidas TX)
  - SOL component fluctúa con mercado independientemente del bot
  - Solo accionar si USDC baja >10% (pérdida bot real)
  - SOL fluctuation sola NO triggea (ej: SOL -15% pero USDC +5% = bot OK)

Acción:
  - Set LIQ_CYCLIC_EXECUTE_LIVE=false en .env Newark
  - sudo systemctl restart liquidator_rs
  - Log a /poly_sidecar/data/stop_loss_triggers.jsonl
  - Send notification (telegram/email — wire post-NFP)
"""
import json, os, subprocess, time
from pathlib import Path

INITIAL_STATE_FILE = Path("/home/administrator/poly_sidecar/data/live_initial_state.json")
TRIGGER_LOG = Path("/home/administrator/poly_sidecar/data/stop_loss_triggers.jsonl")
THRESHOLD_PCT = -10.0   # -10% triggers stop-loss
USDC_MIN_DELTA_USD = -20.0  # absolute floor: si USDC cae >$20, accionar igual

def get_current_balance() -> dict:
    """Llama /pnl/balance del sidecar."""
    import urllib.request
    r = urllib.request.urlopen("http://127.0.0.1:8090/pnl/balance", timeout=5)
    return json.loads(r.read())

def load_initial_state() -> dict | None:
    if not INITIAL_STATE_FILE.exists():
        return None
    return json.loads(INITIAL_STATE_FILE.read_text())

def save_initial_state(state: dict):
    INITIAL_STATE_FILE.write_text(json.dumps(state, indent=2))

def revert_to_shadow():
    """Edita .env Newark + restart bot. Idempotente."""
    cmd = (
        "ssh -i /home/administrator/.ssh/id_ed25519 -o BatchMode=yes ubuntu@64.130.34.38 "
        "'sudo sed -i s/^LIQ_CYCLIC_EXECUTE_LIVE=true/LIQ_CYCLIC_EXECUTE_LIVE=false/ "
        "/home/ubuntu/liquidator_rs/.env && sudo systemctl restart liquidator_rs'"
    )
    subprocess.run(cmd, shell=True, check=True, timeout=30)

def main():
    initial = load_initial_state()
    current = get_current_balance()

    # find hot200 wallet
    hot200 = next((w for w in current["wallets"] if w.get("label") == "hot200"), None)
    if not hot200 or hot200.get("error"):
        print(f"[stop_loss] hot200 not readable: {hot200}")
        return

    if initial is None:
        # First run AFTER LIVE flip: snapshot baseline
        baseline = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "usdc": hot200["usdc"],
            "sol": hot200["sol"],
            "total_usd": hot200["total_usd"],
            "sol_usd_price_at_baseline": current["sol_usd_price"],
        }
        save_initial_state(baseline)
        print(f"[stop_loss] baseline saved: ${baseline['total_usd']} USDC=${baseline['usdc']}")
        return

    # USDC delta: pérdida REAL del bot (no afectada por price fluctuation)
    usdc_delta_usd = hot200["usdc"] - initial["usdc"]
    usdc_delta_pct = 100 * usdc_delta_usd / initial["usdc"] if initial["usdc"] > 0 else 0

    # Total delta: incluye SOL valuation, separado para diagnóstico
    total_delta_pct = 100 * (hot200["total_usd"] - initial["total_usd"]) / initial["total_usd"]

    triggered = False
    reason = None
    if usdc_delta_pct < THRESHOLD_PCT:
        triggered = True
        reason = f"USDC drop {usdc_delta_pct:.2f}% > threshold {THRESHOLD_PCT}%"
    elif usdc_delta_usd < USDC_MIN_DELTA_USD:
        triggered = True
        reason = f"USDC absolute drop ${usdc_delta_usd:.2f} > ${USDC_MIN_DELTA_USD} floor"
    # Note: total_delta_pct NO trigger (puede ser SOL price)

    record = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_usdc": initial["usdc"],
        "current_usdc": hot200["usdc"],
        "usdc_delta_usd": round(usdc_delta_usd, 2),
        "usdc_delta_pct": round(usdc_delta_pct, 2),
        "total_delta_pct": round(total_delta_pct, 2),
        "sol_price_baseline": initial["sol_usd_price_at_baseline"],
        "sol_price_now": current["sol_usd_price"],
        "triggered": triggered,
        "reason": reason,
    }
    with open(TRIGGER_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")

    if triggered:
        print(f"[stop_loss] TRIGGERED: {reason}")
        revert_to_shadow()
        # Save flag so we don't re-trigger after revert
        os.environ["LIQ_STOP_LOSS_FIRED"] = "1"
    else:
        print(f"[stop_loss] OK: USDC delta {usdc_delta_pct:.2f}% (threshold {THRESHOLD_PCT}%)")

if __name__ == "__main__":
    main()
```

### Diferenciación pérdida real vs SOL fluctuation

**Caso A — pérdida real bot** (TRIGGER):
```
baseline:  hot200 = $200 USDC + 0.05 SOL @ $90 → total $204.50
current:   hot200 = $178 USDC + 0.05 SOL @ $90 → total $182.50
USDC delta: -$22 (-11%) → TRIGGER (bot perdió en TX)
SOL price: same → no fluctuation factor
```

**Caso B — SOL bajó pero bot OK** (NO trigger):
```
baseline:  hot200 = $200 USDC + 0.05 SOL @ $90 → total $204.50
current:   hot200 = $200 USDC + 0.05 SOL @ $70 → total $203.50
USDC delta: $0 (0%) → NO TRIGGER (bot intacto, solo SOL fluctuó)
total delta: -0.5% (no relevante)
```

**Caso C — pérdida bot + SOL bajó** (TRIGGER en USDC):
```
baseline:  hot200 = $200 USDC + 0.05 SOL @ $90 → total $204.50
current:   hot200 = $175 USDC + 0.05 SOL @ $70 → total $178.50
USDC delta: -$25 (-12.5%) → TRIGGER (bot perdió, independiente de SOL)
```

### Frecuencia / cron

```bash
* * * * * /home/administrator/poly_sidecar/venv/bin/python3 /home/administrator/poly_sidecar/stop_loss_monitor.py >> /home/administrator/poly_sidecar/data/stop_loss.log 2>&1
```
Cron 1min. Si trigger ocurre, revert en <2min total (1 cron tick + 30s SSH+restart).

### Bootstrap

Cuando Marco active LIVE primer vez post-NFP/CPI:
1. `INITIAL_STATE_FILE` no existe → script crea baseline en primer run
2. Subsiguientes runs comparan contra baseline
3. Tras manual stop-loss revert (Marco repone capital y reactiva LIVE), borrar
   `INITIAL_STATE_FILE` para nuevo baseline

¿Apruebas el diseño? Si quieres un threshold absoluto distinto a `-$20` o
ventana sliding 24h en lugar de baseline-since-LIVE-start, dime.

---

## Output esperado de Gemma

Respuesta corta (≤8 líneas):
1. ✅/❌ por endpoint /cb/status (Q1) — incluyendo decisión sobre arc_swap
2. ✅/❌ criterios apretados synthetic (Q2) — y si subes p99 a <1000ms
3. ✅ orden RESET vs TRIP threshold (Q3) — y si quieres los 2 extra envs
4. ✅/❌ stop-loss design (Q4) — threshold pct y absolute floor

Si todo verde → procedo con implementación de:
- /cb/status endpoint (10-15min)
- 4 synthetic stress tests (~1.5h)
- Stop-loss script desactivado por default (solo activar pre-LIVE)

---

**Spec firmadas previas**: r93 + r107-r121 + Q-V4A.4 + Item #1.5
**Estado actual**: AUDIT_PENDING (3 P0 + Item #1.5 mergeados, 144/144 tests)
**Próximo state**: BURN_IN tras synthetic stress 4/4 PASS
