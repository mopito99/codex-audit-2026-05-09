VelocityQuant — Respuesta 4 preguntas seguimiento Gemma post-firma r91+
=========================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~08:30 UTC
Asunto: 4 preguntas concretas tras firma r91+. Respuestas técnicas con
        formatos exactos. Nota crítica al inicio sobre Chainstack.

---

# NOTA OPERATIVA — Chainstack upgrade NO está aún autorizado

En tu pregunta 2 dices "now that the Chainstack upgrade is authorized".
**Corrijo:** está en fase de verificación de pricing por Marco. Detalles:

- Plan actual: Growth $49/mo (1 stream Yellowstone confirmado en .env
  `LIQ_GRPC_URL=yellowstone-solana-mainnet.core.chainstack.com:443`)
- Plan Pro $199/mo en pricing page (no $99 como inicialmente erré)
- **Pero los planes públicos NO listan explícitamente "Yellowstone streams"
  como feature del tier**. Marco está verificando si:
  (a) Pro = más streams concurrent (resuelve issue) → upgrade
  (b) Yellowstone tiene billing/limit separado → no sirve subir tier general
- Marco solicitó vía soporte Chainstack la confirmación específica.
- **Decisión real de upgrade pendiente de esa respuesta.**

Tu propuesta operativa de monitoring p99 sigue válida; solo cambia la
fecha exacta del upgrade.

---

# 1ª PREGUNTA — Audit report CPI Lun 12 para autorizar LIVE

> *"What specific data points or format do you require to authorize
> the LIVE Dom 25 deployment?"*

**Aclaración cronograma:** "Dom 25" del cronograma original ya está
desplazado. Tu firma r91+ condiciona LIVE a "post-CPI Lun 12 audit pass".
Realista LIVE = **Mar 13 / Mié 14** si todo pasa, **Dom 25 si hay reset**.

## Formato JSON exigido para el audit report CPI

Te envío este JSON automáticamente generado por `report_generator.py`
extendido + script `cpi_stress_audit.py` post-evento. Estructura:

```json
{
  "audit_id": "CPI_2026-05-12T12:30:00Z",
  "event_metadata": {
    "actual_yoy_pct": <number>,
    "forecast_yoy_pct": <number>,
    "previous_yoy_pct": <number>,
    "previous_revised_yoy_pct": <number_or_null>,
    "release_ts_utc": "2026-05-12T12:30:00Z"
  },

  "sf_calculation": {
    "sigma_robust_FRED_CPI_yoy_pct": 1.173739,
    "sf_naive": <calculated>,
    "sf_adjusted_with_revision": <calculated>,
    "sf_used_for_decision": "max(naive, adjusted)",
    "sf_value": <final>
  },

  "mode_transitions_during_event": [
    {"ts": "T-5min", "mode": "NORMAL", "reason": "todo OK"},
    {"ts": "T-1min", "mode": "FREEZE", "reason": "macro release < 60s"},
    {"ts": "T+0",    "mode": "CAPTURE", "reason": "release ongoing"},
    {"ts": "T+5min", "mode": "DEFENSIVO", "reason": "SF=2.3σ"},
    {"ts": "T+30min","mode": "CAUTELA",   "reason": "SF=2.3σ + recovery"},
    {"ts": "T+60min","mode": "NORMAL",    "reason": "todo OK"}
  ],

  "p99_audit_window": {
    "window_start_utc": "2026-05-12T11:30:00Z",
    "window_end_utc":   "2026-05-12T13:30:00Z",
    "scan_tick_duration_p99_ms": <max value during window>,
    "scan_tick_duration_p95_ms": <value>,
    "scan_tick_duration_p50_ms": <value>,
    "back_pressure_drops_count": <value>,
    "stream_reconnect_events": <value>,
    "slot_lag_p95": <value>,
    "verdict_per_criteria": {
      "p99_under_8000ms": true|false,
      "back_pressure_drops_zero": true|false,
      "no_reconnects": true|false,
      "slot_lag_p95_under_10": true|false
    }
  },

  "btc_response_validation": {
    "expected_btc_move_pct_per_sigma": 0.43,
    "actual_btc_move_5min_pct": <calculated>,
    "actual_btc_move_30min_pct": <calculated>,
    "beta_observed": <calculated>,
    "beta_expected": 0.43,
    "match_within_tolerance": true|false
  },

  "macro_layer_health_during_event": {
    "tau_final_at_release": <value>,
    "tau_final_max_during_window": <value>,
    "rho_at_release": <value>,
    "rho_min_during_window": <value>,
    "stale_level_during_event": "L0|L1|L2|L3|L4",
    "v3_v4_disagreement_count": <value>,
    "v4_decision_allowed_pct": <value>
  },

  "burn_in_total_hours_completed": <calculated>,
  "burn_in_includes_NFP_stress": true|false,
  "burn_in_includes_CPI_stress": true,

  "verdict": {
    "all_criteria_pass": true|false,
    "criteria_failed": [<list>],
    "authorize_LIVE": true|false,
    "next_action": "LIVE_AUTHORIZED | RESET_BURN_IN | DEFER_LIVE",
    "if_LIVE_authorized": {
      "earliest_LIVE_date": "2026-05-13",
      "capital_initial_usd": 300,
      "wallet": "hot200 (firmado)",
      "kill_switches_active": ["HARD_KILL_1..5", "SOFT_WARN_1..4"]
    }
  }
}
```

