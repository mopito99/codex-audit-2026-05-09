VelocityQuant — Respuesta 4 preguntas seguimiento Gemma post-r93 DEPLOY
==========================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~10:35 UTC
Asunto: 4 preguntas concretas tras tu DEPLOY APPROVED r93. Respuestas
        técnicas defendibles + código exacto para pregunta 2. ADP en 1h 40min.

---

# 1ª PREGUNTA — ¿Podemos proceder ya al deploy?

> *"He añadido 'kill_switch_pause_btc_move_pct: 2.5' al JSON y el log
> CRITICAL al fallback. ¿Podemos proceder ya al deploy?"*

## Respuesta: **SÍ. Deploy ya aplicado.**

Estado verificado a las 10:30 UTC:

```
✓ risk_config.json firmado r93:
  - rotation_days: 90
  - include_runtime_version: true
  - risk_limits.kill_switch_pause_btc_move_pct: 2.5
  - risk_limits.window_minutes: 5

✓ sidecar.py:
  - load_risk_config() loggea CRITICAL en fallback
  - mode logic L1-L4 lee 100% de risk_config.json
  - NORMAL_DEGRADED dynamic via risk_config

✓ cpi_audit_format.py:
  - runtime_version="V3.5-SHADOW-r93" en MacroLayerHealth + CPIAuditReport
  - Demo run OK + JSON output con runtime_version visible

✓ sidecar restarted con r93 final → mode NORMAL, BTC $81,721, 0 errors
✓ ADP timer programmed: 12:14:30 UTC (vq-adp-capture.timer)
✓ Burn-in 72h iniciado: 2026-05-06T08:22:05Z
```

**ADP capture lanzará automáticamente.** Solo queda **lógica de verificación
del kill_switch_btc_move** (pregunta 2 abajo) — esa la implemento HOY post-ADP
para tener lista para NFP Vie 8.

---

# 2ª PREGUNTA — ¿Dónde implementar verificación kill_switch_btc_move en sidecar?

> *"¿En qué parte exacta de la lógica de sidecar.py debería implementarse
> la verificación del kill_switch_pause_btc_move_pct?"*

## Mi propuesta: **early-check en mode derivation, ANTES de cualquier otro trigger**

### Localización en el flow

```python
# ── Mode derivation (firmado Gemma r92/r93) ─────────────────────────
# ORDEN DE EVALUACIÓN:
# 1. ⚡ kill_switch BTC move outlier (r93) — HARD OVERRIDE preventivo
# 2. ρ < -0.7 divergencia narrativa → DEFENSIVO
# 3. SF > 1σ Investing reaction → CAUTELA
# 4. τ_final > 0.7 → CAUTELA
# 5. Stale L2/L3 → CAUTELA temporal
# 6. Stale L1 → NORMAL_DEGRADED dynamic
# 7. else → NORMAL
```

### Implementación concreta

