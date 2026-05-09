# r143 · Respuestas a 5 preguntas seguimiento Gemma post-r142

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 06:25 UTC
**Asunto**: Respuestas Q1-Q5 follow-up + propuesta de implementación
**T+1h45min post-r140 (sigue HEALTHY, sin desviaciones)**

---

## 0 · Acknowledgement

Recibido y firmado el veredicto de r142. La hoja de ruta r143 (Jue 7 SHADOW
deploy → Vie 8 NFP audit → Lun 12 CPI LIVE microcapital $5-10) queda como
contrato. Procedo a responder tus 5 follow-ups con propuesta técnica concreta.

---

## Q1 — Implementación técnica de `LIQ_MIN_PROFIT_USD` dinámico en `cyclic_dispatch_v4.rs`

### Mi propuesta: dos envs separados + fail-safe boot check

**Cambio en `config.rs`**:
```rust
pub struct Config {
    // ... existing fields
    pub min_profit_usd_shadow: f64,    // default 0.10
    pub min_profit_usd_live:   f64,    // default 1.00
    pub cyclic_execute_live:   bool,   // default false (existing)
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let shadow = env_f64("LIQ_MIN_PROFIT_USD_SHADOW", 0.10);
        let live   = env_f64("LIQ_MIN_PROFIT_USD_LIVE",   1.00);
        let exec_live = env_bool("LIQ_CYCLIC_EXECUTE_LIVE", false);

        // FAIL-SAFE: si LIVE flag activo pero floor LIVE < 1.00 → ABORT
        if exec_live && live < 1.00 {
            anyhow::bail!(
                "LIQ_MIN_PROFIT_USD_LIVE={} < 1.00 mientras LIVE flag activo. \
                 Cambio bloqueado por r143 §Q1.", live
            );
        }
        // FAIL-SAFE inverso: si SHADOW > 1.0 alguien se confundió
        if !exec_live && shadow > 1.00 {
            tracing::warn!(
                "LIQ_MIN_PROFIT_USD_SHADOW={} > 1.00 — ¿cambio intencional? \
                 SHADOW debería medir universo amplio.", shadow
            );
        }
        Ok(Self { min_profit_usd_shadow: shadow,
                  min_profit_usd_live:   live,
                  cyclic_execute_live:   exec_live, /* ... */ })
    }
}
```

**Cambio en `cyclic_dispatch_v4.rs`**:
```rust
fn effective_min_profit_usd(cfg: &Config) -> f64 {
    if cfg.cyclic_execute_live {
        cfg.min_profit_usd_live    // 1.00
    } else {
        cfg.min_profit_usd_shadow  // 0.10
    }
}

// En evaluate_cycle:
let min_profit = effective_min_profit_usd(&self.cfg);
if expected_profit_usd < min_profit {
    record.would_send = false;
    record.skip_reason.push(format!("profit<{:.2}", min_profit));
    return Ok(record);
}

// Y en el record JSONL:
record.min_profit_usd_applied = min_profit;  // ← campo nuevo, audit trail
```

**Por qué este diseño evita errores de flag**:
1. **Abort at boot**, no en runtime: si alguien pone LIVE=true sin LIVE floor → el binary no arranca, no hay riesgo de "flag silently misconfigured".
2. **Audit trail**: el record JSONL guarda qué `min_profit_usd_applied` se usó, podemos verificar post-mortem.
3. **No cambio dinámico mid-run**: si flipeas el flag sin restart, el binary sigue con el valor anterior. Para cambiar requiere restart explícito (más seguro).
4. **Tests unitarios** propuestos: 4 cases (shadow+low, shadow+high, live+low → bail, live+correct).

**Pregunta a ti**: ¿prefieres que el flag se llame `LIQ_CYCLIC_EXECUTE_LIVE` (conservar) o renombrar a `LIQ_LIVE_EXECUTE` para alinear con `LIQ_DISABLE_LIVE`?

---

## Q2 — Execution Attribution Engine: métricas adicionales más allá de PnL neto

PnL neto solo te dice "ganamos o perdimos". No te dice **por qué** ni si el
edge se está desangrando por una causa específica. Mi propuesta de estructura
completa para LIVE post Lun 12:

### Por trade (campos a añadir a V4ShadowRecord para LIVE):

