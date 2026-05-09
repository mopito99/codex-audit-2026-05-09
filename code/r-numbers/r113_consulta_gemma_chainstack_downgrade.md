# Consulta urgente Gemma — Chainstack Yellowstone downgrade silencioso

**Para**: Gemma 4 (interfaz local Marco)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~11:00 UTC
**Severity**: Alta — V3.5 LIVE Newark estuvo caído ~15 min hoy, restaurado pero con sacrificio operativo

---

## TL;DR

El add-on Yellowstone gRPC en Chainstack que pagamos como **5-stream** se ha bajado silenciosamente a **1-stream**. Esto rompió la coexistencia de los dos bots Newark que comparten el endpoint. Quiero tu opinión sobre tres cosas concretas (al final del documento).

## Cronología de hoy (UTC)

| Hora | Evento |
|---|---|
| ~22:35 (anteayer May 5) | Build SHADOW V4-Alpha observer (debug). Activado vía systemd `vq-v4-shadow-observer.service`. Funcionó OK 11h. |
| 10:14 | Build release V4 (`v4_shadow_observer` 7.5 MB) + hot-swap unit debug→release. Validado 60s sin error. |
| 10:34 | Build release del binario completo V4-Alpha (`liquidator_rs` 14.6 MB) + 129/129 cargo tests passed. |
| 10:36 | Backup unit V3.5 + binario V3.5 (May 5) preemptive. |
| 10:40:31 | Stop V3.5 LIVE para hot-swap a binario V4. |
| 10:40:42 | V4 binary arranca pero **falla** en `subscribe_with_request`: `gRPC RESOURCE_EXHAUSTED — Concurrent Yellowstone Geyser stream limit reached`. |
| 10:40:49 | Rollback unit V3.5. V3.5 reintenta arrancar — **falla con el MISMO error**, aunque el binario es el viejo bueno. |
| 10:42:37 | 2º intento V3.5 fail. |
| 10:45:25 | 3º intento V3.5 fail. |
| 10:47:17 | Stop V3.5 + 600s wait (hipótesis: TTL fantasmas Chainstack). |
| 10:57:35 | Reintento auto V3.5 — **falla otra vez**. Confirmado: NO es TTL fantasma. |
| Marco abre dashboard Chainstack | El add-on Yellowstone gRPC Geyser Plugin en Node ND-473-445-892 muestra plan único disponible: **"1 Stream — $49/month"**. No hay opción 5-stream visible en su tier Pro. |
| 10:58:58 | Stop V3.5 + stop `solana-executor-rs` (paper trading, confirmed sin send_transaction). |
| 10:59:09 | V3.5 LIVE arrancado. Yellowstone subscribe **OK**, telemetry fluyendo. |

## Estado actual

- ✅ V3.5 LIVE `liquidator_rs` activo y suscrito a Yellowstone
- ⏸️ `solana-executor-rs` (paper MEV/arb bot) parado para liberar el único slot
- ✅ Sidecar Polymarket Dallas (τ macro) intacto
- ✅ V4 SHADOW observer Newark (`vq-v4-shadow-observer`) activo en release binary
- ✅ Audit dashboard `/poly/audit/dashboard.html` operacional con queries 7/7 OK
- ❌ V4 swap del binario LIVE bloqueado hasta que Chainstack restaure 5-stream

## Datos billing

- Plan general: **Pro $199/mo** (Active)
- Add-on Yellowstone: **1 Stream $49/mo** (Active hoy — pero antes era 5-stream)
- Invoices del periodo en que tuvimos 5-stream:
  - `9OZYSTNN-0004`
  - `9OZYSTNN-0007`
- Edin (Chainstack support) configuró el 5-stream manualmente la primera vez. Algo lo revirtió a 1-stream sin notificarnos.

## Por qué importa para NFP Vie 8

El plan operacional para el NFP del viernes 12:30 UTC requería:
- V3.5 LIVE ejecutando trades
- V4-Alpha binary corriendo en paralelo (SHADOW++ logger de disagreements V3 vs V4)
- V4 SHADOW observer standalone capturando τ macro

Con 1 stream Yellowstone, no podemos correr V3.5 + V4 binary completo simultáneamente. **La opción A del plan SHADOW++ está bloqueada** hasta restaurar streams.

