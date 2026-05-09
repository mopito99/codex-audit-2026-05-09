# ALERTA TÉCNICA · Gemma 4 · CB blocked permanente + Yellowstone zombie

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~12:38 UTC
**Severity**: CRITICAL — el bot V4-Alpha LIVE no firma TX. Capital intacto pero
sistema NO funcional.

---

## TL;DR (≤6 líneas)

Hoy activamos LIVE (`LIQ_CYCLIC_EXECUTE_LIVE=true` en `.env` Newark) tras swap
del binario V3.5 → V4-Alpha (compilado May 6 10:34 UTC). El bot **NO ha firmado
ninguna TX en 22 min de LIVE**. Diagnóstico: el **Circuit Breaker está tripped
al 100% desde el arranque** porque el stream Yellowstone gRPC entrega
`updates=0` durante TODA la sesión. Sin slots fluyendo, el CB no se resetea.
Esto **YA pasaba con V3.5** anterior — los $7,344 SHADOW would-profit en
24h eran 100% teóricos: el bot nunca pudo ejecutar.

## Datos forenses concretos

### Estado runtime

```
Fecha: 2026-05-06 12:38 UTC
Bot:   liquidator_rs.service (V4-Alpha binary, PID 3042586, uptime 22min)
Modo:  LIQ_CYCLIC_EXECUTE_LIVE=true · LIQ_KAMINO_DISABLE=true
RPC:   yellowstone-solana-mainnet.core.chainstack.com:443 (5-stream plan, 2/5 en uso)
hot200 (4V6f...sZTy): 0.05 SOL + $200 USDC = sin movimiento desde activación LIVE
```

### Cycles SHADOW últimos 1000 (cyclic_shadow.jsonl)

```
total cycles:           1000
would_send=true:           0 (0.0%)
cb_blocked:             1000 (100.0%)        ← AQUÍ ESTÁ EL PROBLEMA
depeg_blocked:             0
is_outlier:                0
stale_due_to_missing_ticks: 0
net_profit_usd: min=$0.0008  median=$0.0136  max=$0.0388
```

Profit válido detectado en cycles, but `cb_blocked=true` siempre →
`would_send=false` siempre → 0 TX firmadas.

### Stream stats Yellowstone gRPC

```
Total stream stats logs últimas 2h:    46,397
Con updates>0:                              0
Con updates=0:                         46,399 (100%)
```

**Cero updates en 2 horas.** El stream está conectado (`connected` log + ESTAB
TCP a 208.115.193.163:443), suscrito (`subscribed (Kamino owner + CLMM pools +
Pyth oracles multi-filter R62 A4) kamino=true clmm_pools=2 pyth_oracles=3`),
pero NO entrega `UpdateOneof` messages.

### CB log timeline

```
T+0s    : daemon start, gRPC connected, subscribed multi-filter
T+8s    : "ERROR liquidator_rs::circuit_breaker: CIRCUIT BREAKER TRIPPED: SlotLag"
T+10s+  : "WARN circuit_breaker: slot lag increasing (2 slots)" repeating
        : "WARN circuit_breaker: slot lag increasing (3 slots)"
        : "WARN circuit_breaker: slot lag increasing (4 slots)"
T+22min : CB sigue tripped. Sin reset jamás. updates=0 sostenido.
```

### Diff V4 vs V3.5 relevante

V4-Alpha cambió en `src/circuit_breaker.rs`:
```
-const HYSTERESIS_TRIP_THRESHOLD: u64 = 8;   // V3.5
+const HYSTERESIS_TRIP_THRESHOLD: u64 = 5;   // V4 — más conservador
```

V4 añadió en `src/grpc.rs`:
```
+ // V4-Alpha — Zombie watchdog (Gemma Q-V4A.4 approved spec)
+ // Tracks last_quote_ms and aborts the stream if no UpdateOneof arrives in
+ // LIQ_ZOMBIE_TIMEOUT_MS (default 30s). The error message includes "zombie"
+ // so is_transient() catches it and the run() wrapper triggers reconnect 2s.
```

**Pero**: en logs de 22 min, **0 menciones de "zombie", "watchdog", "reconnect"**.
El watchdog **NO disparó**. Si `LIQ_ZOMBIE_TIMEOUT_MS=30s` debería haber
disparado a los 30s del primer update missing.

## Hipótesis técnicas (que necesito que valides o refutes)

### H1 — Zombie watchdog buggy: bug de inicialización
El watchdog mide `last_quote_ms` desde el primer `UpdateOneof`. Si **nunca**
llega un primer update, `last_quote_ms` queda `None` y la condición
`now - last_quote_ms > timeout` nunca se evalúa → no aborta → no reconecta.

Implicación: si el subscribe ha entregado 0 updates desde el principio, el
watchdog está roto by design.

**Evidencia a favor**: `updates=0` en 100% del tiempo. Cero "zombie" en logs.

**Test**: leer `src/grpc.rs` y revisar la inicialización de `last_quote_ms` y
la condición de trigger. ¿Hay un `unwrap_or(now)` o se queda `None`?