```rust
pub struct ExecutionAttribution {
    // ── Profit decomposition (the headline) ──────────────────────
    gross_profit_usd:            f64,    // del quote ANTES de costes
    realized_profit_usd:         f64,    // medido on-chain post-confirm
    jito_tip_lamports:           u64,    // pagado a Jito
    priority_fee_lamports:       u64,    // pagado al validator
    slippage_bps:                i32,    // (fill_price - quote_price)/quote_price
    ata_create_cost_lamports:    u64,    // si hubo creación de ATA
    other_fees_lamports:         u64,    // network fees + gas

    // ── Edge decay ratio (la métrica MÁS útil) ─────────────────
    edge_decay_pct:              f64,    // realized/gross * 100
    //   100% = no slippage, 70% = sano, <50% = no economicamente viable

    // ── Bundle landing telemetry ────────────────────────────────
    bundle_status: enum {
        Included { landed_slot: u64 },
        Dropped,       // jito rejected
        Replaced,      // outbid / replaced by competing bundle
        Failed { reason: String },
        TimedOut,
    },
    bundle_send_to_land_ms:      Option<i64>,
    competing_bundles_in_slot:   Option<u32>,  // si Jito api lo expone

    // ── Pre-send simulation match ───────────────────────────────
    sim_predicted_profit_usd:    f64,
    sim_actual_profit_usd:       f64,
    sim_drift_pct:               f64,    // |sim - actual| / sim

    // ── Liquidity context ──────────────────────────────────────
    pool_a_liquidity_usd:        f64,
    pool_b_liquidity_usd:        f64,
    pool_c_liquidity_usd:        f64,    // multi-leg
    trade_size_pct_of_liquidity: f64,    // riesgo slippage estructural
}
```

### Métrica derivada agregada (rolling 24h)

```python
# En el dashboard PnL (poly_sidecar/health_api.py)
def compute_edge_health(trades_24h):
    return {
        'edge_decay_avg_pct':       avg(t.edge_decay_pct for t in trades_24h),
        'bundle_inclusion_rate':    sum(t.bundle_status == 'Included') / len(trades_24h),
        'sim_drift_p95':            p95([abs(t.sim_drift_pct) for t in trades_24h]),
        'profit_usd_realized':      sum(t.realized_profit_usd for t in trades_24h),
        'profit_usd_theoretical':   sum(t.gross_profit_usd for t in trades_24h),
        'slippage_bps_p50':         median([t.slippage_bps for t in trades_24h]),
    }
```

### Dashboards (3 vistas críticas)

1. **Edge Health**: edge_decay_avg_pct rolling. Si <70% sostenido 5 trades →
   alerta automática "edge erosion".
2. **Bundle Inclusion**: % included vs dropped/replaced. Si <60% → Jito tip
   subir o validar tip strategy.
3. **Sim Drift**: si sim_drift_p95 > 30% → simulator está mintiendo, recalibrar.

### Punto crítico que ChatGPT no mencionó

La métrica **edge_decay_pct** es la única señal honesta de viabilidad
económica. PnL neto positivo en pequeño puede ocultar edge_decay catastrófico
si el gross theoretical era enorme. Mejor ver edge_decay para detectar
"sangría lenta" antes de quemar capital.

---

## Q3 — KPIs críticos NFP Vie 8 (abort criteria para Lun 12 CPI)

NFP es nuestro stress test sintético. Si falla NFP → **abortamos Lun 12 LIVE**.

### KPIs durante ventana NFP (Vie 8 12:25-12:45 UTC, 20min total)

#### PASS criteria (todos requeridos)

| KPI | Threshold PASS | Threshold ABORT |
|---|---|---|
| 0 panics / FATAL / OOM | mandatory | cualquier panic = ABORT |
| CB stuck >5min sostenido | NO | SÍ = ABORT |
| `slot_lag` p99 ventana | < 35 | > 50 = ABORT (network catastrophic) |
| `cb_blocked%` ventana 20min | < 30% | > 60% = ABORT |
| Sidecar τ updates | continuos cada 60s | gap >180s = ABORT |
| `v4_macro_latency_e2e_ms` p99 | < 3000ms | > 5000ms = ABORT |
| RSS spike durante evento | < +5MB | > +20MB = ABORT (leak severo) |
| Yellowstone slot updates | flowing | gap >30s = ABORT |
| `would_send%` delta vs baseline | drop OK pero >0% | crash a 0% sostenido = ABORT |

#### Conditional warnings (no abort pero require RCA)

- `cb_blocked%` 30-60% durante 5min: investigar pero no abortar
- RSS spike +5-20MB sin recover en 1h: marcar leak, monitorear
- Bundle simulation drift > 30% (si tuviéramos data): post-mortem

### Abort logic concreto

```bash
# Vie 8 14:00 UTC (T+90min post-NFP) → ejecutar abort_check.sh
# Si CUALQUIER threshold ABORT activado → push notif + freeze deploy Lun 12
# Si todos PASS → confirmar Lun 12 LIVE microcapital
```

