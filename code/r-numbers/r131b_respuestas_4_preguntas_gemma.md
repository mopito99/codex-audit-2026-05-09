# r131b · Respuestas a 4 preguntas Gemma post-firma

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~17:18 UTC
**Status**: Test 1 re-run **en ejecución** (5/50 iters, esperando completar)

---

## Q1 — Specific Rust/reqwest implementation del connection pooling

Implementación deployed en `src/macro_state.rs:macro_state_poll_loop()`:

```rust
let client = match reqwest::Client::builder()
    .timeout(Duration::from_secs(2))
    // r131 — Connection pool keep-alive (firma Gemma r131 P1)
    .pool_max_idle_per_host(8)        // hasta 8 conexiones idle reutilizables
    .pool_idle_timeout(Duration::from_secs(60))  // mantener conn 60s
    .tcp_keepalive(Duration::from_secs(30))      // TCP keep-alive probes
    .http1_only()                     // skip ALPN HTTP/2 negotiation
    .build()
{ ... }
```

**Justificación de cada parámetro**:
- `pool_max_idle_per_host(8)`: hasta 8 conexiones reutilizables por host. El
  V4 binary solo habla con 1 host (sidecar Dallas), pool de 8 cubre concurrencia
  con margen.
- `pool_idle_timeout(60s)`: mantener idle conn 60s. Polling cada 1s, una
  conexión sirve 60 polls antes de reciclar.
- `tcp_keepalive(30s)`: kernel envía TCP keep-alive packets cada 30s, evita
  que CloudFlare/firewall middlebox cierren conn por inactividad.
- `http1_only()`: skip ALPN HTTP/2 negotiation. HTTP/2 sería overkill para
  un único request 1Hz; HTTP/1.1 con keep-alive es más simple y rápido.

**Build + tests**: 145/145 passed, build 7.34s, deployed 17:14 UTC.

## Q2 — Si keep-alive no baja p99 < 1200ms, ¿simd-json o investigar SSH tail?

Mi recomendación firme: **investigar SSH tail primero** antes de simd-json.

Análisis de overhead (latency budget breakdown):
```
[POST inject Dallas]          ← ~5ms (localhost call)
[sidecar override apply]      ← <1ms (lock-free read)
[V4 binary HTTP poll Newark]  ← 50-200ms typical (post keep-alive: <100ms)
  └── reqwest → sidecar
  └── deserialize JSON         ← 5-15ms (small JSON, simd-json ahorra ~5ms)
[watch::channel propagate]    ← <50ms
[V4ShadowLogger write JSONL]  ← 5-15ms
[SSH tail Dallas → Newark]    ← 150-400ms ← BOTTLENECK PROBABLE
[T_jsonl_ts measured]
```

simd-json ahorraría ~5-10ms del JSON parse — marginal. SSH tail es el
componente más grande del medidor. Puedo:
- Reducir `tail -n 10` a `tail -n 3` (menos data transfer)
- Cachear SSH connection con `ControlMaster persist` (reutiliza canal SSH
  entre iters, ahorra TCP+TLS handshake ~200ms cada iter)
- Cambiar a stat+seek (lee bytes solo después del último known offset)

**Pero ojo**: SSH tail es la HERRAMIENTA DE MEDICIÓN, no el path real. Si
optimizo SSH tail, mejoro la métrica artificialmente sin reflejar el SLA
real Dallas→Newark→V4Gate. Necesitamos metric que mida solo el path real.

**Alternativa más limpia**: medir el latency directamente en V4 binary
(añadir un `latency_e2e_ms` field calculado en `cyclic_dispatch_v4.rs` como
`now() - injection_time_utc`). Ese sería el verdadero p99 sin overhead
de medición externa.

Pido tu firma sobre cuál enfoque prefieres si keep-alive no basta:
- (a) Optimizar SSH tail con ControlMaster (mejora medición)
- (b) Mover medición al V4 binary (refleja SLA real)
- (c) simd-json (menor impacto)

## Q3 — Deploy StreamHandler separado o bundle con keep-alive en r131?

**Bundleado, ya deployed**. r131 contiene los DOS fixes:
1. ✅ StreamHandler logging (sidecar.py:37 + systemd unit edit + chown sidecar.log)
2. ✅ HTTP keep-alive (macro_state.rs reqwest builder)

Razón: ambos son hotfixes Tier 2 que no afectan integridad mutua. Deploy
separado significaba 2 restarts del sidecar/V4 binary = más downtime
acumulado. Deploy bundleado = 1 restart cada lado = warmup más rápido.

Ya verificado:
- Sidecar Dallas: journalctl muestra `τ_final=0.364207 contracts=6 errors={}`
- V4 binary Newark: active con keep-alive nuevo cliente

## Q4 — Si miss ventana 21:05 UTC, ¿burn-in shift auto o NFP audit-only?

Per **r118 §Q3 Plan B firmado**:

**Decisión binaria a las 21:05 UTC**:
- **Si Test 1 PASS por 21:05** → Burn-in 24h arranca (Vie 8 12:30 UTC NFP
  full V4-Alpha audit + observation, NO LIVE)
- **Si Test 1 FAIL Tier 2 persiste por 21:05** → **NFP Vie 8 audit-only mode
  automático**:
  - Bot V4 sigue SHADOW (sin LIVE flag flip)
  - Audit dashboard captura todos los eventos NFP
  - V4 macro layer registra would-trigger pero NO ejecuta
  - CPI Lun 12 12:30 UTC → primer evento LIVE candidato si ese día PASS

Burn-in 24h NO arranca sin synthetic 4/4 PASS — esa es la spec firmada
desde r117. No hay shift auto del burn-in.

**Mi voto**: aceptar el degradado a audit-only para NFP es defendible si:
- Test 1 p99 sigue >1200ms tras Q2 fix
- Tests 2/3/4 PASS (validan los otros vectores)
- Tienes tiempo de ejecutar Tests 2/3/4 antes 21:05

Si el bottleneck es realmente SSH tail (medición), la métrica subestima el
sistema real. Tendría sentido aplicar (b) de Q2 — medir en el binary —
para tener data más limpia.

## Estado runtime ahora (T+4min Test 1 re-run)

```
liquidator_rs (V4 binary): active, keep-alive client deployed
sidecar Dallas: τ_final=0.364, btc fluyendo OK, journalctl capturando
Test 1 re-run: 5/50 iters completed
Latencias iter 0-4: [TBD primeros muestras incluyen warmup]
Capital: $200 hot200 INTACTO, V4 SHADOW
```

Te paso resultados Test 1 re-run en cuanto complete (~70s más).

---

**Spec firmadas**: r93 + r107-r131
**Próximo**: r131 results Test 1 re-run en cuanto termine
