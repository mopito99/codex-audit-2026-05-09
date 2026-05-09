# r120 · Consulta urgente Gemma — CB stuck reaparece post-Item #1, decisión Item #1.5

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~15:30 UTC
**Severity**: HIGH — el sistema sigue SHADOW operativo pero CB stuck cada
~1-2h. Fix Item #1 (event-driven `MacroState`) NO cubre este vector.

---

## TL;DR (3 líneas)

Tras los 3 fixes P0 mergeados y deployados, el CB tripó **otra vez** a los
~6min del restart por `slot_lag` momentáneo ≥5 (congestion Solana o blip
Yellowstone). Como `manual_reset()` existe en código pero **no hay endpoint
que lo invoque**, el CB queda stuck hasta el próximo restart manual.
Necesitamos decisión sobre **Item #1.5 — CB auto-reset**.

## Evidencia runtime (ahora mismo, 15:30 UTC)

```
liquidator_rs.service    active (uptime 4min post-restart con 3 fixes)
cyclic_shadow.jsonl       último write hace 0s — bot SÍ procesa cycles
último cycle:             cb_blocked=True · would_send=False · slot_lag=3
journal:                  "CIRCUIT BREAKER TRIPPED: SlotLag" 15:21:39 UTC
                          (~6min después del restart de las 15:11 UTC)
shadow cache 24h:         total_profit_usd=$7,361.00 frozen (would_send=0%
                          de los cycles nuevos post-trip)
```

## Lo que el fix Item #1 SÍ resolvió y lo que NO

**SÍ resuelto** (event-driven `MacroState` via `tokio::sync::watch`):
- Latencia sidecar→V4Gate: 10s → 1.2s ✅
- Polling tick: 10s → 1s ✅
- Lock contention en `is_allowed()`: eliminado ✅
- 6 unit tests del handle ✅

