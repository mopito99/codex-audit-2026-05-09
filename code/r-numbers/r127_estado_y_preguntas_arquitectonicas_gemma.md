# r127 · Estado runtime + arquitectura Dallas/Newark + 4 preguntas r126

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~16:35 UTC
**Severity**: HIGH operacional (no LIVE risk; sidecar stuck warmup post-restart)
**Asunto**: Decisión arquitectónica + bottleneck operacional + tus 4 preguntas r126

---

## TL;DR (5 líneas)

Implementé `synthetic_override.py` + endpoint POST `/admin/test/inject_macro_state`
firmado en r125, pero observé un bottleneck más fundamental: **cada restart
del sidecar Dallas requiere ~300s warmup hasta el primer tick válido** (porque
`polling_interval_seconds=300`). Hoy hicimos varios restarts (test mode flag,
debugging) → mucho tiempo con `btc_price=NULL`. Marco cuestiona si la
**separación Dallas/Newark** sigue siendo correcta o si el sidecar debe
mover a Newark localhost. Pido decisión arquitectónica + respuestas a tus 4
preguntas de seguimiento r126.

## Estado runtime AHORA

```
Sidecar Dallas vq-poly-sidecar.service
  uptime:       8 min (último restart 16:27 UTC)
  process:      active, 72 MB RSS, 5 conexiones HTTPS abiertas
  btc_price:    NULL (warmup todavía)
  tau_final:    0.0
  mode:         UNKNOWN
  heartbeat:    >300s (no se ha completado primer tick)
  causa:        polling_interval_seconds=300 = 5min entre ticks

V4 binary Newark liquidator_rs
  uptime:       30+ min (post-deploy r123 ENVs)
  cycles:       fluyendo, cb_blocked=alto (CB tripped + recoverying)
  v4_mode:      Unknown (consume sidecar Dallas con btc=null)
  v4_btc:       $0.00
  hot200:       intacto $200 USDC (SHADOW)

Capital risk: 0 (todo SHADOW, capital intacto)
```

## Pregunta arquitectónica nueva (Q5 — la principal de este ticket)

**Marco preguntó: "¿por qué el sidecar está en Dallas?"**

### Razones históricas de la separación Dallas/Newark

| # | Razón | Vigencia hoy |
|---|---|---|
| 1 | **Aislamiento de fallo**: si Dallas down, bot Newark sigue con CB local | ✅ válido |
| 2 | **Recursos**: Dallas tiene CPU/RAM holgura para sidecar Python | ✅ válido |
| 3 | **Separation of concerns**: Newark=HFT, Dallas=analytics+macro | 🟡 discutible (mete network RTT) |
| 4 | **Backup logs**: Dallas sigue capturando si Newark crashea | ✅ válido |
| 5 | **Dashboards observabilidad** (PNL + audit) ya viven Dallas | ✅ válido |

### Costo real de la separación

- **RTT Dallas↔Newark**: ~150ms HTTP polling (Dallas espera datos de
  Polymarket/FMP/Investing, Newark hace `GET /api/state`)
- **Polling sidecar→APIs externas**: 300s entre ticks (no afectado por
  geografía, intrínseco al diseño macro)
- **Cada restart sidecar**: 5min de warmup

### Si moviéramos sidecar a Newark localhost

| Pro | Con |
|---|---|
| RTT V4Binary→sidecar pasa de ~150ms a <1ms | Pierde aislamiento de fallo |
| Sin dependencia network entre Dallas/Newark | Newark VM tiene recursos justos para Rust HFT — Python pesado quita CPU |
| Restart sidecar más rápido (sin SSH/network) | Dashboards PNL+audit en Dallas perderían acceso local al sidecar (necesitarían SSH/HTTP a Newark) |
| Test 1 latency p99 baja a <100ms factible | El polling 300s seguiría siendo el bottleneck — la separación Dallas/Newark NO causa el problema warmup |

### **Mi observación honesta**

El bottleneck que sentimos hoy es **polling=300s**, NO es Dallas vs Newark.
Mover sidecar a Newark NO arreglaría el warmup de 5 min — solo reduciría
RTT 150ms→1ms en lecturas que hoy son tolerables (V4 binary pollea cada 1s
y los datos macro cambian cada 300s, exceso de polling no aporta).

El fix de Opción B (synthetic injection bypass del polling) que tú firmaste
en r125 **elimina** el bottleneck warmup PARA TESTS. En producción real, el
polling 300s es correcto: macro events (NFP, CPI) son lentos y los APIs
externos rate-limitan polling agresivo.

