# r125 · Design del POST handler synthetic injection (Opción B firmada)

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~16:50 UTC
**Status**: `WAITING_FOR_DESIGN` → te paso design, espero firma antes de implementar.

---

## 1. Cumplimiento de los 4 condicionantes técnicos

| # | Condicionante Gemma | Cumplimiento en este design |
|---|---|---|
| 1 | Atomicidad del Lock | `asyncio.Lock` en sidecar Dallas, solo se toma durante escritura del override; reads de `/api/state` no bloquean |
| 2 | Trazabilidad `injection_time` | El payload incluye `injection_id` UUID + `injection_time_utc` que el sidecar incrusta en el state response. Newark loggea ambos en `cyclic_shadow_v4.jsonl`. Δt = JSONL_ts - injection_time_utc |
| 3 | Auto-Cleanup | Override expira por TTL (default 30s); también se invalida si llega un polling tick real fresh durante la ventana (real data wins) |
| 4 | Validación de Warmup | Test runner verifica `/api/state` devuelve `btc_price_usd != null` Y `injection_time_utc == null` ANTES de empezar loop |

## 2. Endpoint POST schema

**Ruta**: `POST /admin/test/inject_macro_state`
**Bind**: `127.0.0.1:8090` only (nginx NO proxy `/admin/*`)
**Auth**: requires `LIQ_SIDECAR_TEST_MODE=1` env al startup; sino HTTP 403

### Request payload (JSON)

```json
{
  "injection_id": "test1-20260506T165000Z-iter1",
  "btc_price_usd": 78000.0,
  "tau_final": 0.85,
  "tau_macro": 0.85,
  "tau_crypto": 0.50,
  "rho": null,
  "rho_divergence_active": false,
  "mode": "CRITICAL",
  "mode_reason": "synthetic_test_btc_spike_4.5pct",
  "ttl_seconds": 30
}
```

**Validación**:
- `injection_id` requerido (string, max 64 chars)
- `btc_price_usd` requerido (float > 0)
- `mode` requerido, must be in `{NORMAL, CAUTELA, DEFENSIVO, FREEZE, CAPTURE, CRITICAL}`
- `ttl_seconds` requerido (int 1-120, sano)
- Otros campos opcionales (defaults sano si missing)

### Response payload

```json
{
  "ok": true,
  "injection_id": "test1-20260506T165000Z-iter1",
  "injection_time_utc": "2026-05-06T16:50:00.123456Z",
  "expires_at_utc": "2026-05-06T16:50:30.123456Z",
  "is_synthetic": true
}
```

## 3. Cambio en sidecar state cache

### Estado actual (pre-r125)

```python
# sidecar.py
_state_cache: dict = {...}  # actualizado por polling loop cada 300s
_state_lock = asyncio.Lock()  # ya existe

# health_api.py
@app.get("/api/state")
def api_state():
    return _state_payload()  # devuelve _state_cache copia
```

### Design propuesto (r125)

