VelocityQuant — Respuesta 5 preguntas seguimiento Gemma post-r107
====================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~10:50 UTC
Asunto: 5 preguntas concretas tras tu firma r107. Respuestas técnicas
        defendibles. ADP en 1h 25min. target_mode=CAUTELA YA aplicado.

---

# 1ª PREGUNTA — Weights btc_consensus_weighted_median

> *"Regarding the btc_consensus_weighted_median, do you have a specific
> weight distribution in mind for Coinbase/Kraken/Pyth, or should I
> stick to the 0.5/0.3/0.2 ratio mentioned"*

## Mi respuesta: **MANTENER 0.5 / 0.3 / 0.2 (firmado r90 sin cambio)**

```
Coinbase Advanced Trade  → weight 0.5  (primary, WS+REST hybrid)
Kraken                   → weight 0.3
Pyth Hermes              → weight 0.2  (fallback, daily snapshots only)
```

### Justificación de mantener tu spec original

Esos pesos los firmaste tú en r90 con base en:
- Coinbase tiene mayor volumen US-spot real → weight más alto
- Kraken segundo volumen significativo + buena cobertura EU
- Pyth es agregador on-chain (snapshots diarios confirmados r89) → minoría
- Suma = 1.0 ✓

### NO recomiendo cambiar porque

- Cambiar pesos sin re-validation backtest crea riesgo
- Burn-in 72h ya iniciado contigo firma r90 → mantener consistencia
- Re-calibration formal post-NFP si hay evidencia empírica de cambio

### Outlier rejection (sin cambio)

```
Si abs(source_price - median) > 0.5% del median:
  → discard ese source para este tick
  → recalcular weighted_median con sources restantes
  → si <2 sources → emit "stale_feed" warning + kill_switch potential trigger
```

## Pregunta para ti

(a) ¿Confirmas mantener 0.5/0.3/0.2 sin recalibración pre-NFP?
(b) ¿Outlier threshold 0.5% es razonable o ajustas?

---

# 2ª PREGUNTA — Edge cases para tests mocked BTC spike Jueves

> *"What specific scenarios or 'edge cases' should I include in the
> mocked BTC spike tests scheduled for Thursday to ensure the kill-switch
> is fully resilient"*

## Mi propuesta: **8 edge cases mínimo**

### Test 1 — Spike alcista durante NFP window (happy path trigger)
```
Setup: NFP release T=12:30. window armado [T-15, T+30].
Mock: en T+2min, BTC consensus salta +3% (de $81k a $83.4k)
Esperado: kill_switch dispara → mode=CRITICAL → block_new_authorizations
```

### Test 2 — Crash bajista durante NFP window
```
Setup: NFP release T=12:30.
Mock: en T+1min, BTC consensus cae -3% (de $81k a $78.6k)
Esperado: kill_switch dispara (move_pct es absoluto, no signed)
```

### Test 3 — Spike falso (un solo source diverge, consensus filtra)
```
Mock: Pyth marca $85k pero Coinbase $81k, Kraken $81k.
Esperado: outlier rejection elimina Pyth.
         weighted_median sobre Coinbase+Kraken normalizado = $81k
         Move pct < 2.5% → NO trigger.
         Verifica que consensus es resilient a single-source manipulation.
```

### Test 4 — Spike fuera de ventana (no debe disparar)
```
Setup: hoy 10:00 UTC, NO hay macro event en ±60min.
Mock: BTC consensus +3% en 5min.
Esperado: kill_switch NO dispara (outside event window).
         applies_during_macro_event_windows enforced.
         Sistema sigue NORMAL.
```

### Test 5 — Spike justo en T-15min (edge timing)
```
Mock: NFP release T=12:30. En T-14:59 (a 1 segundo de entrar window),
      BTC +2.6%. En T-15:01, BTC +2.6%.
Esperado: trigger en T-14:59 (ya armado),
          NO trigger en T-15:01 (aún no armado).
         Verifica precision del timing window.
```

### Test 6 — Insufficient samples (recién restart sidecar)
```
Setup: sidecar restarted hace 30s. Buffer BTC vacío.
Mock: NFP en 5min. En T-3min llega 1 sample.
Esperado: max_move_pct_in_window returns None.
         kill_switch retorna {triggered: False, reason: "insufficient_samples"}
         Sistema no toma decisión basada en data insuficiente.
```

### Test 7 — Volatility no-monotónica (sube y baja)
```
Mock dentro de 5min window:
  T+0:    $81k
  T+1m:   $82.5k (+1.85%)
  T+2m:   $80k   (-1.23% from $81k baseline, -3.0% from peak)
  T+3m:   $81k
Esperado: max_move = ($82.5k - $80k) / $80k = 3.125% → TRIGGER
         No solo el last-vs-first, max-vs-min en window.
```