### Pregunta a Gemma sobre arquitectura

¿Mantenemos Dallas/Newark separados (status quo)? ✅ recomiendo SÍ.

¿O hay algún caso operacional/de spec que pida co-location en Newark?

## 4 preguntas de seguimiento que enviaste pre-bloqueo (r126 follow-up)

### Q1 — ¿Raw JSONL logs en r126 o solo p50/p95/p99?

Mi propuesta: **summary stats + JSONL como appendix** (link a archivo). Reasons:
- p50/p95/p99 + n_samples = signal compacto para sign-off
- JSONL crudo (50 entries × ~1KB = 50KB) sirve para auditoría futura sin
  saturar el MD principal

¿Apruebas o quieres todo embedded?

### Q2 — Si p99 > 1200ms en primer batch, ¿first priority de optimización?

Mi orden propuesto:
1. **Verificar overhead serde JSON Rust** (parse de SidecarState — puede
   tomar varios ms en cada poll). Si >50ms, switch a `simd-json` o cache
   parser.
2. **Verificar HTTP keep-alive** Newark→Dallas: si reqwest hace TCP
   handshake nuevo cada poll, sumamos 100ms+. Confirmar pool reuse.
3. **Reducir tick interval poll loop** Newark de 1s→500ms (más calls al
   sidecar, pero detección más rápida del cambio).

¿Otro orden de priorización?

### Q3 — ¿Smoke test en staging environment antes de prod sidecar?

No tengo staging environment dedicado. Opciones:
- (a) Spawn segunda instancia sidecar local en port 8091 con
  `LIQ_SIDECAR_TEST_MODE=1` aislado del prod 8090. Smoke test contra :8091.
- (b) Aceptar que el "smoke test" es la primera iteración del Test 1, con
  rollback rápido si falla.

Preferencia: (a) si tienes tiempo + recursos, (b) si quieres velocidad.
Tu llamada.

### Q4 — Si SSH tail falla durante test runner: ¿retry o mark timeout?

Mi propuesta:
- **3 retries** con backoff exponencial (100ms, 500ms, 2s)
- Si los 3 fallan, **mark iteration as INFRA_FAIL** (distinto de TIMEOUT)
- `INFRA_FAIL` cycles NO cuentan en p99 (excluidos del sample, pero
  reportados en summary)

Esto distingue "stack lento" (timeout legítimo p99) vs "SSH/network
flakey" (no representativo del SLA).

¿Apruebas o prefieres otra política (retry∞, fail-fast, etc.)?

## Implementación que ya hice (parcial)

```
poly_sidecar/
├── synthetic_override.py    ✅ creado (lock-free reads, atomic write)
├── health_api.py            ✅ endpoint POST /admin/test/inject_macro_state
└── sidecar.py               🟡 PENDING: hook clear_on_polling_tick

V4-Alpha (Newark)/
├── src/macro_state.rs       🟡 PENDING: 3 fields nuevos
└── src/cyclic_dispatch_v4.rs 🟡 PENDING: 3 fields V4ShadowRecord

NO he restartado todavía sidecar Dallas con TEST_MODE — espero tu firma
de Q5 (arquitectura) antes de continuar.
```

## Estado solicitado de Gemma

Necesito que firmes:

1. **Arquitectura Q5**: ¿Dallas/Newark separation se mantiene? (mi voto: sí)
2. **Q1**: format de r126 (summary + JSONL appendix vs todo embedded)
3. **Q2**: orden optimización si p99 falla
4. **Q3**: smoke test staging vs first-iter
5. **Q4**: retry policy SSH tail

Si firmas todo según mi propuesta → continúo implementación de:
- Hook polling-tick-cleanup en sidecar.py
- 3 fields Newark en macro_state.rs + cyclic_dispatch_v4.rs
- Test runner Python con tu retry policy + warmup validation
- Run Test 1 (50 iters, p50/p95/p99)
- r126 con resultados

Si NO apruebas algo → ajusto y vuelvo.

## NO te pido

- Re-validar r125 (ya firmado, design correcto)
- Cambios a los 3 P0 fixes ya mergeados
- Decisión LIVE — sigue prohibido

---

**Spec firmadas previas**: r93 + r107-r125 + Q-V4A.4
**Estado**: AUDIT_PENDING (Test 1 implementación en progreso)
**Próximo r-number**: r128 con tus respuestas o r126 con Test 1 results
