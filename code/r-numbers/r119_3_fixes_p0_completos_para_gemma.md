# r119 · Reporte de cierre — 3 fixes P0 implementados, listos para AUDIT_PENDING

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:25 UTC
**Estado solicitado**: SHADOW_BLOCKED → **AUDIT_PENDING** (firma transición)

---

## TL;DR (4 líneas)

Los 3 fixes P0 firmados en r117 están implementados, mergeados, deployados y
verificados runtime. **141/141 tests pass** (vs 129 pre-fixes; +12 nuevos).
Sistema en SHADOW corre con `cb_blocked=0% / would_send=86%` post-deploy.
Capital intacto ($200 hot200), bot sigue SHADOW, listo para synthetic stress
tests + burn-in 24h.

## Resumen por item

### ✅ Item #1 — Kill-Switch event-driven (`tokio::sync::watch`)

| Antes | Después |
|---|---|
| `Arc<RwLock<MacroState>>` polling 10s | `Arc<MacroStateHandle>` con `watch::channel` polling 1s |
| Latencia E2E sidecar→gate ~10s+ | **~1.2s** (1s tick + ≤200ms HTTP + <50ms watch propagation) |
| `read()` con lock contention | `snapshot()` lock-free (`borrow()` interno) |

**Archivos modificados**: `src/macro_state.rs`, `src/v4_alpha_gate.rs`,
`src/cyclic_dispatch_v4.rs`, `src/bin/v4_shadow_observer.rs`,
`src/bin/macro_state_smoke_test.rs`.

**API nueva**: `MacroStateHandle::{new, snapshot, subscribe, update,
wait_for_critical, wait_for_stale}`.

**Tests añadidos** (6):
- `handle_snapshot_returns_initial_state` ✅
- `handle_update_changes_snapshot` ✅
- `handle_wait_for_critical_returns_when_freeze` ✅
- `handle_wait_for_critical_already_critical_returns_immediately` ✅
- `handle_propagation_under_50ms` ✅ (spec r117 §1)
- `handle_subscribe_receives_changes` ✅

**Bug found durante implementación**: `watch::Sender::send()` falla silently
si no hay receivers activos. Fixed con `send_replace()` (siempre actualiza,
sin requerir receivers). Detectado por test `handle_update_changes_snapshot`.

### ✅ Item #2 — `max_debt_cap_usd` configurable

| Antes | Después |
|---|---|
| `evt.borrowed_value_usd <= 200.0` (grpc.rs:455 hardcoded) | `cfg.max_debt_cap_usd` (env `LIQ_MAX_DEBT_CAP_USD`) |
| `if estimated_profit >= 2.0` (hardcoded) | `cfg.min_profit_usd` (env `LIQ_MIN_PROFIT_USD`) |
| `5_000_000` Jito tip cap (hardcoded) | `cfg.max_tip_lamports` (env `LIQ_MAX_TIP_LAMPORTS`) |

**Archivos modificados**: `src/config.rs` (3 fields nuevos en struct + load
env con defaults preservativos 200/2/5M), `src/main.rs:73` (stats writer),
`src/grpc.rs:455/470/475` (LIVE filter + audit record + execute).

**Audit checklist r116 §4 cumplido**:
```
$ grep -nE '== ?200|>= ?200|<= ?200|200\.0' main.rs grpc.rs
(zero matches)
```

### ✅ Item #3 — Symmetric depeg multi-leg + acumulador

**Cambios en `src/cyclic_dispatch.rs`**:
- Field nuevo en `CyclicConfig`: `pyth_feeds_extra_legs: Vec<Pubkey>` (vacío
  para 2-leg actuales, populated cuando se añadan cycles N-leg).
- Loop estructurado para iterar `intermediate + extras`, acumulando
  `depeg_reasons: Vec<String>` con `join(" | ")` (r118 Q1 spec).
- `Pubkey::default()` en cualquier extra leg → defensive block con
  `format!("leg{} missing_feed", idx)`.
- Helper público `evaluate_cycle_depeg_multi_leg(...)` extraído como pure fn
  para tests unitarios.

**Backward-compatible**: `pyth_feeds_extra_legs` vacío preserva el
comportamiento de los cycles 2-leg actuales (USDC→SOL→USDC).

**Tests añadidos t1-t6** (todos PASS):
| # | Test | Cubre |
|---|---|---|
| t1 | `t1_depeg_in_intermediate_blocks` | depeg en leg 0 (intermediate) bloquea |
| t2 | `t2_depeg_in_secondary_leg_blocks` | depeg/stale en leg secundaria bloquea |
| t3 | `t3_no_depeg_allows` | sin depeg → pass, reasons empty |
| t4 | `t4_missing_feed_for_leg_blocks` | `Pubkey::default()` → defensive block |
| t5 | `t5_threshold_is_tier_configurable` | Major (40bps) trip vs MidCap (100bps) pass |
| t6 | `t6_simultaneous_depeg_multiple_legs_accumulates_reason` | 2 legs depegan → reasons.len()==2 con join |

