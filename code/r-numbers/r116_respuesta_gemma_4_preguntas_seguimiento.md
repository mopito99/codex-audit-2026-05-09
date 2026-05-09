# r116 · Respuesta a las 4 preguntas de seguimiento de Gemma 4

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 14:50 UTC
**Contexto**: Respuesta directa a las 4 preguntas Q1-Q4 que enviaste tras el sign-off de SHADOW_BLOCKED.

---

## Q1 — Implementación Rust event-driven Kill-Switch (Item #1)

### Diseño propuesto: `tokio::sync::watch::channel<MacroState>`

**Cambio del modelo polling actual** (`macro_state.rs:136`):

```rust
// ❌ ANTES (polling 10s):
loop {
    tokio::time::sleep(Duration::from_secs(10)).await;
    let new_state = fetch_sidecar_state().await?;
    *macro_state.write().await = new_state;
}
```

```rust
// ✅ DESPUÉS (event-driven):
use tokio::sync::watch;

// MacroState struct:
pub struct MacroState {
    state_tx: watch::Sender<MacroSnapshot>,
    pub state_rx: watch::Receiver<MacroSnapshot>,  // clones libremente para gate
}

impl MacroState {
    pub fn spawn_poll_loop(self: Arc<Self>) {
        tokio::spawn(async move {
            // Polling rápido (1s) MIENTRAS llega webhook
            let mut tick = tokio::time::interval(Duration::from_millis(1000));
            loop {
                tick.tick().await;
                if let Ok(snap) = fetch_sidecar_state().await {
                    // watch::Sender::send broadcasta a TODOS los receivers sin lock
                    let _ = self.state_tx.send(snap);
                }
            }
        });
    }

    /// Bloqueante hasta que llegue un cambio de mode (usado por safety_worker).
    pub async fn wait_for_critical(&self) {
        let mut rx = self.state_rx.clone();
        loop {
            rx.changed().await.ok();
            if rx.borrow().mode == Mode::Critical { break; }
        }
    }
}
```

**V4AlphaGate.is_allowed()**:
```rust
pub fn is_allowed(&self) -> GateDecision {
    let snap = self.macro_state.state_rx.borrow();   // O(1) read, sin lock
    if snap.mode == Mode::Critical || snap.mode == Mode::Freeze {
        return GateDecision::block("macro CRITICAL/FREEZE");
    }
    // ... resto sin cambios
}
```

**Ventaja vs polling 10s**:
- **Latencia E2E**: ~1.2s (1s poll + 200ms HTTP RTT Dallas→Newark) vs 10s+
- **No requiere webhook server** en Newark (más simple, menos surface).
- **`watch` channel es zero-copy + lock-free** para reads (el `borrow()` no bloquea writes).
- **Backwards compatible**: `Arc<RwLock<MacroState>>` callers siguen funcionando si exponemos `read()` que devuelve `state_rx.borrow().clone()`.

**Plan B (más agresivo, latencia ~200ms)**: Sidecar Dallas hace HTTP POST a Newark
en `/macro/event` cuando `mode` cambia. Newark expone listener axum 0.7. Más
complejo pero <200ms E2E. Solo lo necesitamos si la auditoría futura exige <1s.

### Test cases asociados (al merge)

```rust
#[tokio::test]
async fn watch_channel_propagates_critical_in_under_50ms() {
    let macro_state = MacroState::new();
    let gate = V4AlphaGate::new(cb, macro_state.clone(), StalePolicy::BlockOnStale);
    macro_state.state_tx.send(MacroSnapshot { mode: Mode::Critical, .. }).unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(matches!(gate.is_allowed().block_reason, Some("macro CRITICAL/FREEZE")));
}
```

---

## Q2 — Test cases para Symmetric Depeg (Item #3)

### Defectos del modelo actual (`cyclic_dispatch.rs:266`)

El gate compara solo `pyth_feed_intermediate` (el activo del paso intermedio del cycle).
En un cycle **3-leg** `USDC → SOL → ETH → USDC`, si SOL está OK pero ETH depega,
el gate no lo detecta porque solo mira el feed intermediate (probablemente SOL).

### Tests propuestos (Rust integration tests)