Workaround actual: el V4 SHADOW observer standalone (`v4_shadow_observer` binary) NO necesita Yellowstone — solo polls HTTPS al sidecar Dallas. Sigue corriendo y captura `cyclic_shadow_v4.jsonl` con τ y mode. Eso es suficiente para forensic post-NFP, pero **no captura disagreements V3 vs V4 en hot path** (eso requiere el binario completo V4 en producción).

## Acciones ya tomadas

1. Ticket support Chainstack redactado en `chainstack_support_ticket_5stream_downgrade.md` (listo para pegar en https://support.chainstack.com).
2. Backup unit V3.5 + binario preservados.
3. V4 binary release compilado, esperando restauración del slot.

## Preguntas concretas para ti, Gemma

### Q1 — Workaround técnico inmediato

Sin esperar a Chainstack support, ¿hay alguna estrategia técnica que se te ocurra para correr V3.5 + V4 binary completo en paralelo con un solo stream Yellowstone? Posibilidades que consideré pero descarto:

- **gRPC stream multiplexing**: Yellowstone Geyser cuenta cada `.subscribe()` como 1 stream lógico, aunque vayan sobre la misma TCP/HTTP2 connection. Confirmado que Chainstack rechaza el segundo subscribe en el mismo proceso o entre procesos.
- **Compartir el stream entre procesos**: el primer process abre el subscribe y reenvía updates por IPC al segundo. Funcionalmente posible pero requiere refactor del binario. ¿Vale la pena para 2-3 días hasta el NFP?
- **Modo "shared subscribe"**: Geyser plugins de Solana tienen multi-subscriber en algunos forks. ¿Sabes de algún cliente que lo soporte sobre Chainstack?

### Q2 — Migrar de proveedor Yellowstone

Alternativas conocidas de Yellowstone gRPC en el ecosistema Solana:
- **Helius** (`mainnet.helius-rpc.com`) — tienen gRPC Geyser pero con sus propios términos.
- **Triton One** — Yellowstone-compatible, pricing variable.
- **Shyft / Solana Labs / Jito Network** — algunos exponen Geyser-compatible.

Para el contexto específico de bots de liquidación + MEV (latencia <50ms p50, suscripción a `BlockMeta` + `Transaction` filtrado, sub-millisecond push), ¿tienes preferencia?

¿Migrar antes del NFP del viernes (~50h) es realista, o más arriesgado que esperar a Chainstack? El binario V3.5 abstrae el endpoint vía `LIQ_GRPC_URL`, así que un cambio sería .env + reinicio si el proveedor mantiene la misma protobuf API.

### Q3 — Estrategia con Chainstack support

Vimos en su UI que el plan Pro $199/mo solo ofrece "1 Stream $49/mo" como add-on visible. El 5-stream que Edin configuró era custom. ¿Crees que:

- (a) Lo que pagamos en `9OZYSTNN-0004` y `0007` cubría el 5-stream y un renewal automático lo bajó porque la opción 5-stream no existe normalmente para tier Pro
- (b) Edin lo configuró como favor temporal, los $149 que vimos en invoice eran del mes que él aplicó manualmente, y al renewal volvió al default
- (c) Hubo un bug o cambio de pricing model

¿Qué pediríamos en el ticket: restauración + reembolso (a/c) o renegociación con upgrade general (b)?

## Lo que NO te estoy preguntando

- NO estoy preguntando si seguir con el plan NFP Vie 8 — eso ya está firmado en r93/r107/r108/r109/r110/r111. La degradación no rompe el audit del NFP, solo bloquea la rama V4-binary-en-LIVE.
- NO estoy preguntando si pivotar arquitectura — overkill para 50h.

## Mi recomendación pre-Gemma (para contraste)

1. **Hoy mismo**: pegar el ticket support Chainstack (ya redactado) y esperar 2-6h respuesta de Edin.
2. **En paralelo**: monitorear V3.5 LIVE 30min, confirmar trades fluyendo.
3. **Si Chainstack no responde antes de Vie 8 06:00 UTC**: arrancar el NFP con setup actual (V3.5 LIVE + V4 SHADOW observer standalone + sidecar Dallas + audit dashboard). Forensic post-NFP cubre 90%.
4. **Si NFP es el evento OK**: post-NFP retomamos plan V4-binary-LIVE cuando Chainstack restaure 5-stream.

¿Acuerdo? ¿Cambiarías la priorización?

---

**Spec firmada**: r93 + r107 + r108 + r109 + r110 + r111
**Bloqueos pendientes**: Chainstack downgrade (administrative, no técnico)
