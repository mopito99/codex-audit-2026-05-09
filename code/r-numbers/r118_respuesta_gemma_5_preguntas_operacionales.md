# r118 · Respuesta Gemma 4 — 5 preguntas operacionales pre-implementación

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:00 UTC
**Contexto**: Respuesta a las 5 preguntas seguimiento tras r117.

---

## Q1 — Loop Symmetric Depeg con `depeg_reason` acumulador

### Implementación propuesta (`cyclic_dispatch.rs`)

**Antes** (single-feed, sobrescribe):
```rust
let depeg_reason = if depeg_check(pyth_intermediate) {
    Some(format!("{} depegged", token_intermediate))
} else { None };
```

**Después** (multi-leg, acumula):
```rust
let mut depeg_reasons: Vec<String> = Vec::new();
let mut any_depeg = false;

for (idx, leg) in cycle.legs.iter().enumerate() {
    // Resolver feed para esta leg (con fallback defensivo)
    let feed = pyth_cache.get(&leg.token_mint);
    match feed {
        Some(feed_data) => {
            let depeg_bps = compute_depeg_bps(feed_data, leg.expected_price);
            if depeg_bps.abs() > cfg.depeg_threshold_bps {
                any_depeg = true;
                depeg_reasons.push(format!(
                    "leg{}={} depeg={}bps (price={:.4} vs expected={:.4})",
                    idx, leg.token_symbol, depeg_bps,
                    feed_data.price, leg.expected_price
                ));
            }
        }
        None => {
            // Defensive: missing feed = block (Q2 t4 spec)
            any_depeg = true;
            depeg_reasons.push(format!(
                "leg{}={} missing_feed",
                idx, leg.token_symbol
            ));
        }
    }
}

let depeg_blocked = any_depeg;
let depeg_reason = if any_depeg {
    Some(depeg_reasons.join(" | "))   // "leg1=ETH depeg=5023bps | leg2=USDT missing_feed"
} else { None };
```

### Garantías

1. **Acumula todas las legs failing** en `depeg_reasons: Vec<String>` (no sobrescribe).
2. **`join(" | ")`** preserva ordering (leg index) y separador legible para grep.
3. **Missing feed = block** (cubre t4: defensive default).
4. **Threshold leído de `cfg.depeg_threshold_bps`** (cubre t5: configurable, no hardcoded).
5. Compatible con t6 (multiple legs simultáneamente reportadas).

### JSONL output esperado tras fix

```json
{
  "depeg_blocked": true,
  "depeg_reason": "leg1=SOL depeg=4400bps (price=50.00 vs expected=89.50) | leg2=ETH depeg=5012bps (price=1500.00 vs expected=3000.00)",
  ...
}
```

Esto permite las jq queries del audit dashboard agregar por substring (`leg1`, `leg2`, etc.) sin parser custom.

---

## Q2 — Inyección de fake BTC price spikes sin afectar producción

### Solución: sidecar **test_mode flag** + endpoint dedicado

#### Diseño (`sidecar.py` + `health_api.py`)

Agregar variable de entorno `LIQ_SIDECAR_TEST_MODE=1` (default = 0 = producción).

**`sidecar.py`**:
```python
TEST_MODE = os.environ.get("LIQ_SIDECAR_TEST_MODE") == "1"
_test_btc_override: dict[str, Any] = {"enabled": False, "price": None, "expires_at": 0}

def get_btc_price_for_kill_switch() -> float:
    if TEST_MODE and _test_btc_override["enabled"]:
        if time.time() < _test_btc_override["expires_at"]:
            return _test_btc_override["price"]
        else:
            _test_btc_override["enabled"] = False  # auto-expire
    # path normal — consensus 3-source
    return btc_consensus_weighted_median()
```

**`health_api.py`** (nuevo endpoint, **solo bind a localhost**):
```python
@app.post("/admin/test/btc_inject")
def admin_test_btc_inject(price: float, duration_s: int = 60):
    if not pnl.TEST_MODE:
        raise HTTPException(403, "test mode disabled")
    pnl._test_btc_override = {
        "enabled": True,
        "price": price,
        "expires_at": time.time() + duration_s,
    }
    return {"injected": price, "expires_in_s": duration_s}
```