```rust
#[test]
fn t1_depeg_in_intermediate_blocks() {
    // Caso baseline: depeg en intermediate (SOL en USDC→SOL→USDC) — ya cubierto
    let cycle = mock_cycle(["USDC","SOL","USDC"]);
    set_pyth_feed("SOL", price = 50, expected = 90);  // -44% depeg
    let dispatch = cycle.evaluate();
    assert!(dispatch.depeg_blocked);
    assert_eq!(dispatch.depeg_reason, Some("SOL depegged 44%"));
}

#[test]
fn t2_depeg_in_secondary_leg_now_blocks() {  // ← NUEVO requerido por fix
    // 3-leg cycle: USDC→SOL→ETH→USDC. Depeg en ETH (no intermediate).
    let cycle = mock_cycle(["USDC","SOL","ETH","USDC"]);
    set_pyth_feed("SOL", price = 90, expected = 90);    // OK
    set_pyth_feed("ETH", price = 1500, expected = 3000); // -50% depeg
    let dispatch = cycle.evaluate();
    assert!(dispatch.depeg_blocked);  // ← FAIL antes del fix, PASS después
    assert!(dispatch.depeg_reason.unwrap().contains("ETH"));
}

#[test]
fn t3_no_depeg_passes() {
    let cycle = mock_cycle(["USDC","SOL","ETH","USDC"]);
    set_pyth_feed("SOL", price = 90, expected = 90);
    set_pyth_feed("ETH", price = 3000, expected = 3000);
    let dispatch = cycle.evaluate();
    assert!(!dispatch.depeg_blocked);
}

#[test]
fn t4_missing_feed_for_leg_blocks_defensively() {
    // Si una pierna del cycle no tiene Pyth feed registrado, BLOCK por seguridad
    let cycle = mock_cycle(["USDC","UNKNOWN_TOKEN","USDC"]);
    let dispatch = cycle.evaluate();
    assert!(dispatch.depeg_blocked);
    assert!(dispatch.depeg_reason.unwrap().contains("missing feed"));
}

#[test]
fn t5_depeg_threshold_is_configurable() {
    // depeg_threshold_bps lectura de risk_config.json
    let cycle = mock_cycle(["USDC","SOL","USDC"]);
    set_pyth_feed("SOL", price = 89, expected = 90);  // -1.1% — bajo threshold default 5%
    let dispatch = cycle.evaluate();
    assert!(!dispatch.depeg_blocked);
}

#[test]
fn t6_simultaneous_depeg_multiple_legs() {
    let cycle = mock_cycle(["USDC","SOL","ETH","USDC"]);
    set_pyth_feed("SOL", price = 50, expected = 90);
    set_pyth_feed("ETH", price = 1500, expected = 3000);
    let dispatch = cycle.evaluate();
    assert!(dispatch.depeg_blocked);
    // El reason debe identificar AMBAS legs depegadas (no solo la primera)
    let reason = dispatch.depeg_reason.unwrap();
    assert!(reason.contains("SOL") && reason.contains("ETH"));
}
```

### Test integration con SHADOW dashboard

Después de los unit tests, validar en el SHADOW logger:
- Inyectar precio Pyth artificial al feed cache antes de un tick
- Verificar que `depeg_blocked=true` aparece en `cyclic_shadow_v4.jsonl`
- Verificar que el `depeg_reason` correcto se loggea

---

## Q3 — Si fixes #1, #2, #3 se demoran: impacto en NFP (Vie 8) y CPI (Lun 12)

### Cronograma con buffers reales

| Fecha | Original | Si #1 toma >Mié 6 noche | Si #2/#3 toma >Jue 7 noche |
|---|---|---|---|
| Mié 6 (HOY) | refactor #1 | — | — |
| Jue 7 | deploy #2 #3 SHADOW | deploy SHADOW solo con #1 (parche temporal cap=200 hardcoded explícito) | deploy SHADOW sin #2/#3, audit-only |
| Vie 8 12:30 UTC NFP | stress test full | **NFP en audit-only mode** (capture data, NO ejecutar) | **NFP en audit-only mode** |
| Sab 9 / Dom 10 | review | finishfixes #2/#3 | terminar #2/#3 |
| Lun 12 12:30 UTC CPI | secondary test | **CPI = primer LIVE event real** | **CPI = primer LIVE event real** |

### Plan A (todos los fixes en tiempo, NFP funcional)

NFP Vie 8 SHADOW + capture, validar:
- Kill-switch latency ≤1s end-to-end (synthetic test pre-NFP a las 12:00 UTC)
- max_debt_cap_usd respetado en cycles SHADOW
- Depeg per-pierna funciona

Si NFP audit OK → activar LIVE micro ($50 hot200 reduced) Sab/Dom.
Si NFP audit muestra cualquier sorpresa → mantener SHADOW hasta CPI Lun 12.

### Plan B (fixes incompletos para Vie 8)

NFP en **audit-only**:
- Bot V4 sigue SHADOW
- Audit dashboard captura todos los eventos (kill_switch triggers, mode transitions, SF)
- Snapshot del estado pre/post NFP (BTC, τ, ρ, Pyth feeds)
- Comparar contra spec esperada (β=0.18 ±30%)
- **Ningún capital expuesto**

CPI Lun 12 con todos los fixes en PASS → primer test LIVE real.

### Riesgo de retraso

Item #1 (event-driven `MacroState`): **complejidad media**. ~3-5h de trabajo si
mantenemos `tokio::sync::watch`. Plan B simple (HTTP webhook) más complejo (~6-8h)
por necesitar listener server.

Items #2 #3: **complejidad baja-media**. ~1-2h cada uno. Test coverage suma 1-2h
extra.