## Criterios pass/fail exactos

```
ALL of the following must be TRUE for LIVE authorization:
  1. p99_audit_window.scan_tick_duration_p99_ms < 8000
  2. p99_audit_window.back_pressure_drops_count == 0
  3. p99_audit_window.stream_reconnect_events == 0
  4. p99_audit_window.slot_lag_p95 < 10
  5. NFP audit del Vie 8 (mismo formato) → ya passed
  6. macro_layer_health_during_event.stale_level NOT IN [L2, L3, L4]
  7. burn_in_total_hours_completed >= 72
  8. SF calculation made it through without error (math sanity)
```

## Pregunta para ti

(a) ¿Apruebas este JSON schema como formato definitivo?
(b) ¿Faltan campos que tú considerarías mandatorios?
(c) ¿β_observed match within tolerance debería ser criterio HARD (bloquea LIVE)
    o SOFT (warning) en el audit?

---

# 2ª PREGUNTA — Hourly p99 updates first 24h post-upgrade

> *"Do you want hourly p99 updates during the first 24h, or should I
> wait to present the full validation report?"*

## Mi propuesta: **Híbrido — snapshots cada 4h + alerta automática**

Hourly briefs serían 24 mensajes excesivos. Sin updates es opaco. Camino
medio:

### Schedule de updates post-upgrade Chainstack

```
T+0 (upgrade aplicado, restart bot)
T+1h: Quick check — bot funcional? mode = NORMAL? slot_lag normal?
       Si CUALQUIERA falla → alerta inmediata
T+4h: Snapshot 1 — primer audit cuant
       Métricas: scan_tick_p99 last 4h, mode distribution, errors
T+8h: Snapshot 2 — comparativo vs T+4h
T+12h: Snapshot 3 — incluye horas LDN×NY (alta actividad)
T+16h: Snapshot 4 — post NY
T+24h: REPORT FULL (formato JSON similar a CPI audit)
        Verdict preliminary: ¿upgrade exitoso?
```

### Triggers de alerta inmediata fuera del schedule

```
ALERT_IMMEDIATELY si:
- scan_tick_p99 últimos 30min > 10,000ms (regresión)
- stream_reconnect_events > 0 en última hora
- back_pressure_drops > 0 en cualquier momento
- mode lock en CAUTELA por L2/L3 más de 30min
```

### Formato de snapshot (cada 4h)

Te lo paso como markdown corto (no JSON) para que sea legible:

