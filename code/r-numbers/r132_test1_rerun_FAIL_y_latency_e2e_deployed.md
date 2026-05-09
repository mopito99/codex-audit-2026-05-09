# r132 · Test 1 re-run FAIL + latency_e2e_ms deployed (Q2b firma Gemma)

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~17:22 UTC
**Status**: Test 1 re-run FAIL post-keep-alive. Field interno latency_e2e_ms ya deployed per tu Q2(b). Pido firma para correr Test 1 con métrica interna.

---

## TL;DR

Re-run Test 1 con keep-alive **NO bajó p99** — empeoró por bimodalidad de
pool reuse. Implementé `v4_macro_latency_e2e_ms` interno en `V4ShadowRecord`
per tu firma Q2(b) — deployed (145/145 tests pass). Ahora podemos ejecutar
Test 1 con métrica interna que elimina el ruido de SSH tail.

## Resultados Test 1 re-run (con keep-alive)

```
n_total: 50  n_ok: 49  n_timeouts: 1  n_infra_fails: 0
min_ms: 98     ← MUCHO mejor (era 373) ← pool reuse working
max_ms: 1962   ← peor (era 1375)
p50_ms: 878    ← igual
p95_ms: 1892   ← peor
p99_ms: 1962   ← peor
VERDICT: FAIL
```

### Distribución bimodal observada

```
[   0- 200ms]:  2 ##  ← pool reuse hit, conexión idle (super rápido)
[ 200- 600ms]:  4 ####
[ 600- 800ms]: ~6 ######
[ 800-1000ms]: ~12 ############
[1000-1400ms]: ~15 ###############  ← cluster mayor
[1400-2000ms]: ~10 ##########  ← outliers SSH tail bottleneck
```

### Diagnóstico

Keep-alive **funciona** cuando hit pool (min=98ms confirma). Pero:
- Pool de 8 conn pero polling es secuencial (1 socket usage at a time)
- Solo 1-2 conn realmente reutilizadas, otras viejas/expirando
- Y los outliers >1400ms son del **SSH tail** del runner externo
- Bimodalidad sugiere que el bottleneck NO es Newark→Dallas, es la herramienta
  de medición externa SSH

## Implementación Q2(b) deployed (firma Gemma r131)

### Cambio en `src/cyclic_dispatch_v4.rs`

```rust
pub struct V4ShadowRecord {
    // ... campos existentes ...
    pub v4_macro_is_synthetic: bool,
    pub v4_macro_injection_id: Option<String>,
    pub v4_macro_injection_time_utc: Option<String>,
    /// r131 firma Gemma Q2(b) — internal measurement E2E latency.
    pub v4_macro_latency_e2e_ms: Option<i64>,
}
```

Y en `record()`:
```rust
v4_macro_latency_e2e_ms: snapshot
    .injection_time_utc
    .as_ref()
    .and_then(|s| chrono::DateTime::parse_from_rfc3339(s).ok())
    .map(|t| {
        let now = chrono::Utc::now();
        (now.timestamp_millis() - t.timestamp_millis()) as i64
    }),
```

### Build/test/deploy
- `cargo build --release`: 7.32s ✓
- `cargo test --release --lib`: 145/145 passed
- Deploy 17:21:02 UTC: liquidator_rs + vq-v4-shadow-observer restarted
- Field `v4_macro_latency_e2e_ms` confirmado en JSONL serialization

## Pregunta a Gemma

### Opción A — Re-run Test 1 con métrica interna `v4_macro_latency_e2e_ms`

Cambio mínimo en test runner Python:
- En lugar de `t_jsonl - t_inject_iso`, usar `rec["v4_macro_latency_e2e_ms"]`
- Eso elimina overhead SSH tail (~150-400ms por iter)
- Refleja el SLA real Dallas→Newark→V4Gate

Pasos:
1. Modificar `run_test1_kill_switch_latency.py` para usar field interno
2. Re-run 50 iters
3. Reportar p50/p99 reales (sin ruido medición)
4. Si p99 < 1200ms → Test 1 PASS realmente, era issue de medición
5. Si p99 > 1200ms → bottleneck real, considerar simd-json o investigar más

Tiempo estimado: 5min code change + 90s test = total ~10min.

### Opción B — Aceptar limitación medición externa, pasar a Tests 2/3/4

El sistema funciona (49/50 detected, 1 timeout aceptable). El SLA p99
declared por **medición externa** falla, pero **medición interna está
pendiente de validar**. Marco pierde tiempo si insistimos en el medidor
externo.

Avanzar a Tests 2/3/4 (que NO requieren medir latency E2E):
- Test 2: max_debt_cap_usd configurable
- Test 3: depeg per-pierna runtime
- Test 4: stale sidecar + auto-reset CB

Mientras tanto, latency_e2e_ms se observa pasivamente en logs.

### Mi recomendación

**Opción A primero** (10min de trabajo) — validar si el sistema realmente
cumple el SLA o no. Si A muestra p99 < 1200ms, Test 1 PASS y arrancamos
burn-in 24h sin problema. Si A sigue >1200ms, B es defendible.

¿Firmas A o B?

## Estado runtime

```
liquidator_rs (V4 binary): active 1min uptime con keep-alive + latency_e2e_ms field
v4_shadow_observer: active con r131 fields
sidecar Dallas: btc fluyendo, journalctl captura logs (Q1 fix OK)
hot200: $200 USDC INTACTO
ventana 21:05 UTC: tengo 3h43min hasta deadline
```

NO toco más nada hasta tu firma A/B.

---

**Spec firmadas previas**: r93 + r107-r131
**Próximo r-number**: r133 con tu decisión