```python
# Estado mutable: buffer rolling de BTC prices
class _BTCBuffer:
    """Buffer rolling de BTC prices con timestamps para ventana N min."""
    def __init__(self):
        self.samples: list[tuple[float, float]] = []  # [(ts, price), ...]

    def push(self, ts: float, price: float, retain_seconds: float = 600):
        self.samples.append((ts, price))
        cutoff = ts - retain_seconds
        self.samples = [(t, p) for t, p in self.samples if t > cutoff]

    def max_move_pct_in_window(self, window_seconds: float) -> float | None:
        if len(self.samples) < 2:
            return None
        now = self.samples[-1][0]
        cutoff = now - window_seconds
        in_window = [(t, p) for t, p in self.samples if t >= cutoff]
        if len(in_window) < 2:
            return None
        prices = [p for _, p in in_window]
        return ((max(prices) - min(prices)) / min(prices)) * 100.0


_btc_buffer = _BTCBuffer()


def check_btc_kill_switch(btc_price: float, risk_config: dict, fmp_upcoming: list) -> dict:
    """Verifica kill_switch_pause_btc_move_pct (firmado Gemma r93).

    Returns:
        {triggered: bool, reason: str, btc_move_pct: float, in_event_window: bool}
    """
    import time
    rl = risk_config.get("risk_limits", {})
    threshold_pct = rl.get("kill_switch_pause_btc_move_pct", 2.5)
    window_min = rl.get("window_minutes", 5)
    applies_to = rl.get("applies_during_macro_event_windows", ["NFP", "CPI", "FOMC", "PCE"])

    # Push current price al buffer
    _btc_buffer.push(time.time(), btc_price)

    # Calcular max move en window
    move_pct = _btc_buffer.max_move_pct_in_window(window_min * 60)
    if move_pct is None:
        return {"triggered": False, "reason": "insufficient_samples", "btc_move_pct": None, "in_event_window": False}

    # Solo se activa durante ventanas de macro event tier-1
    in_event_window = _is_in_macro_event_window(fmp_upcoming, applies_to, pre_min=15, post_min=30)

    if not in_event_window:
        return {"triggered": False, "reason": "outside_event_window", "btc_move_pct": move_pct, "in_event_window": False}

    if move_pct > threshold_pct:
        return {
            "triggered": True,
            "reason": f"BTC move {move_pct:.2f}% > {threshold_pct}% in {window_min}min during macro event window",
            "btc_move_pct": move_pct,
            "in_event_window": True,
        }

    return {"triggered": False, "reason": "within_threshold", "btc_move_pct": move_pct, "in_event_window": True}


def _is_in_macro_event_window(fmp_upcoming: list, applies_to: list, pre_min: int = 15, post_min: int = 30) -> bool:
    """Check si NOW está en ventana [event_ts - pre_min, event_ts + post_min]
    para algún evento de los `applies_to` categories."""
    import time
    from datetime import datetime
    now = time.time()
    for ev in fmp_upcoming:
        cat = ev.get("category", "")
        if cat not in applies_to:
            continue
        date_str = ev.get("date", "")
        try:
            ev_dt = datetime.fromisoformat(date_str.replace(" ", "T"))
            ev_ts = ev_dt.timestamp()
            if (ev_ts - pre_min * 60) <= now <= (ev_ts + post_min * 60):
                return True
        except Exception:
            continue
    return False


# ── En el mode derivation (sidecar polling loop) ────────────────────
# Inserción al INICIO de mode logic, ANTES de divergence/SF/tau checks:
def derive_mode_with_kill_switch(client, tau_final, divergence, react_event,
                                   rho_global, rho_threshold, btc_price,
                                   fmp_upcoming):
    risk_config = load_risk_config()

    # NEW r93 — kill switch BTC outlier (HARD OVERRIDE)
    kill_check = check_btc_kill_switch(btc_price, risk_config, fmp_upcoming)
    if kill_check["triggered"]:
        return {
            "mode": "CRITICAL",
            "mode_reason": kill_check["reason"],
            "size_factor": 0.0,
            "block_new_authorizations": True,
            "kill_switch_btc_triggered": True,
            "kill_switch_btc_move_pct": kill_check["btc_move_pct"],
        }

    # ... resto de la lógica existente (divergencia, SF, τ, stale, etc.)
```

### Ventana de "macro event window" propuesta

`pre_min=15, post_min=30` (firmado por mí, pendiente tu confirmación):

```
T-15min ←── kill switch ARMADO ──→ T (release) ──→ T+30min ──→ DESARMADO
```

## Pregunta para ti

(a) ¿Apruebas pre_min=15 / post_min=30 como ventana del kill switch?
(b) ¿La logic propuesta (early HARD OVERRIDE antes de cualquier otro check) es correcta?
(c) ¿BTC price para el buffer debe ser `btc_consensus_weighted_median` (Coinbase+Kraken+Pyth) o el spot Pyth solo?

---

# 3ª PREGUNTA — Metadata específica para CRITICAL log fallback

> *"Sobre el log CRITICAL del fallback, ¿necesitas que incluya algún
> metadato específico (ej. checksum del archivo fallido o timestamp)
> para la auditoría?"*

## Mi propuesta: **YES — log estructurado con 5 campos**

```python
def load_risk_config() -> dict:
    try:
        return json.loads(RISK_CONFIG_FILE.read_text())
    except Exception as e:
        # firma Gemma r93 §2: log CRITICAL estructurado obligatorio
        import hashlib, traceback
        try:
            content = RISK_CONFIG_FILE.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()[:16]
            file_size = len(content)
        except Exception:
            sha256 = "FILE_NOT_READABLE"
            file_size = -1

        logger.critical(
            "WARNING: risk_config.json corrupted/missing. "
            "Operating on r92 Signed Defaults.",
            extra={
                "audit_event": "risk_config_fallback_triggered",
                "file_path": str(RISK_CONFIG_FILE),
                "file_sha256_first16": sha256,
                "file_size_bytes": file_size,
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {<defaults...>}
```

### 5 campos justificados

1. **`file_path`** — path absoluto (operador sabe qué buscar)
2. **`file_sha256_first16`** — primeros 16 chars del hash (detectar si fue editado o si está corrupto vs missing)
3. **`file_size_bytes`** — confirmar si está vacío vs corrupted (size=0 vs size>0 con JSON inválido)
4. **`exception_type` + `exception_message`** — tipo (FileNotFoundError vs JSONDecodeError vs PermissionError) + detalle
5. **`timestamp_utc`** — para correlate con otros logs / sidecar restarts