#### Aislamiento de producción

1. **`LIQ_SIDECAR_TEST_MODE=1`** se setea **solo durante el stress test**, jamás
   en `vq-poly-sidecar.service` `EnvironmentFile=` permanente.
2. **Forma operativa**:
   ```bash
   sudo systemctl set-environment LIQ_SIDECAR_TEST_MODE=1
   sudo systemctl restart vq-poly-sidecar.service
   curl -X POST 'http://127.0.0.1:8090/admin/test/btc_inject?price=78000&duration_s=120'
   # ... ejecutar stress test, observar CB / kill_switch ...
   sudo systemctl unset-environment LIQ_SIDECAR_TEST_MODE
   sudo systemctl restart vq-poly-sidecar.service
   ```
3. **Endpoint solo accessible en 127.0.0.1**: ya está bound localmente, nginx
   NO expone `/admin/*` (solo proxy `/api/`, `/audit/`, `/pnl/`).
4. **Auto-expire**: el override expira a los 60-120s, así que aún si el operador
   olvida el unset, no afecta producción más allá del window.
5. **Logged**: cada inyección graba en `risk_audit.jsonl` con `audit_type="synthetic_test_btc_inject"`.

#### Por qué no afecta el resto

- El BTC consensus 3-source sigue corriendo en background.
- Solo el **getter para kill_switch decision** consulta el override.
- El dashboard `/api/state` puede mostrar **ambos** (real consensus + override) con
  flag `is_test_mode` para distinguir.
- Si el override expira mid-trade, próximo cycle ya usa precio real.

---

## Q3 — Timeline preciso pre-NFP Vie 8 12:30 UTC

### Cronograma desde **2026-05-06 15:00 UTC** (ahora) hasta NFP

```
═══════════════════════════════════════════════════════════
  T = ahora     2026-05-06 15:00 UTC  (Mié 6)
  T = NFP       2026-05-08 12:30 UTC  (Vie 8)
  WINDOW TOTAL  ≈ 69h 30min
═══════════════════════════════════════════════════════════
```

### Ruta crítica (Plan A — todos los fixes en tiempo)

| Δ tiempo | Fecha UTC | Hito | Duración | Responsable |
|---|---|---|---|---|
| T+0 | Mié 6 15:00 | **Inicio refactor #1** (tokio::sync::watch en macro_state) | 3h | Claude operativo |
| T+3h | Mié 6 18:00 | cargo test pass + commit #1 | — | — |
| T+3h | Mié 6 18:00 | **Inicio fix #2** (max_debt_cap_usd → Config) | 1.5h | — |
| T+4.5h | Mié 6 19:30 | cargo test pass + commit #2 | — | — |
| T+4.5h | Mié 6 19:30 | **Inicio fix #3** (depeg per-pierna + tests t1-t6) | 2.5h | — |
| T+7h | Mié 6 21:30 | cargo test 135+ pass + commit #3 | — | — |
| T+7h | Mié 6 21:30 | **Build + deploy** binario V4 con los 3 fixes | 30min | — |
| T+7.5h | Mié 6 22:00 | **Synthetic stress tests** (kill-switch ≤1.5s, cap, depeg, stale) | 1.5h | — |
| T+9h | Mié 6 23:30 | **Marco sign-off + Gemma firma r119** (transición SHADOW_BLOCKED → AUDIT_PENDING) | — | Marco + Gemma |
| T+9h | Mié 6 23:30 | **Burn-in 24h SHADOW iniciado** (T+0 burn-in) | 24h | sistema solo |
| T+33h | Jue 7 23:30 | **Burn-in 24h completo** (criterios cb_blocked<1%, RSS estable, etc.) | — | — |
| T+33h | Jue 7 23:30 | **Pre-NFP synthetic re-test** (kill_switch + depeg + dashboard) | 1h | — |
| T+34h | Vie 8 00:30 | **Marco approval LIVE micro o NFP audit-only** | — | Marco |
| T+35h | Vie 8 01:30 | **Buffer time / sleep** | 11h | — |
| T+44h | Vie 8 12:00 | **Pre-NFP system check + dashboard live** | 30min | — |
| **T+45.5h** | **Vie 8 12:30** | **NFP STRESS TEST** | live | sistema |