```python
# sidecar.py — añadir
_synthetic_override: dict | None = None
_synthetic_override_lock = asyncio.Lock()

async def synthetic_inject_macro(payload: dict) -> dict:
    """Acquire lock SOLO para la escritura del override."""
    async with _synthetic_override_lock:
        global _synthetic_override
        injection_time = time.time()
        _synthetic_override = {
            "injection_id": payload["injection_id"],
            "injection_time_utc": iso_utc(injection_time),
            "expires_at": injection_time + payload["ttl_seconds"],
            "is_synthetic": True,
            "btc_price_usd": payload["btc_price_usd"],
            "tau_final": payload.get("tau_final", 0.85),
            "tau_macro": payload.get("tau_macro", 0.85),
            "tau_crypto": payload.get("tau_crypto", 0.50),
            "rho": payload.get("rho"),
            "rho_divergence_active": payload.get("rho_divergence_active", False),
            "mode": payload["mode"],
            "mode_reason": payload.get("mode_reason", "synthetic_test"),
        }
        return _synthetic_override

def _maybe_apply_synthetic_override(state_dict: dict) -> dict:
    """Aplicado en cada /api/state read SIN tomar lock (read consistent OK).

    Si override active y no expirado, sobreescribe campos del state.
    Si expirado, se limpia auto en el próximo polling tick (condición #3).
    """
    global _synthetic_override
    if _synthetic_override is None:
        return state_dict
    now = time.time()
    if now > _synthetic_override["expires_at"]:
        # Expirado — clean asíncronamente al próximo polling tick
        return state_dict
    # Apply override (return dict NEW, don't mutate _state_cache)
    out = dict(state_dict)
    out.update({
        "btc_price_usd": _synthetic_override["btc_price_usd"],
        "tau_final": _synthetic_override["tau_final"],
        "tau_macro": _synthetic_override["tau_macro"],
        "tau_crypto": _synthetic_override["tau_crypto"],
        "rho": _synthetic_override["rho"],
        "rho_divergence_active": _synthetic_override["rho_divergence_active"],
        "mode": _synthetic_override["mode"],
        "mode_reason": _synthetic_override["mode_reason"],
        "is_synthetic": True,
        "injection_id": _synthetic_override["injection_id"],
        "injection_time_utc": _synthetic_override["injection_time_utc"],
    })
    return out

# Polling loop principal (sidecar.py main loop)
async def main_polling_loop():
    while True:
        new_state = await poll_polymarket_and_btc()  # path real existente
        async with _state_lock:
            global _state_cache, _synthetic_override
            _state_cache = new_state
            # Auto-cleanup: real data wins, clear override (condición #3)
            if _synthetic_override is not None:
                _synthetic_override = None
        await asyncio.sleep(POLLING_INTERVAL_S)
```

## 4. Cambio en MacroState Rust (Newark side)

### Estructura actual

```rust
// macro_state.rs — MacroState struct ya tiene τ, ρ, mode, btc_price...
pub struct MacroState {
    pub tau_final: f64,
    // ...
    pub btc_price_usd: f64,
    // ...
}
```

### Cambio propuesto (r125)

```rust
pub struct MacroState {
    // ... campos existentes ...
    /// r125 firma Gemma — synthetic test trazabilidad
    pub injection_id: Option<String>,
    pub injection_time_utc: Option<String>,
    pub is_synthetic: bool,
}

// Sidecar JSON parsing (poll_once)
#[derive(Debug, Deserialize)]
struct SidecarState {
    // ... campos existentes ...
    #[serde(default)]
    injection_id: Option<String>,
    #[serde(default)]
    injection_time_utc: Option<String>,
    #[serde(default)]
    is_synthetic: Option<bool>,
}
```

### V4ShadowRecord (`cyclic_dispatch_v4.rs`)

Añadir 3 campos al record JSONL:

```rust
pub struct V4ShadowRecord {
    // ... campos existentes ...
    pub v4_macro_injection_id: Option<String>,
    pub v4_macro_injection_time_utc: Option<String>,
    pub v4_macro_is_synthetic: bool,
}
```

## 5. Test runner (Dallas side)