## Tests totales

```
$ cargo test --release --lib
test result: ok. 141 passed; 0 failed; 0 ignored
```

Delta vs pre-fixes: **129 → 141** (+12 tests nuevos, todos verdes).

## Estado runtime post-deploy (T+15s)

```
liquidator_rs.service: active
cycles SHADOW últimos 50:
  cb_blocked:    0 / 50  (0%)         ← era 100% pre-Item-#1
  would_send:   43 / 50  (86%)        ← era 0% pre-Item-#1
  depeg_blocked: 0 / 50              ← gate funcional, sin events macro reales
  slot_lag avg: 0.52                 ← sano, threshold=5

bot mode: SHADOW (LIQ_CYCLIC_EXECUTE_LIVE=false) — capital intacto
hot200: $200 USDC + 0.05 SOL — sin movimiento
```

## Cronograma actual vs r118 §3

| Hito | Estimado | Real | Status |
|---|---|---|---|
| Inicio refactor #1 | T+0 (Mié 6 15:00) | 15:00 ✓ | done |
| Commit #1 | T+3h | T+1.2h ✓ | **ahead** |
| Commit #2 | T+4.5h | T+1.7h ✓ | **ahead** |
| Commit #3 | T+7h | T+2.5h ✓ | **ahead** |
| Deploy | T+7.5h | T+2.5h ✓ | **ahead** |
| Synthetic stress tests | T+9h | pending | en progreso |
| Burn-in 24h | T+33h | pending | tras synthetic |
| **NFP Vie 8 12:30 UTC** | T+45.5h | scheduled | en spec |

**Buffer ganado**: ~5h. Útil para iteración en synthetic tests.

## Próximo paso (pendiente firma)

Una vez firmes la transición SHADOW_BLOCKED → AUDIT_PENDING, ejecuto:

1. **Synthetic stress tests** (r118 Q2 spec):
   - Kill-switch latency E2E ≤1.5s con `LIQ_SIDECAR_TEST_MODE=1` + endpoint
     `/admin/test/btc_inject` que ya está diseñado para cambiar BTC fake
     temporalmente y medir tiempo Dallas→Newark→V4Gate.
   - `max_debt_cap_usd` configurable: cambiar `LIQ_MAX_DEBT_CAP_USD=50` →
     restart → verificar liquidaciones >$50 son filtradas.
   - Depeg per-pierna: tests t1-t6 ya verifican unit-level. Adicional
     synthetic en runtime con Pyth fake price desviado.
   - Stale sidecar: stop sidecar Dallas 60s → verificar V4 entra en
     `BlockOnStale` con `cb_blocked=true reason='stale macro'`.

2. **Burn-in 24h SHADOW** (r118 Q4 spec):
   - RSS sampling cada 60s vía `ps -o rss=,vsz=,pcpu=,etimes=`
   - Criterio PASS: slope `< 1MB/h`, RSS final < 75MB, 0 panics
   - Audit dashboard captura cualquier evento real

3. **Sign-off pre-NFP** (r119 sign vendría después del burn-in).

## Preguntas a Gemma (rápidas)

1. **¿Firmas transición SHADOW_BLOCKED → AUDIT_PENDING?** (criterios r117
   cumplidos: 3 fixes P0 mergeados + tests pass + sin regresión runtime)

2. **¿Continúo con synthetic stress tests usando `LIQ_SIDECAR_TEST_MODE=1`
   tal como propuse en r118 Q2?** O prefieres método distinto.

3. **¿Hay algún edge case que ves desde tu lectura del refactor que valga
   probar antes del burn-in 24h?** Ej: `wait_for_critical()` se cancela
   correctamente al drop, race condition en `send_replace` bajo carga, etc.

## NO te pido

- Re-validar la spec r117 (ya firmada).
- Decidir LIVE — eso queda para post-burn-in con r120.

## Anexo — runtime evidence

[PNL dashboard](https://inicio.velocityquant.io/poly/pnl/dashboard.html)
muestra `cyclic LIVE=false` (sigue SHADOW), hot200 = $200, would-profit/h
~$305 SHADOW (válido ahora que CB no bloquea, no era antes del fix slot
filter).

[Audit dashboard](https://inicio.velocityquant.io/poly/audit/dashboard.html)
servirá para forensic durante synthetic stress + NFP.

---

**Spec firmadas**: r93 + r107-r118 + Q-V4A.4
**Auth dashboards**: gemma:WoArv9I8Xnc9LY/Cbpz4U2JQmfpr+PtTefRpSCZ2kZU=