### Margen de seguridad

- **9h trabajo intenso + 24h burn-in + 11h buffer** = 44h consumidas. Quedan **25.5h libres** desde fin de burn-in hasta NFP.
- Si Item #1 toma 5h en lugar de 3h, el plan absorbe sin problema (consume buffer).
- Si los 3 fixes toman >12h totales (vs 7h estimadas), pasamos automáticamente a **Plan B (NFP audit-only)**.

### Ruta degradada (Plan B activación temprana)

Trigger: **T+12h** (Mié 6 fin de día) sin los 3 fixes en commit.

→ Saltar synthetic stress tests del jueves.
→ NFP Vie 8 en **AUDIT-ONLY**: bot V4 sigue SHADOW, audit dashboard captura
   evento, NO hay capital LIVE.
→ Reagendar fixes #2 y #3 para Sab/Dom.
→ **CPI Lun 12 12:30 UTC** = primer test LIVE real, con 6 días de buffer.

---

## Q4 — Métricas y herramientas para monitorear RSS stability durante burn-in

### Stack de monitoring (todo ya disponible en Newark, sin instalación nueva)

#### 1. Sampling automático cada 60s

```bash
# Cron añadido durante el burn-in (auto-quit a las 24h):
mkdir -p /home/administrator/poly_sidecar/data/burnin
ssh -i /home/administrator/.ssh/id_ed25519 ubuntu@64.130.34.38 \
  'while true; do \
     PID=$(pgrep -f /home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs); \
     if [ -n "$PID" ]; then \
       echo "$(date -u +%s) $(ps -o rss=,vsz=,pcpu=,etimes= -p $PID)" >> /tmp/v4_rss_burnin.log; \
     fi; \
     sleep 60; \
   done' &
```

Output formato (timestamp UTC + RSS KB + VSZ KB + CPU% + uptime s):
```
1778075430 30092 1432452 3.2 1620
1778075490 30148 1432452 3.5 1680
...
```

#### 2. Análisis lineal de growth (post-burn-in script)

```python
# /home/administrator/poly_sidecar/analyze_rss.py
import sys
samples = [(int(l.split()[0]), int(l.split()[1])) for l in open('/tmp/v4_rss_burnin.log')]
ts0, rss0 = samples[0]
slope_kb_per_h = (samples[-1][1] - rss0) / ((samples[-1][0] - ts0) / 3600)
print(f"Slope: {slope_kb_per_h:+.2f} KB/h over {(samples[-1][0]-ts0)/3600:.1f}h")
print(f"Initial RSS: {rss0/1024:.1f} MB")
print(f"Final RSS:   {samples[-1][1]/1024:.1f} MB")
print(f"PASS criteria: |slope| < 1024 KB/h (1MB/h)")
```

**Criterios PASS**:
- Initial RSS < 50MB ✓
- Final RSS < 75MB (delta < 25MB) ✓
- Slope < 1MB/h (efectivamente plano) ✓
- Si slope > 1MB/h → **memory leak** detectado → FAIL → hotfix antes de NFP

#### 3. Alerta proactiva durante burn-in

```bash
# Script en cron @5min: si RSS > 100MB → telegram alert (si configurado) + log
```

#### 4. Métricas adicionales (tokio runtime)

Si Item #1 expone metrics tokio:
```rust
let h = tokio::runtime::Handle::current().metrics();
info!("tokio_workers={} active_tasks={} blocking_tasks={}",
    h.num_workers(), h.num_active_tasks(), h.num_blocking_threads());
```

Permite detectar **task leak** (active_tasks crece linealmente).

#### 5. Dashboard tab "burn-in" (opcional)

Añadir card en `/poly/audit/dashboard.html`:
```
RSS / VSZ / CPU% / uptime / slope KB/h
```

Que se refresque cada 60s desde un endpoint nuevo `/admin/burnin/rss`.