### H2 — Subscribe filter no matchea ningún account
Los 2 CLMM pools (Raydium SOL/USDC + Orca SOL/USDC) y 3 Pyth oracles
**deberían** generar updates frecuentes (cada slot ~400ms). Si `updates=0`,
el filter no matchea on-chain.

Posibilidades:
- El `subscribe_with_request` envía pubkeys con encoding base58 cuando el server
  espera base64 o viceversa
- El plan Chainstack 5-stream que reinstaló Marco hoy generó nuevas keys de
  acceso, los pubkeys filter quedaron desconectados de la nueva subscription
- Algún feature del plan Chainstack distingue "1-stream" de "5-stream" en cuanto
  a qué eventos puedes suscribir (account updates vs slot meta only?)

**Test**: comparar `SubscribeRequest` exacto que el binario V4 envía vs el que
V3.5 enviaba antes. Ver si pools.toml addresses están bien encoded.

### H3 — CB no tiene timeout / auto-reset
Si tripeó por SlotLag al T+8s, debería resetear cuando el lag baja. Pero
`updates=0` significa que **nunca hay slot lag para medir** — el CB se queda
con la última métrica conocida (lag alta) y stuck.

**Test**: leer `circuit_breaker.rs`, función `tick()` o `update_slot()`.
¿Cómo se llama el reset path? ¿Depende de recibir slots nuevos? Si sí, es
inconsistente con el zombie watchdog.

### H4 — `LIQ_ZOMBIE_TIMEOUT_MS` no está en .env
Quizás la variable que controla el timeout no se setea en `.env`. El default
hardcoded podría ser muy alto (5min, 1h?) o cero (disabled).

**Test**: `grep LIQ_ZOMBIE_TIMEOUT_MS /home/ubuntu/liquidator_rs/.env` y
comparar con `unwrap_or(30000)` en código.

### H5 — Plan Chainstack post-reinstall entrega updates "limitados"
Hoy 11:05 UTC Marco hizo Uninstall del Yellowstone 1-stream + Install del
5-stream. Posible que la nueva subscription esté en un estado raro server-side
(quotas no aplicadas, filtros no propagados).

**Test**: comparar updates en otros binarios que usen el mismo endpoint
(`solana-executor-rs` running concurrent, 1/5 streams). ¿Tiene updates>0?

## Preguntas concretas a Gemma

1. **¿Es H1 (watchdog buggy) consistente con la implementación que firmaste
   en Q-V4A.4?** ¿Esperabas que el watchdog cubriera el caso "nunca llegó
   primer update"?

2. **¿Cuál es el orden correcto para diagnosticar?**
   a) Primero rollback al binario V3.5 (threshold=8) y ver si recupera updates
   b) Primero investigar si solana-executor-rs tiene updates>0 en su stream
      separado (descartaría plan Chainstack como causa)
   c) Primero leer el código grpc.rs V4 con calma y validar H1+H2

3. **Si confirmamos que el sistema nunca firmó una TX en su historia**,
   ¿el plan NFP Vie 8 es viable? ¿O hay que pausar TODO hasta arreglar el
   stream?

4. **¿Conoces algún caso de Chainstack Yellowstone donde el subscribe parece
   OK pero entrega 0 updates por config silenciosa server-side?**

5. **Re-test de capital**: ¿está OK dejar `LIQ_CYCLIC_EXECUTE_LIVE=true`
   mientras debugeamos? Si el CB se resetea de pronto sin que estemos viendo,
   firmaría TX. ¿O revertimos a SHADOW por seguridad mientras investigamos?

## Acciones ya tomadas hoy (relevantes)

- 10:34 UTC: rebuild release binario V4-Alpha (`liquidator_rs` 14.6 MB, 129/129 tests pass)
- 10:36 UTC: backup unit + binario V3.5 LIVE (rollback ready)
- 10:40 UTC: swap unit V3.5 → V4 binary, restart — falló por Chainstack 1-stream
- 10:58 UTC: rollback V3.5 + stop solana-executor-rs (sacrificio para liberar slot)
- 11:05 UTC: Marco uninstall add-on Yellowstone 1-stream + install 5-stream
- 11:07 UTC: V3.5 LIVE up + solana-executor up (2/5 streams)
- 11:10 UTC: re-swap V4 binary, restart, OK
- 12:14 UTC: ADP capture timer disparó (sin issue)
- 12:16 UTC: descomentar+set `LIQ_CYCLIC_EXECUTE_LIVE=true`, restart
- 12:16:08 - 12:38 UTC: bot LIVE, **0 TX firmadas**, CB tripped 100%, updates=0
- hot200 sin movimiento ($200 USDC + 0.05 SOL intactos)

## Output esperado de ti, Gemma

1. **Validación o refutación** de H1-H5
2. **Orden de diagnóstico** recomendado
3. **Decisión binaria**: ¿revertir a SHADOW ya, o seguir con LIVE mientras debuggeamos?
4. **Si conoces el bug**: file:línea concreto del fix

NO necesito narrativa larga. Tabla de hallazgos con severidad + acción concreta.

---

**Spec firmadas previas**: r93 + r107 + r108 + r109 + r110 + r111 + Q-V4A.4 (zombie watchdog)
**Auditoría externa pendiente**: bundle 326 KB en https://inicio.velocityquant.io/poly/audit/bundle.md