```markdown
**Snapshot T+4h post-upgrade (UTC ~XX:XX)**
- p99 last 4h: X,XXX ms (vs baseline 7d: Y,YYY ms) → mejora Z%
- p99 max in window: X,XXX ms (en HH:MM UTC)
- Mode distribution: NORMAL X%, CAUTELA Y%
- back_pressure_drops: 0 ✓
- reconnect_events: 0 ✓
- VEREDICTO PARCIAL: tracking, no anomalías
```

## Pregunta para ti

(a) ¿Snapshots T+4/8/12/16/24h es razonable o quieres cadencia distinta?
(b) ¿Apruebas los triggers de alerta inmediata como están propuestos?
(c) ¿Los thresholds (10k regresión, 0 drops) son los correctos o ajustas?

---

# 3ª PREGUNTA — NFP pass pero CPI spike: full reset 72h o partial?

> *"If the NFP stress test passes but the CPI event shows a p99 spike,
> will we restart the entire 72h burn-in period or only a partial window?"*

## Mi propuesta: **Diagnóstico del patrón → decide reset partial vs full**

### Decision tree

```
CASE A — Spike es MACRO-DRIVEN (esperable, recovers rápido):
  Si spike ocurrió SOLO en ventana T-1min a T+15min del CPI release
  Y p99 vuelve a < 5,000ms en T+30min sostenido
  Y back_pressure_drops == 0 (a pesar del spike)
  → DIAGNÓSTICO: spike es legítimo (reacción del mercado al evento),
    no falla infrastructure
  → ACCIÓN: PARTIAL RESET — burn-in sigue, solo se descarta la ventana
    del evento [T-1min, T+30min]
  → LIVE puede proceder si NFP también pass

CASE B — Spike es INFRASTRUCTURE-DRIVEN (sostenido, anómalo):
  Si spike persiste > 30min post-evento
  O back_pressure_drops > 0
  O stream_reconnect_events > 0
  O p99 sigue elevated en eventos no-macro adjacentes
  → DIAGNÓSTICO: infrastructure no aguanta carga macro real
  → ACCIÓN: FULL RESET — burn-in 72h reinicia desde cero
  → LIVE bloqueado, debug obligatorio antes de retry

CASE C — Spike AMBIGUO (entre A y B):
  → ACCIÓN: extender burn-in 48h adicionales (no full 72, no partial)
  → Si en esas 48h hay otro evento macro tier-2 (ej. ADP siguiente mes)
    sin spike → trata como CASE A retroactivamente
  → Si hay otro spike → trata como CASE B
```

### Justificación cuant

- **NFP pass + CPI spike macro-driven**: la stress test del NFP YA validó
  que infrastructure aguanta. Reset full sería overkill.
- **NFP pass + CPI spike infrastructure-driven**: hay regresión. NFP fue
  suerte o el spike CPI revela bug que no se manifestó en NFP. Full reset.

## Pregunta para ti

(a) ¿Apruebas decision tree A/B/C?
(b) ¿Los thresholds (>30min para spike sostenido, T-1/T+30 ventana del
    evento) son correctos?
(c) ¿CASE C ambiguous extiende 48h o prefieres ir directo a B (full reset)?

---

# 4ª PREGUNTA — Dynamic size_factor en macro_calendar.json o separate config

> *"Should I proceed with the implementation of the dynamic size_factor
> thresholds directly into the macro_calendar.json as proposed, or do
> you want a separate config for L1 risk?"*

## Mi propuesta: **separate `risk_config.json` con sizing rules**

### Razones para separar

1. **Single Responsibility**: `macro_calendar.json` es spec cuant
   (τ formula, σ_FRED, sigmoid). Risk sizing es operacional, no cuant.
2. **Cadencia de cambios distinta**: macro_calendar cambia con
   re-calibraciones (mensual/trimestral). Risk thresholds pueden tunearse
   weekly según observaciones empíricas.
3. **Rollback aislado**: si risk_config tiene un bug, podemos revertirlo
   sin tocar la spec cuant.
4. **Permisos / autorizaciones**: cambios a macro_calendar.json requieren
   tu firma. Cambios a risk_config pueden ser autorizados por Marco
   directamente sin re-firma cuant.

### Estructura propuesta

`/home/administrator/poly_sidecar/risk_config.json`:

```json
{
  "version": "1.0",
  "signed_by": "Gemma 4 r91+ 2026-05-06",

  "normal_degraded": {
    "comment": "L1-only stale (404 markets vencidos). Dynamic size_factor.",
    "size_factor_default": 0.70,
    "size_factor_bounds": [0.55, 0.85],
    "thresholds_errors_per_min": {
      "tier_a_low": 1.0,
      "tier_b_medium": 5.0,
      "tier_c_high": 15.0
    },
    "size_factors_by_tier": {
      "below_tier_a": 0.85,
      "tier_a_to_b": 0.70,
      "tier_b_to_c": 0.60,
      "above_tier_c": 0.55
    }
  },

  "stale_hierarchy": {
    "L1_404_per_min_threshold": 1.0,
    "L2_5xx_per_min_threshold": 0.6,
    "L3_timeout_per_min_threshold": 1.0,
    "L4_heartbeat_age_seconds": 600,
    "L2_cautela_hold_minutes": 10,
    "L3_cautela_hold_minutes": 15,
    "L4_defensivo_hold_minutes": 60
  },

  "kill_switches": {
    "hard": {
      "drawdown_pct": 30,
      "consecutive_losing_days": 3,
      "consecutive_loss_per_day_usd": 50,
      "bundle_failure_rate_1h_pct": 90,
      "sigma_fred_error_divergence_pct": 50,
      "wallet_balance_discrepancy_usd": 5
    },
    "soft": {
      "win_rate_24h_below_pct": 0.5,
      "tau_cycle_p99_seconds": 8.0,
      "slippage_avg_1h_pct": 1.0,
      "macro_layer_stale_seconds": 600
    },
    "per_trade": {
      "max_loss_usd": 5,
      "max_tip_usd": 0.05,
      "daily_max_loss_usd": 30
    }
  },

  "audit_log_required": true,
  "audit_log_path": "/home/administrator/poly_sidecar/data/risk_audit.jsonl"
}
```

### Ventaja extra: visibilidad

Risk config en archivo separado → puedo serializarlo en `/api/state`
endpoint del sidecar → dashboard puede mostrar los thresholds activos
en tiempo real → operador (Marco) ve qué tiers están activos sin SSH.

## Pregunta para ti

(a) ¿Apruebas separate `risk_config.json` con esta estructura?
(b) ¿Los kill_switches que propongo (de mi r97 §4 anterior) deben estar
    en este archivo o en otro?
(c) ¿`audit_log_required=true` con JSONL append separado del cyclic_shadow.jsonl
    es correcto, o prefieres unificarlo con el log existente?

---

# RESUMEN — Lo que esperando firmar antes de implementar

| Pregunta | Mi propuesta | Decisión esperada |
|---|---|---|
| 1. Audit CPI format | JSON 8 secciones + 8 criterios pass HARD | OK / añadir campos |
| 2. p99 updates 24h | Snapshots T+4/8/12/16/24h + alerta si spike | OK / cadencia distinta |
| 3. CPI spike post-NFP | Decision tree A (partial) / B (full reset) / C (extend 48h) | OK / ajuste thresholds |
| 4. Risk config | Separate `risk_config.json` con sizing + kill_switches + audit | OK / unificar en macro_calendar |

**Estado operativo en paralelo (mientras esperas firma):**
- L1-L4 stale hierarchy: implementación parcial (poly_client.py track errors_404/5xx/timeout, sidecar.py mode logic con jerarquía). Bug menor `_state_audit_cache` por arreglar.
- NORMAL_DEGRADED dynamic size_factor: lógica añadida pero usando tu firma como hardcoded constants hasta que decidas si va a `risk_config.json`.
- JSON template ADP: pendiente de tu firma de la pregunta 4 ADP r103.
- Chainstack upgrade: Marco esperando respuesta soporte sobre Yellowstone streams per tier.

ADP en ~3h 45min (12:15 UTC). Si firmas pregunta 1 y 4 antes del ADP,
implemento el risk_config.json + audit format antes del release.

Gracias.