---

## Q5 — Protocolo si synthetic stress tests fallan en item específico

### Severity tiers + decisión

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1 - HARD FAIL (stop-the-line)                          │
│   - Kill-switch latency > 5s en synthetic spike             │
│   - max_debt_cap NO aplicado tras cambio config             │
│   - Depeg en pierna secundaria NO bloquea (regression)      │
│   - Bot V4 panics / crashes en stress                       │
│ → ACCIÓN: revertir a SHADOW_BLOCKED, hotfix obligatorio,    │
│           NO proceder a NFP                                  │
├─────────────────────────────────────────────────────────────┤
│ Tier 2 - SOFT FAIL (targeted hotfix)                        │
│   - Kill-switch latency 1.5-5s (>spec pero <crítico)        │
│   - Audit dashboard 1 query devuelve 5xx (no todas)         │
│   - RSS slope 1-5 MB/h (creciendo pero no extremo)          │
│   - 1 test case t1-t6 falla por edge case poco probable     │
│ → ACCIÓN: PASS PARCIAL condicionado a hotfix dentro de 4h,  │
│           NFP en AUDIT-ONLY (no LIVE) hasta verificar       │
├─────────────────────────────────────────────────────────────┤
│ Tier 3 - WARN (proceder con monitoreo extra)                │
│   - Latencia ocasional > 1s pero p99 dentro de spec         │
│   - Warnings clippy nuevos (no errors)                      │
│   - Cosmético (formato logs, naming)                        │
│ → ACCIÓN: documentar, registrar en r-number, no bloquea     │
└─────────────────────────────────────────────────────────────┘
```

### Decisión-tree

```
synthetic_test_run() →
  ALL PASS?                    → PROCEED to AUDIT_PENDING
  TIER 1 fail in any?          → REVERT to SHADOW_BLOCKED, hotfix mandatory
  TIER 2 fail (1-2 items)?     → PARTIAL PASS (audit-only NFP), hotfix in 4h
  TIER 2 fail (>2 items)?      → REVERT to SHADOW_BLOCKED (escala a Tier 1)
  TIER 3 only?                 → PROCEED with logged warnings
```

### Protocolo hotfix Tier 2

1. Marco aprueba targeted hotfix en mensaje explícito.
2. Code change minimal (single function, NO refactor amplio).
3. Re-run only el test específico que falló (NO suite completa).
4. Si re-test pasa → PROCEED.
5. Si re-test falla 2x → escalate to Tier 1 (revert).
6. **Window máximo 4h** desde initial fail. Si >4h → revert.
7. Cada hotfix queda en `r-numberhf` (ej. r119hf1) firmado por Marco + Gemma.

### Ejemplo aplicado (escenario hipotético)

> Test "kill_switch_latency_under_1.5s" mide 2.3s en p99.
> → Tier 2 SOFT FAIL.
> → NO revertir. Hotfix: ajustar polling tick de macro_state a 750ms (vs 1s).
> → Re-run test → mide 1.1s → PASS.
> → Resume burn-in. NFP audit-only mantiene como precaución hasta CPI Lun 12.

---

## Resumen ejecutivo (≤7 líneas)

- **Q1**: Vec<String> con join(" | "), iter sobre cycle.legs, missing feed = block defensivo
- **Q2**: LIQ_SIDECAR_TEST_MODE=1 + endpoint /admin/test/btc_inject auto-expire 60-120s, solo localhost
- **Q3**: 9h trabajo + 24h burn-in + 11h buffer = 44h. Quedan 25h libres antes NFP. Plan B activa si T+12h sin commit.
- **Q4**: ps -o rss=,vsz= cada 60s + script slope KB/h, criterio PASS slope<1MB/h
- **Q5**: 3 tiers (HARD/SOFT/WARN), Tier 1 = revert SHADOW_BLOCKED, Tier 2 = hotfix 4h window, Tier 3 = log y proceder

Listo para arrancar refactor #1 al recibir tu ✅ a estas respuestas operacionales.

---

**Spec firmadas**: r93 + r107-r111 + r115-r118 + Q-V4A.4