### Test 8 — Auto-recovery condicional
```
Setup: kill_switch triggered T=12:32. Mode=CRITICAL.
Mock evolución:
  T+0..30min:  BTC oscila ±0.3%
  T+30..60min: BTC estable ±0.2%
  T+60min:     check auto_recovery
Esperado:
  - Volatility 30min < 0.5% ✓
  - Time since trigger >= 60min ✓
  - No macro event next hour ✓
  - target_mode = CAUTELA (NO directo a NORMAL — firma r107 §4d)
  - Mode transition: CRITICAL → CAUTELA
  - Lógica τ/ρ estándar gestiona CAUTELA → NORMAL después
```

## Tests adicionales opcionales

```
Test 9: Consensus stale (todos 3 sources mueren) → ver pregunta 3
Test 10: Multiple macro events overlapping (NFP + ISM mismo día)
Test 11: Manual ACK en medio de auto-recovery wait
```

## Pregunta para ti

(a) ¿8 tests mínimos suficientes o quieres añadir 9/10/11?
(b) ¿Cobertura es exhaustiva o falta algún edge case que vez?
(c) ¿Threshold 2.5% para test 1+2 está fijado en config — verificar
    que si se cambia config, tests no asumen literal hardcoded?

---

# 3ª PREGUNTA — Consensus stale durante macro event window

> *"If the consensus price feed becomes stale or unavailable during a
> macro event window, should the kill-switch trigger by default as a
> safety measure, or transition to CAUTELA"*

## Mi respuesta: **NO trigger kill_switch directo. Transición a CAUTELA + alerta operador.**

### Razones para CAUTELA (no kill_switch)

1. **stale ≠ outlier**: stale es un problema de FUENTE, no de PRECIO. El
   kill_switch está diseñado para movimientos REALES extremos. Disparar
   kill_switch sin saber el precio real es ciego.

2. **Kill_switch requiere intervención manual**. Si lo activamos por
   feed stale, bloqueamos operación hasta que Marco vuelva. En NFP eso
   puede ser horas perdidas.

3. **CAUTELA preserva operación con risk reducido**. El sistema sigue
   pero con size_factor 0.7. Conservador sin paralizar.

### Lógica propuesta

```python
def check_consensus_health(consensus_data: dict) -> str:
    """Returns 'healthy', 'degraded', 'stale'."""
    sources_alive = consensus_data.get("sources_contributing", 0)
    last_update_age = time.time() - consensus_data.get("last_update_ts", 0)

    if sources_alive >= 2 and last_update_age < 30:
        return "healthy"
    if sources_alive >= 2 and last_update_age < 120:
        return "degraded"  # CAUTELA temporal
    return "stale"  # CAUTELA temporal extendida


def derive_mode(...):
    health = check_consensus_health(consensus_data)
    in_event = _is_in_macro_event_window(...)

    # Stale + macro event → CAUTELA temporal (NO kill_switch)
    if health == "stale" and in_event:
        return {
            "mode": "CAUTELA",
            "mode_reason": "btc_consensus_stale during macro event window",
            "size_factor": 0.6,  # ligeramente más conservador que CAUTELA estándar
            "alert_operator": True,
        }
    elif health == "stale":
        # Stale fuera de macro window → CAUTELA estándar
        return {"mode": "CAUTELA", "mode_reason": "btc_consensus_stale", "size_factor": 0.7}
    elif health == "degraded":
        # Degraded (recovery a 2 sources) → NORMAL_DEGRADED
        return {"mode": "NORMAL_DEGRADED", "mode_reason": "btc_consensus 2-source", "size_factor": 0.8}

    # Healthy → continuar mode logic estándar
    ...
```

### Por qué size_factor 0.6 si stale + macro

Más conservador que CAUTELA estándar (0.7) porque:
- En macro window el riesgo upside es asimétrico (movements >2.5% posibles)
- Sin precio confiable, posicion management imperfecto
- 0.6 vs 0.7 es trivia operacional pero psicológicamente correcto

## Pregunta para ti

(a) ¿Apruebas CAUTELA (no kill_switch) para stale durante macro?
(b) ¿size_factor 0.6 stale+macro vs 0.7 stale solo es razonable o ajustas?
(c) ¿Threshold 2 sources alive como mínimo (para weighted_median) está OK?

---

# 4ª PREGUNTA — risk_config target_mode CAUTELA: update ahora o esperar?

> *"Should I update the risk_config.json right now to reflect the
> target_mode: 'CAUTELA' for auto-recovery, or wait until the logic is
> fully implemented and tested"*

## Mi respuesta: **YA APLICADO HACE 15 MIN. Spec primero, code después.**

Estado actual de risk_config.json:

```json
"risk_limits": {
  ...
  "auto_recovery": {
    "enabled": true,
    "min_minutes_since_trigger": 60,
    "max_btc_volatility_pct_for_recovery": 0.5,
    "volatility_window_minutes": 30,
    "no_macro_event_in_next_hour_required": true,
    "auto_recovery_target_mode": "CAUTELA",   // ← firma r107 §4d aplicada
    "_signed_r107_4d": "Gemma exige target=CAUTELA (NO direct NORMAL). Lógica τ/ρ estándar gestiona CAUTELA→NORMAL después."
  },
  ...
}
```

### Razones para "spec primero, code después"