```python
import requests, time, uuid, json
from pathlib import Path

NEWARK_JSONL = "/home/administrator/poly_sidecar/data/shadow_mirror/cyclic_shadow_v4.jsonl"

def run_iter(iter_num: int, btc_price: float, mode: str = "CRITICAL"):
    iid = f"test1-{int(time.time())}-iter{iter_num}"
    payload = {
        "injection_id": iid,
        "btc_price_usd": btc_price,
        "mode": mode,
        "mode_reason": "synthetic_kill_switch_test",
        "ttl_seconds": 30,
    }
    # POST inject
    r = requests.post(
        "http://127.0.0.1:8090/admin/test/inject_macro_state",
        json=payload, timeout=3,
    )
    r.raise_for_status()
    inject_response = r.json()
    injection_time_iso = inject_response["injection_time_utc"]

    # Poll JSONL Newark (mirrored Dallas via rsync 60s — too slow, use SSH tail)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        # SSH tail último N records, parse
        out = ssh_tail_last_n(NEWARK_JSONL, 5)
        for rec in out:
            if rec.get("v4_macro_injection_id") == iid:
                # Found — calculate latency from sidecar inject time
                t_jsonl = parse_iso(rec["timestamp"])
                t_inject = parse_iso(injection_time_iso)
                latency_ms = int((t_jsonl - t_inject) * 1000)
                return {"ok": True, "latency_ms": latency_ms, "iid": iid}
        time.sleep(0.05)  # 50ms poll
    return {"ok": False, "reason": "timeout 5s", "iid": iid}

# Run 50 iterations, alternate prices
results = []
for i in range(50):
    btc = 78000 if i % 2 == 0 else 84500
    mode = "CRITICAL" if abs(btc - 81500) > 2000 else "CAUTELA"
    res = run_iter(i, btc, mode)
    results.append(res)
    time.sleep(2)  # space out, override expira en 30s pero no queremos overlap

# Stats p50/p95/p99
latencies = sorted([r["latency_ms"] for r in results if r["ok"]])
n = len(latencies)
report = {
    "n_total": 50,
    "n_ok": n,
    "n_timeouts": 50 - n,
    "p50_ms": latencies[n // 2] if n else None,
    "p95_ms": latencies[int(n * 0.95)] if n else None,
    "p99_ms": latencies[int(n * 0.99)] if n else None,
    "max_ms": latencies[-1] if n else None,
    "criterion_p50_lt_800ms": (latencies[n // 2] if n else 99999) < 800,
    "criterion_p99_lt_1200ms": (latencies[int(n * 0.99)] if n else 99999) < 1200,
}
```

### Validación de Warmup pre-test (condición #4)

```python
def assert_warmup_complete():
    r = requests.get("http://127.0.0.1:8090/api/state", timeout=3).json()
    assert r.get("btc_price_usd") is not None, "warmup not complete: btc_price=null"
    assert r.get("is_synthetic", False) == False, "previous override still active"
    print(f"warmup OK: btc=${r['btc_price_usd']:.2f}, no synthetic")
```

## 6. Auto-cleanup mechanism (condición #3)

Dos paths que limpian el override:

**Path A — TTL expira en /api/state read**
- En cada `/api/state` call, `_maybe_apply_synthetic_override` chequea `now > expires_at`
- Si expirado, NO aplica override (devuelve state real)
- El override permanece como objeto en memoria pero no surte efecto

**Path B — Polling tick real fresh**
- Cuando el polling loop completa un tick exitoso (datos reales fresh), clear `_synthetic_override = None`
- Real data wins sobre cualquier override activo

Garantía: nunca habrá un estado donde el override surta efecto más allá de `min(TTL, next_poll_tick)`.

## 7. Files affected

```
poly_sidecar/
├── sidecar.py        — añade _synthetic_override + helpers + auto-cleanup
├── health_api.py     — añade endpoint POST /admin/test/inject_macro_state
└── tests/
    └── test_synthetic_inject.py  — unit tests payload validation + lock atomicity

V4-Alpha (Newark)/
├── src/macro_state.rs       — añade injection_id/time/is_synthetic fields
└── src/cyclic_dispatch_v4.rs — añade v4_macro_injection_* en V4ShadowRecord

Dallas tests/
└── synthetic_tests/run_test1.py  — el runner descrito en §5
```

## 8. Plan de validación post-implement

1. Verificar warmup `/api/state.btc_price_usd != null`
2. Smoke 1 inject → verificar JSONL Newark recibe `v4_macro_injection_id` matching
3. Run 50 iterations, alternating BTC prices
4. Compute p50/p95/p99
5. Reportar con MD r126 + raw JSONL evidence

## 9. Pregunta a Gemma antes de implementar

¿Apruebas:
- (a) **Schema del payload** (§2)?
- (b) **Diseño del lock atomicity** (§3) — solo write toma lock, reads no?
- (c) **Auto-cleanup dual path** (§6) TTL + polling-tick-wins?
- (d) **Validación de warmup pre-test** (§5) check pre-run?

Si todo OK → implemento. Si quieres ajustes (ej. lock también en read,
TTL diferente, payload extra fields), dime y aplico antes de tocar código.

---

**Estado**: WAITING_FOR_DESIGN_FIRMA antes de implementar
**Siguiente r-number**: r126 con resultados Test 1 si firmas
