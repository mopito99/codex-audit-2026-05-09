VelocityQuant — Review compacto delta r93 (versión COMPACTA)
================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~10:15 UTC
Asunto: r106 anterior era 37 KB, te saturó context. Te paso solo los
        DELTAS de r93 sobre la r92 que ya firmaste. Approval del delta = OK
        para deploy. ADP en 2h.

---

# DELTA 1 — `risk_config.json` (audit_log section)

## ANTES (r92)
```json
"audit_log": {
  "enabled": true,
  "path": "/home/administrator/poly_sidecar/data/risk_audit.jsonl",
  "log_every_sf_calculation": true,
  "log_mode_transitions": true,
  "include_decision_chain_microsecond": true,
  "post_decision_capture_offsets_minutes": [5, 30, 60],
  "retention_policy": "append_only_no_rotation"
}
```

## AHORA (r93 — tu firma)
```json
"audit_log": {
  "enabled": true,
  "path": "/home/administrator/poly_sidecar/data/risk_audit.jsonl",
  "log_every_sf_calculation": true,
  "log_mode_transitions": true,
  "include_decision_chain_microsecond": true,
  "include_runtime_version": true,                    // ← NEW r93 §3
  "post_decision_capture_offsets_minutes": [5, 30, 60],
  "retention_policy": "rotate_every_90_days",         // ← CHANGED r93 §2
  "rotation_days": 90                                 // ← NEW r93 §2
}
```

**¿Apruebas?** YES / NO

---

# DELTA 2 — `cpi_audit_format.py`

## Cambio: añadido campo `runtime_version` en 2 dataclasses

```python
@dataclass
class MacroLayerHealth:
    ...
    runtime_version: str = "V3.5-SHADOW-r93"   # ← NEW r93 §3

@dataclass
class CPIAuditReport:
    ... (sin cambios)
    runtime_version: str = "V3.5-SHADOW-r93"   # ← NEW r93 §3 (al final)
    verdict: dict = ...
```

**Bug fix asociado:** Python dataclass exige que los campos con default
estén al FINAL. Tuve que reordenar `runtime_version` después de los campos
sin default. Tests verde post-fix.

**¿Apruebas?** YES / NO

---

# DELTA 3 — `sidecar.py` mode logic

## Cambio: NORMAL_DEGRADED ahora lee size_factors de risk_config.json

ANTES (r91+, hardcoded):
```python
elif stale_level == "L1":
    if err_404_per_min < 1.0:    size_factor = 0.85   # hardcoded
    elif err_404_per_min < 5.0:  size_factor = 0.70   # hardcoded
    elif err_404_per_min < 15.0: size_factor = 0.60   # hardcoded
    else:                        size_factor = 0.55   # hardcoded
```

AHORA (r92/r93, lee config):
```python
elif stale_level == "L1":
    size_factor = compute_normal_degraded_size_factor(err_404_per_min, risk_config)
    # Función lee thresholds y factors de risk_config.json — NO hardcoded
```

## Función helper (single source of truth = JSON)
```python
def compute_normal_degraded_size_factor(err_404_per_min, risk_config):
    nd = risk_config["normal_degraded"]
    th = nd["thresholds_errors_per_min"]   # de JSON
    sf = nd["size_factors_by_tier"]        # de JSON
    if err_404_per_min < th["tier_a_low"]:    return sf["below_tier_a"]
    if err_404_per_min < th["tier_b_medium"]: return sf["tier_a_to_b"]
    if err_404_per_min < th["tier_c_high"]:   return sf["tier_b_to_c"]
    return sf["above_tier_c"]
```

**¿Apruebas?** YES / NO

---

# CRITERIO HARD r93 §1.c — VERIFICACIÓN

Tu firma exigió: *"sidecar.py NO tenga fallbacks hardcoded que ignoren
risk_config.json"*.

✅ Hot path mode logic: lee 100% de JSON
✅ Thresholds: lee 100% de JSON
✅ size_factors: lee 100% de JSON

⚠️ **Excepción:** `load_risk_config()` tiene fallback hardcoded SOLO si
el archivo JSON no existe o tiene syntax error. Mi defensa:

- Operación normal: JSON es fuente única ✓
- Operación degradada (file missing): fallback usa los mismos valores
  que tú firmaste en r92 (defaults idénticos al JSON)
- Sin fallback: sidecar crashea → pérdida total observability

**¿Aceptas el fallback como degraded mode safety o exiges crash hard?**

---

# TESTS VERDE

```
✓ risk_config.json parse OK
✓ cpi_audit_format.py compile OK
✓ Demo: audit_ADP_*.json escrito con runtime_version="V3.5-SHADOW-r93"
✓ Verdict logic: ya identifica criteria_failed correctamente
```

---

# 3 PREGUNTAS PARA TI (respuesta YES/NO + comentario)

1. **Apruebas los 3 deltas r93?** YES / NO
2. **Aceptas fallback en load_risk_config() o exiges crash hard?** ACCEPT_FALLBACK / CRASH_HARD
3. **Algún campo adicional en risk_config que añadirías antes NFP Vie 8?**
   (e.g. capital_max_at_risk_per_event, kill_switch_pause_btc_move_pct, etc.)

Si los 3 = YES + ACCEPT_FALLBACK + sin campos adicionales → deploy
inmediato + ADP capture lista.

ADP en 2h. Gracias.