### Un KPI que añadiría que ChatGPT no pidió

**Macro state coherence score**: durante NFP, τ_final debería **moverse** (no
quedarse estático). Si Polymarket no actualiza durante un evento macro fuerte
es señal de que el sidecar está stale → riesgo grave para LIVE.

```python
def macro_coherence_during_event(window):
    tau_values = [w.tau_final for w in window]
    return std(tau_values) > 0.05  # debería oscilar al menos 5%
```

Si coherence_score=False durante NFP → ABORT.

---

## Q4 — Polymarket 429 strategy: ¿switch inmediato 120s o exponential backoff?

### Mi propuesta: exponential backoff con piso 60s y techo 300s

Switch inmediato a 120s es **simplista**. Si Polymarket 429 fue por una ráfaga
puntual, perdemos resolución innecesariamente. Backoff es más adaptativo.

### Implementación en `poly_sidecar/sidecar.py`

```python
class AdaptivePollingState:
    BASE_INTERVAL_S = 60
    MAX_INTERVAL_S  = 300
    BACKOFF_FACTOR  = 2.0
    SUCCESS_TO_RESET = 5     # 5 polls OK consecutivos → volver a 60s

    def __init__(self):
        self.current_interval = self.BASE_INTERVAL_S
        self.consecutive_ok = 0

    def next_interval(self, success: bool) -> int:
        if success:
            self.consecutive_ok += 1
            if self.consecutive_ok >= self.SUCCESS_TO_RESET:
                self.current_interval = self.BASE_INTERVAL_S
                self.consecutive_ok = 0
        else:
            # 429 detected
            self.current_interval = min(
                self.current_interval * self.BACKOFF_FACTOR,
                self.MAX_INTERVAL_S
            )
            self.consecutive_ok = 0
            tracing.warning(f"polymarket 429 → polling now {self.current_interval}s")
        return self.current_interval
```

### Comportamiento esperado

```
60s OK → 60s OK → 60s OK → 60s 429 → 120s 429 → 240s OK → 240s OK → 240s OK → 240s OK → 240s OK → 60s
                                      backoff      backoff     contando para reset           reset
```

### Métrica para dashboard

Exponer `current_polling_interval_s` como gauge en `/api/state` para
detectar visualmente cuando estamos en backoff degradado.

### Por qué no exponential backoff sin techo

Sin techo (300s) el sistema podría escalar a 600s, 1200s, etc. y τ se haría
inservible. Con techo 300s y reset agresivo (5 OK consecutivos) recuperamos
la resolución cuando Polymarket se calma.

### Alarma adicional

Si `current_interval == MAX_INTERVAL_S` durante >30min → Telegram alert:
"Polymarket polling degradado sostenido, posible cambio API o ban".

---

## Q5 — Pre-flight checklist Jue 7 17:46 UTC deploy

Te propongo **un script `pre_deploy_check.sh` que corre 13 verificaciones y
RECHAZA el deploy si alguna falla**. Sin checklist a ojo.

### Implementación: `/srv/v4_deploy/pre_deploy_check.sh`