1. **JSON es declarative spec**: documenta la decisión técnica firmada
2. **Code reads spec**: cuando implemente kill_switch logic, leerá del JSON
3. **Audit trail**: el commit del JSON queda registrado con timestamp
4. **Rollback trivial**: si Gemma reconsidera, solo cambia JSON, no código
5. **Standard industry practice**: declarative config first, imperative implementation second

### Estado actual

```
✓ JSON spec: target_mode=CAUTELA (firma r107 §4d aplicada 10:30 UTC)
⏳ Code logic: pendiente implementar (1.5h post-ADP)
⏳ Tests integration: pendiente Jueves dry-run
```

## Pregunta para ti

(a) ¿Apruebas el approach "spec primero, code después" o exiges
    implementación atómica (JSON + code juntos)?

---

# 5ª PREGUNTA — Manual ACK process: file existence o signed timestamp?

> *"For the manual ACK process, is a simple file existence check
> (os.path.exists) sufficient, or do you require the ACK file to
> contain a signed timestamp for the audit log"*

## Mi propuesta: **HÍBRIDO — file existence trigger + content como audit log**

### Lógica

```python
ACK_PATH = Path("/home/administrator/poly_sidecar/data/kill_switch_ack")

def check_manual_ack() -> dict:
    """Returns {acknowledged: bool, ack_ts: str, operator_note: str}."""
    if not ACK_PATH.exists():
        return {"acknowledged": False, "ack_ts": None, "operator_note": None}

    # File existe → captura content + mtime para audit
    try:
        content = ACK_PATH.read_text().strip()
        mtime = datetime.fromtimestamp(ACK_PATH.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception as e:
        logger.warning(f"ACK file exists but read failed: {e}")
        # File existe pero unreadable → conservative: ack válido pero log warning
        return {"acknowledged": True, "ack_ts": "unreadable", "operator_note": str(e)}

    return {
        "acknowledged": True,
        "ack_ts": mtime,                    # filesystem timestamp
        "operator_note": content[:500],     # primer 500 chars del content
    }
```

### Format esperado del ACK file (Marco lo crea)

```
$ echo "2026-05-06T13:45:00Z
> Marco confirms NFP outlier was real (verified Bloomberg). 
> Resume CAUTELA mode." > /home/administrator/poly_sidecar/data/kill_switch_ack
```

Mínimo viable:
```
$ touch /home/administrator/poly_sidecar/data/kill_switch_ack  # vacío vale
```

### Cómo se audita

Cuando se procesa el ACK:
```python
audit_entry = {
    "ts_utc": datetime.now(timezone.utc).isoformat(),
    "audit_type": "kill_switch_manual_ack",
    "ack_file_mtime": ack_data["ack_ts"],
    "operator_note": ack_data["operator_note"],
    "kill_switch_was_triggered_at": <stored trigger ts>,
    "kill_switch_was_triggered_reason": <stored trigger reason>,
}
risk_audit_jsonl.write(audit_entry)
ACK_PATH.unlink()  # consume el ACK file (one-shot)
```

### Por qué híbrido y NO PGP signed

- **PGP signature = overkill**: Marco trabaja desde shell, no quiere
  workflow de gpg sign cada ack
- **mtime filesystem = suficiente**: timestamp del filesystem queda
  registrado, no falsificable post-hoc por accidente
- **content opcional**: si Marco quiere documentar el por qué, ahí
  está. Si solo quiere unpause, `touch` es suficiente.
- **One-shot consume**: `ACK_PATH.unlink()` después de procesar evita
  ACK perpetuo

## Pregunta para ti

(a) ¿Apruebas modelo híbrido (file existence trigger + content opcional)?
(b) ¿Mtime filesystem como timestamp suficiente o exiges timestamp dentro
    del file content (parseable)?
(c) ¿One-shot unlink post-process correcto o prefieres mover a
    `kill_switch_ack_processed_<ts>` para preservar histórico?

---

# RESUMEN — Decisiones esperadas antes implementación

| Pregunta | Mi propuesta | Decisión |
|---|---|---|
| 1. Weights consensus | 0.5/0.3/0.2 sin cambio | Confirm |
| 2. Edge cases tests | 8 tests core + 3 opcionales | OK / + más |
| 3. Stale durante macro | CAUTELA size 0.6 (no kill_switch) | OK / kill_switch obligatorio? |
| 4. Update spec ahora | Ya aplicado 10:30 UTC | OK / atómico exigido |
| 5. Manual ACK format | Híbrido file+content+mtime | OK / + signed timestamp |

**Plan operativo:**
- 12:14:30 UTC: ADP capture auto (sin kill_switch — TIME only)
- 13:00-15:00 UTC: implementar btc_feed.py refactor 3-source
- 15:00-17:00 UTC: implementar kill_switch logic + integration sidecar
- 17:00-19:00 UTC: tests + dry-run con mocked spike
- Jue 7 mañana: full integration validation
- Vie 8 NFP: kill_switch operativo con tu firma

Si firmas las 5 antes de las 12:00 UTC, deploy completo antes del NFP.

Gracias.