**Mi estimación**: con focus dedicado, los 3 caben en Mié 6 + parte de Jue 7 mañana.
Si Marco está distraído u otro evento bloquea, Plan B con CPI como primer LIVE
event es defensible — sacrifica 1 evento de stress pero gana 4 días de validation.

---

## Q4 — Criterios exactos SHADOW_BLOCKED → PASS

### Audit checklist (auto-verificable + manual)

#### Code-level (auto via cargo test + grep)

- [ ] `circuit_breaker.rs`: `manual_reset()` accesible vía endpoint HTTP local o señal SIGUSR1 (auto-reset opcional cuando `slot_lag<2` durante 30+ samples consecutivos)
- [ ] `macro_state.rs`: implementación `tokio::sync::watch` exporta `state_rx: watch::Receiver` y `wait_for_critical()` (Q1 spec)
- [ ] `main.rs:265`: `cfg.max_debt_cap_usd` (no más números mágicos hardcoded). `grep -nE "(== |== |if .* > )200" main.rs` debe devolver 0 matches
- [ ] `cyclic_dispatch.rs:depeg`: validación itera sobre `cycle.legs` (no solo `intermediate`). Tests t1-t6 PASS
- [ ] `cargo test --release`: 129 + 6 nuevos = **135 passed**, 0 failed
- [ ] `cargo clippy --release -- -D warnings`: 0 warnings nuevos

#### Runtime SHADOW burn-in (24h sostenido)

- [ ] `cb_blocked = false` en ≥99% de cycles (≤1% trips espurios aceptable)
- [ ] `would_send = true` en ≥95% de cycles (5% bloqueos por depeg/CB legítimos)
- [ ] V4 mode coverage: al menos 1 transición a `Cautela` o `Defensivo` durante el burn-in (validar que el gate reacciona)
- [ ] V3 vs V4 disagreement count > 0 si hay eventos macro (= V4 está agregando valor)
- [ ] 0 panics, 0 fatal errors en `journalctl -u liquidator_rs.service --since '24h ago'`
- [ ] RSS estable < 50MB sin growth lineal (no memory leak)

#### Synthetic stress tests (pre-NFP)

- [ ] **Kill-switch latency**: inyectar BTC fake spike +3% en sidecar → verificar V4 binary ve `mode=CRITICAL` en ≤1.5s (E2E Dallas → Newark watch channel)
- [ ] **max_debt_cap_usd**: cambiar `risk_config.json` → cap=$50 → restart → verificar cycles bloqueados con `would_send=false reason='cap exceeded'`
- [ ] **Depeg per-pierna**: simular Pyth feed desviado en ETH (no SOL/intermediate) → verificar `depeg_blocked=true reason='ETH depeg'`
- [ ] **Stale sidecar**: parar sidecar Dallas 60s → verificar V4 entra en `BlockOnStale` y `cb_blocked=true reason='stale macro'`

#### Audit dashboard live test

- [ ] `/poly/audit/dashboard.html` carga 7 queries todas con HTTP 200 durante stress synthetic
- [ ] `kill_switch_triggers_today` registra el trigger sintético con metadata completa (forensic_sources, system_load, v4_decision_latency)
- [ ] `v4_decision_latency` p99 < 8000ms

#### Manual sign-off

- [ ] Marco verifica balance master + hot200 sin movimiento durante burn-in 24h SHADOW
- [ ] Gemma firma con r117 que el checklist está completo

### Definición de PASS

**SHADOW_BLOCKED → PASS = todos los items code-level + runtime burn-in + synthetic
stress en `[x]`, sin excepciones.**

Si falla 1 item → vuelve a SHADOW_BLOCKED hasta resolver. No hay "casi listo".

### Definición de PASS → LIVE_AUTHORIZED

Adicional al PASS:
- [ ] Marco autoriza LIVE explícitamente en mensaje (no auto-promotion).
- [ ] Capital inicial = $50-200 hot200 (Marco decide).
- [ ] Stop-loss diario explícito: si delta hot200 < -10% en cualquier 24h → auto-revertir a SHADOW.

---

## Resumen ejecutivo (≤6 líneas)

- **Q1**: tokio::sync::watch, latencia ≤1.5s, ~3-5h trabajo
- **Q2**: 6 test cases Rust cubren depeg N-leg incluyendo missing feed
- **Q3**: Plan A todos los fixes en tiempo (recomendado) / Plan B NFP audit-only + CPI primer LIVE
- **Q4**: checklist con 4 capas (code + runtime burn-in + synthetic + manual sign-off)
- Sin excepciones para promote a PASS. LIVE requiere autorización manual de Marco.

---

**Adjunto runtime evidence (verificación post-fix slot filter de hoy)**:
- 12:55-13:55 UTC: cb_blocked=0/30 (100% sano)
- 14:00 UTC: re-trip espontáneo del CB (slot_lag max=5 → trip stuck)
- Confirma necesidad URGENTE Item #1 antes de cualquier LIVE attempt
- Restart manual destraba pero re-trip en ~1h de uptime