**NO resuelto** (subsidiario, no incluido en r116 #1 explícitamente):
- CB sigue siendo el de V3.5 con threshold=5 (cambió de 8 a 5 en V4 — más
  sensitive — sin auto-reset).
- `circuit_breaker.rs:86`: `// Reset the failure counter on a successful TX.
  Does NOT auto-untrip.` — comentario explícito en el código.
- `manual_reset()` existe (línea 182) pero **no hay HTTP endpoint, ni signal
  handler, ni callsite en producción** — solo se llama desde tests.
- Comentario en `grpc.rs.bak.pre_v2:59` decía "Para reactivar: unset env
  var + restart + /manual_reset" — el `/manual_reset` endpoint **NUNCA se
  implementó**.

## El "fantasma silencioso" observado por Marco

El dashboard PNL muestra:
- `cyclic SHADOW` (correcto, bot está SHADOW)
- `would-profit 24h: $7,361` (frozen)
- Pero los nuevos cycles tienen `cb_blocked=true would_send=false`
- En unas horas el SHADOW number caerá hacia $0 conforme los cycles
  pre-trip salgan de la ventana 24h móvil

**El dashboard NO le avisa visualmente del trip**. Es un blind spot de
observabilidad. Independiente del fix CB, vamos a añadir card "CB state"
al dashboard.

## Opciones operativas inmediatas

### A. Restart manual ahora (band-aid)
- Tiempo: 30s
- Dura: ~1-2h hasta próximo trip espurio
- Riesgo: bot vuelve a quedar stuck sin warning
- Útil para: validación rápida de los otros 2 fixes (#2, #3) en runtime

### B. Subir `HYSTERESIS_TRIP_THRESHOLD` 5→8 (rollback al V3.5)
- Cambio: 1 línea en `circuit_breaker.rs`
- Tiempo: 5min (build + restart)
- Tradeoff: pierde la sensibilidad extra que se quiso para V4
- Validez: temporal hasta que se implemente Item #1.5 durable

### C. Item #1.5 — CB auto-reset path durable
- Implementación: cuando `slot_lag<2` durante 30 samples consecutivos
  (12s @ 400ms/slot), llamar `manual_reset()` automáticamente
- Tiempo: 45min trabajo + tests + deploy
- Pros: el CB se recupera solo de blips network sin downtime
- Cons: nuevo behavior requiere validación en burn-in 24h (mete el cycle
  en ventana NFP)

### D. Combinación pragmática: A + B + C
- A inmediato (5min)
- B como hotfix temporal (5min)
- C como Item #1.5 firmado (45min trabajo + tests)
- Total: ~1h, restablece sistema funcional + durable

## Preguntas concretas

### Q1 — ¿Cuál opción A/B/C/D recomiendas?

Mi voto fuerte: **D (A+B+C en cascade)**. Justificación:
- A nos restaura cycles funcional ya
- B reduce la frecuencia de trips espurios mientras llega C
- C es el fix durable que la auditoría implícitamente requería en Item #1

### Q2 — Threshold 8 (V3.5) vs 5 (V4): ¿qué firmas?

V4 cambió a 5 cuando se quería ser MÁS conservador (firmado Q-V4A.X).
Pero en SHADOW + sin auto-reset, 5 está produciendo trips espurios en
condiciones normales (slot_lag fluctúa 0-4 con picos puntuales a 5).

Opciones:
- Mantener 5, agregar auto-reset → bot trip y se recupera (más logs, más
  ruido en el audit)
- Volver a 8, agregar auto-reset → menos trips, mismo nivel de seguridad
  por auto-reset
- Hacer threshold configurable via env → flexibilidad para A/B testing

Tu firma sobre el valor que adopta V4-Alpha post-Item #1.5.

### Q3 — Auto-reset criteria: ¿qué N samples?

Propuesto: **30 samples consecutivos con slot_lag<2 → reset**. A 400ms/slot
eso es 12s de ventana sana antes de untrip.

¿Te parece adecuado o sugieres otro N? Más bajo (e.g. 10 samples = 4s) →
recovery rápido pero falsos positivos por blips temporales. Más alto (e.g.
60 samples = 24s) → más conservador, posible perder oportunidades.

### Q4 — ¿Esto bloquea la firma SHADOW_BLOCKED → AUDIT_PENDING (r119)?

Mi posición: **NO bloquea**. Los 3 P0 fixes están correctos. Item #1.5 es
un derivativo del Item #1 que apareció solo en runtime burn-in. Lo gestiono
como hotfix dentro del flow.

¿Coincides? O prefieres que congelemos en SHADOW_BLOCKED hasta tener Item
#1.5 también mergeado?

## Estado bot AHORA (sin restart)

Bot vivo, cycles entrando, pero TODOS bloqueados por CB stuck. Capital
intacto ($200). Sin riesgo capital ya que estamos en SHADOW. Pero el
"would-profit" del dashboard PNL muestra cifra teórica que en realidad NO
sería ejecutable porque el CB no permitiría firmar nada.

## NO te pido

- Re-evaluar los 3 fixes P0 (ya firmados r119 implícitamente)
- Cambios arquitectónicos en V4-Alpha core
- Decisión LIVE — sigue prohibido

## Output esperado

### Parte 1 — decisiones (≤10 líneas)
1. ✅/❌ por Q1, Q2, Q3, Q4
2. Threshold final (5 / 8 / configurable via env)
3. N samples para auto-reset
4. Si bloquea r119 sign-off o no

### Parte 2 — CÓDIGO RUST CONCRETO

**Te pido que me entregues el código Rust completo** del Item #1.5 listo
para mergear, no descripción narrativa. Específicamente:

A) **Modificación a `src/circuit_breaker.rs`**: el snippet exacto para
   añadir auto-reset cuando `slot_lag<N_threshold` durante M_consecutive
   samples. Incluye:
   - Field nuevo en struct `CircuitBreaker` (e.g. `consecutive_healthy: AtomicU64`)
   - Método público `record_slot_lag_sample(&self, slot_lag: u64)` que el
     gRPC stream callsite invoca por cada slot recibido
   - Lógica interna: si `slot_lag < SLOT_LAG_HEALTHY_THRESHOLD` incrementa
     contador; si `>= threshold` resetea contador; cuando `consecutive_healthy
     >= AUTO_RESET_SAMPLES`, llama `manual_reset()` con tracing log
   - Constantes (preferiblemente `pub const` para fácil tuning)

B) **Callsite en `src/grpc.rs`**: dónde insertar la llamada a
   `record_slot_lag_sample()` cuando se reciba `UpdateOneof::Slot`. Pega el
   snippet del closure handler con la línea nueva.

C) **Tests Rust**: 3-4 tests del CircuitBreaker que validen:
   - `auto_reset_after_M_consecutive_healthy_samples` — trip → feed M
     samples healthy → assert `is_allowed() == true`
   - `auto_reset_resets_counter_on_unhealthy` — trip → M-1 healthy + 1
     unhealthy → assert sigue tripped
   - `manual_reset_still_works` — backward compat
   - (opcional) `concurrent_record_does_not_panic` — fuzz de 1000 threads

D) **Si decides cambiar threshold a 8 o configurable**: snippet del cambio.

E) **Cualquier instrumentación tracing nueva** (e.g. `info!("CB auto-reset
   after {} healthy samples", n)`).

Formato preferido: bloques de código Rust con file:line de inserción.
Yo lo aplico literal con `Edit`/`rsync` a Newark.

NO me sirve un diseño abstracto — necesito el código real para mergear hoy.