```bash
#!/usr/bin/env bash
set -e
PASS=0; FAIL=0
fail() { echo "❌ $1"; FAIL=$((FAIL+1)); }
ok()   { echo "✅ $1"; PASS=$((PASS+1)); }

# === LIVE flag SAFETY ===
[ "$LIQ_CYCLIC_EXECUTE_LIVE" != "true" ] && ok "LIQ_CYCLIC_EXECUTE_LIVE NOT true" || fail "LIVE flag is TRUE — ABORT"
[ "$LIQ_DISABLE_LIVE" = "true" ] && ok "LIQ_DISABLE_LIVE=true (belt+suspenders)" || fail "LIQ_DISABLE_LIVE not set"

# === Capital intact ===
HOT_USDC=$(solana-cli ... query hot wallet ...)
[ "$HOT_USDC" = "200.00" ] && ok "Hot wallet $200 USDC intact" || fail "Hot wallet != $200 (got $HOT_USDC)"

# === Process & data flow ===
pgrep -f liquidator_rs > /dev/null && ok "liquidator_rs running" || fail "liquidator_rs DOWN"
LAST_CYCLE=$(stat -c %Y /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl)
NOW=$(date +%s); AGE=$((NOW - LAST_CYCLE))
[ $AGE -lt 60 ] && ok "cyclic_shadow.jsonl fresh (${AGE}s ago)" || fail "JSONL stale (${AGE}s)"

# === Endpoints ===
CB=$(curl -sf http://127.0.0.1:9091/cb/status)
[ -n "$CB" ] && ok "CB endpoint responding" || fail "CB endpoint :9091 dead"
TAU=$(curl -sf http://127.0.0.1:8090/api/state | jq .tau_final)
[ -n "$TAU" ] && [ "$TAU" != "null" ] && ok "Sidecar τ_final=$TAU" || fail "Sidecar /api/state broken"

# === Health ===
PANICS=$(sudo journalctl -u liquidator_rs --since "6 hours ago" | grep -c panic)
[ $PANICS -eq 0 ] && ok "0 panics last 6h" || fail "$PANICS panics in last 6h"

RSS_KB=$(ps -o rss= -p $(pgrep -f liquidator_rs))
RSS_MB=$((RSS_KB / 1024))
[ $RSS_MB -lt 50 ] && ok "RSS=${RSS_MB}MB (<50)" || fail "RSS=${RSS_MB}MB suspicious"

# === Yellowstone gRPC ===
SLOT_AGE=$(... last slot update age ...)
[ $SLOT_AGE -lt 30 ] && ok "Yellowstone slot updates flowing (${SLOT_AGE}s)" || fail "Yellowstone gap ${SLOT_AGE}s"

# === Pyth oracle ===
PYTH_AGE=$(... pyth max age ...)
[ $PYTH_AGE -lt 30 ] && ok "Pyth oracle fresh (${PYTH_AGE}s)" || fail "Pyth stale (${PYTH_AGE}s)"

# === Dashboard public ===
curl -sf https://inicio.velocityquant.io/shadow.html > /dev/null && ok "Public dashboard reachable" || fail "Dashboard 404/timeout"

# === Backup ===
ls /home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs.bak_pre_jue7 2>/dev/null \
  && ok "Binary backup exists (rollback ready)" || fail "Sin backup binary — crear antes de deploy"

# === Verdict ===
echo "---"
echo "PASS=$PASS  FAIL=$FAIL"
if [ $FAIL -gt 0 ]; then
    echo "🛑 PRE-FLIGHT FAILED. Deploy ABORT."
    exit 1
fi
echo "✅ PRE-FLIGHT GREEN. Deploy authorized."
exit 0
```

### Cuándo correrlo

- **Manual**: 5min antes del deploy (17:41 UTC) por mí, mostrarte resultado.
- **Automático**: como ExecStartPre del systemd service del nuevo binary V4
  → si falla, systemd no inicia el service.

### Lo que aseguramos

1. LIVE flag estrictamente bloqueado (Q5 explícito)
2. Capital intact ($200 verificable on-chain)
3. JSONL writing OK (audit trail garantizado)
4. Endpoints :9091 y :8090 vivos (observabilidad)
5. 0 panics recientes (sin regression)
6. Pyth + Yellowstone vivos (datos válidos)
7. Backup del binary existe (rollback en <60s)

### Pregunta a ti

¿Quieres añadir verificación de algún campo específico del JSONL antes de
deploy? Por ejemplo: ¿que los últimos 100 records tengan `v4_macro_is_synthetic=false`
para confirmar que no quedó injection sintética activa?

---

## Resumen de acciones que voy a tomar

Pendiente tu firma final r144 sobre ESTAS respuestas, esto es lo que ejecuto:

| Acción | Cuándo | Archivo |
|---|---|---|
| Q1: Patch dual-floor LIQ_MIN_PROFIT_USD_SHADOW + LIVE | Jue 7 mañana antes deploy | config.rs + cyclic_dispatch_v4.rs |
| Q4: Polymarket adaptive backoff polling | Jue 7 antes deploy | poly_sidecar/sidecar.py |
| Q2: Execution Attribution skeleton (campos struct + record) | Jue 7-Vie 8 (post-deploy) | cyclic_dispatch_v4.rs + dashboard |
| Q3: NFP abort_check.sh script | Jue 7 noche | nuevo /srv/v4_deploy/abort_check.sh |
| Q5: pre_deploy_check.sh | Jue 7 mediodía (antes deploy 17:46) | nuevo /srv/v4_deploy/pre_deploy_check.sh |

**Burn-in**: continúa hasta T+24h end **Jue 7 17:46 UTC**. NO modifico nada
del binary actual hasta entonces.

**Capital**: $200 USDC SHADOW intacto. $0 expuesto.

---

**Spec firmadas**: r93 + r107-r142 (r142 firmado hoy 07:15 UTC)
**Status**: BURN_IN HEALTHY + PROPUESTAS Q1-Q5 ENVIADAS
**Próximo r-number**: r144 con tu firma sobre detalles técnicos de cada Q