### ¿Por qué `extra={}` y no string format?

- Permite parsing automático (jq, ELK, Splunk si lo añadimos)
- Stringification del exception preserva traceback completo para debug
- Los campos quedan separados del mensaje human-readable

## Pregunta para ti

(a) ¿Apruebas los 5 campos como estándar del CRITICAL log?
(b) ¿Falta `traceback` completo (línea por línea)? Mi posición: NO, el
    type+message es suficiente para audit; traceback va a stderr
    standard y es overkill para el JSONL de auditoría.
(c) ¿Aceptas SHA256 truncado a 16 chars (8 bytes) o exiges los 64 completos?

---

# 4ª PREGUNTA — Kill switch BTC: auto-recovery o manual?

> *"Si el kill_switch se activa por el movimiento de BTC, ¿debería el
> sistema intentar un autorecovery o requerir intervención manual para
> reanudar?"*

## Mi propuesta: **HÍBRIDO — manual default, auto-recovery condicional**

### Lógica

```
ESTADO inicial: kill_switch ARMADO (firmado risk_limits.block_new_authorizations_until_manual=true)

CASE A — Marco interviene manualmente (ack):
  - Marco verifica el evento (e.g. NFP outlier real, no falla feed)
  - Marco ejecuta: touch /home/administrator/poly_sidecar/data/kill_switch_ack
  - Sidecar detecta el ACK file → reanuda mode NORMAL

CASE B — Auto-recovery condicional (firmado en risk_config):
  - Si BTC volatility se estabiliza (max move < 0.5% en últimos 30min) Y
  - Si han pasado al menos 60min desde el trigger Y
  - Si NO hay otro macro event tier-1 en la próxima hora
  → sidecar transitions automáticamente kill_switch → CAUTELA → NORMAL

  Esto evita lock perpetuo si Marco no está disponible y el evento fue puntual.
```

### Implementación en risk_config.json

Añadir bajo `risk_limits`:

```json
"risk_limits": {
  "kill_switch_pause_btc_move_pct": 2.5,
  "window_minutes": 5,
  "force_mode_on_trigger": "CRITICAL",
  "block_new_authorizations_until_manual": true,

  "auto_recovery": {
    "enabled": true,
    "min_minutes_since_trigger": 60,
    "max_btc_volatility_pct_for_recovery": 0.5,
    "volatility_window_minutes": 30,
    "no_macro_event_in_next_hour_required": true,
    "auto_recovery_target_mode": "CAUTELA"
  },

  "manual_ack_path": "/home/administrator/poly_sidecar/data/kill_switch_ack",
  "manual_ack_priority_over_auto": true
}
```

### Por qué híbrido (no solo manual o solo auto)

| Solo manual | Solo auto | Híbrido (propuesto) |
|---|---|---|
| Lock perpetuo si Marco offline | Auto-resume puede masquerar problema real | Marco priority + safety net |
| Operador es el "circuit breaker breaker" | Sin operator dependency | Operator + system check |
| Default actual r93 | No firmado por ti | Combina ambos |

## Pregunta para ti

(a) ¿Apruebas modelo HÍBRIDO con auto-recovery condicional?
(b) ¿O prefieres SOLO MANUAL estricto (más conservador)?
(c) Si HÍBRIDO: ¿`min_minutes_since_trigger=60` y `max_btc_volatility=0.5%/30min` son razonables?
(d) Auto-recovery `target_mode = "CAUTELA"` o ir directo a `NORMAL`?

---

# RESUMEN — Lo que esperaría firmar antes de NFP Vie 8 (50h)

| Pregunta | Mi propuesta | Decisión esperada |
|---|---|---|
| 1. Deploy ready? | SÍ ya aplicado | confirmación → ✓ |
| 2. Where in sidecar.py | Early HARD OVERRIDE pre todo | OK / ajuste position |
| 3. CRITICAL log metadata | 5 campos estructurados | OK / + traceback? |
| 4. Auto-recovery? | Híbrido manual+auto condicional | OK / solo manual? |

**Tiempo estimado para implementar logic kill_switch:** 1.5h.

**Plan operativo:**
- ADP capture 12:15 UTC ✓ ya programmed
- Post-ADP: implementar kill_switch logic (HOY antes de las 18:00 UTC)
- Mañana Jue 7: tests integración + dry run con mocked BTC spike
- Vie 8 NFP: kill_switch operativo

Si firmas las 4 preguntas hoy, deploy completo del kill_switch listo
ANTES del NFP del Vie 8.

Gracias.
