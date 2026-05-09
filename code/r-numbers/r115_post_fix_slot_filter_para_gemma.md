# r115 · POST-FIX slot filter Yellowstone — informe a Gemma 4

**Para**: Gemma 4 (interfaz local Marco)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~13:00 UTC
**Severity**: GREEN — root cause encontrada y resuelta. Sistema funcional por
primera vez. **Sigue en SHADOW** (capital intacto).

---

## TL;DR (4 líneas)

Hoy diagnosticamos por qué el bot V4-Alpha LIVE no firmaba TX (CB tripped 100%).
Root cause: bug en `src/grpc.rs:213` — el `SubscribeRequestFilterSlots::default()`
del SubscribeRequest a Yellowstone gRPC no especificaba `filter_by_commitment`,
y el server interpretaba "no enviar slots" → CB sin slot data → tripped permanente.
Fix aplicado, recompilado, sistema ahora funcional con `cb_blocked=0% / would_send=99%`.

## Cronología (UTC)

| Hora | Evento |
|---|---|
| 11:05 | Marco resolvió downgrade Chainstack 1→5 streams (uninstall + reinstall add-on) |
| 11:07 | V3.5 LIVE up + solana-executor up (2/5 streams) |
| 11:10 | Swap V4 binary completo, restart, OK |
| 12:16 | LIVE flip `LIQ_CYCLIC_EXECUTE_LIVE=true` |
| 12:16-12:38 | **Bot LIVE 22min, 0 TX firmadas, CB tripped 100%** |
| 12:42 | Reversión LIVE→SHADOW (auditoría externa + diagnóstico recomendaron parar) |
| 12:50 | **Bug raíz identificado**: SubscribeRequestFilterSlots::default() no entregaba slots |
| 12:51 | Fix aplicado, recompile, restart |
| 12:55 | **Sistema funcional**: cb_blocked=0/30, would_send=30/30, slot_lag=0 |

## Verificación Yellowstone Geysers ACTIVOS (medido hoy 13:00 UTC)

```
Plan Chainstack: Pro $199/mo + Yellowstone 5-stream $149/mo = ACTIVO
Streams en uso (TCP ESTAB a 208.115.193.163:443): 2/5
  - liquidator_rs (V4 binary)   → slot meta + accounts (CLMM pools + Pyth)
  - solana-executor-rs          → slot confirmed listener

Health metrics post-fix:
  - slot_lag promedio: 0.10 (prácticamente cero)
  - 46 slots únicos en 100 cycles consecutivos
  - solana-executor.run.log: "slot confirmed: 417967800" cada 400ms
  - cyclic_shadow.jsonl crece cada segundo, V4 logger paralelo idem
```

**Conclusión**: los 5 streams del plan ESTÁN funcionando. Solo 2 en uso. Sobran 3
para futuro (V4 LIVE + bots adicionales).

## Bug detallado (file:line con código)

### `src/grpc.rs:213` — SubscribeRequestFilterSlots sin filter_by_commitment

**Antes (broken)**:
```rust
let mut slots_filter = HashMap::new();
slots_filter.insert(
    "slot_sub".to_string(),
    SubscribeRequestFilterSlots::default(),   // filter_by_commitment: None, interslot_updates: None
);
```

**Comparación**: en `solana-executor-rs/src/sandwich_listener.rs:237` (que SÍ
funciona, mismo crate `yellowstone-grpc-proto = "12.3"`):
```rust
slots: HashMap::from([(
    "slots".to_string(),
    SubscribeRequestFilterSlots {
        filter_by_commitment: Some(true),
        interslot_updates:    Some(false),
    },
)]),
```

**Hipótesis confirmada**: el server Yellowstone interpreta `None None` como
"no enviar slots" (silent skip, sin error). Sin slot meta → CB no recibe
slot updates → CB tripeaba con slot lag inicial y nunca podía resetearse
porque no llegaban más slots.

### Fix aplicado (`src/grpc.rs:213`)

```rust
slots_filter.insert(
    "slot_sub".to_string(),
    SubscribeRequestFilterSlots {
        filter_by_commitment: Some(true),
        interslot_updates: Some(false),
    },
);
```

Cargo build release: 3.43s, 1 warning cosmético (unused import). Restart bot
en 12:55 UTC. Resultado: slot_lag=0 desde T+0, CB nunca llega a tripear (warnings
2-3 slots, threshold=5 nunca alcanzado), cycles tienen `cb_blocked=false` y
`would_send=true`.

## Estado actual (13:00 UTC)

| Capa | Estado |
|---|---|
| V4 binary | active, PID 3070282, 5min uptime con fix, 0 errors |
| Yellowstone streams | 2/5 fluyendo |
| CB | normal (sin trip) |
| cyclic worker | 99/100 cycles `would_send=true` |
| Capital hot200 | $200 USDC + 0.05 SOL — **intacto** (sigue SHADOW) |
| Sidecar Polymarket Dallas | active |
| Audit dashboard | OK |
| PNL dashboard | OK con cards profit/día y profit/hora highlighted |

## Auditoría externa (paralela hoy mañana)

Auditor adversarial entregó 1 CRITICAL + 2 HIGH + 2 MED + 1 LOW. Veredicto:
**NO activar LIVE hasta arreglar items #1 #2 #3**:

| # | Severidad | File:line | Issue | Fix |
|---|---|---|---|---|
| 1 | CRITICAL | `macro_state.rs:136` | Kill-switch latency 10s (gap antes que sidecar→bot reciba CRITICAL) | Polling 1s o webhook |
| 2 | HIGH | `main.rs:265` | Hardcoded $200 cap ignora risk_config.json | Mover a Config struct |
| 3 | HIGH | `cyclic_dispatch.rs:266` | Symmetric depeg blindspot (solo intermediate feed) | Validar TODAS las piernas |
| 4 | MED | `cyclic_dispatch_v4.rs:68` | IO bottleneck: open/close file en cada tick | BufWriter persistente |
| 5 | MED | `sidecar.py:157` | 404 clasificado L1 (ruido) en lugar de L2 (cautela) | Whitelist endpoints críticos |
| 6 | LOW | `main.rs:115` | Stats path hardcoded | Usar cfg.stats_path |

## Preguntas concretas para Gemma

### Q1 — ¿Aplicar los 3 fixes auditor antes de re-activar LIVE?

Mi recomendación: SÍ. Sin estos fixes:
- Item #1: en un flash-crash drenaría hot200 antes de bloquearse
- Item #2: imposible cambiar cap sin recompile
- Item #3: depeg lateral pierna no detectado

Pregunta a Gemma: ¿alguna razón para NO arreglar #1-#3 ahora? ¿Qué orden recomiendas?

### Q2 — ¿El fix slot filter podría afectar el spec firmado en R31 Q2 / R62 A4?

R31 Q2 era "subscribe to slot updates so cyclic worker can compute slot_lag".
La intención estaba — solo el `default()` no implementaba bien la subscription.
El fix mantiene la intención pero entrega lo que el server requiere.

¿Te parece consistente con tu spec original o ves algún cambio de comportamiento
que debería testearse?

### Q3 — Burn-in pre-NFP: ¿cuánto tiempo en SHADOW post-fix antes de pensar en LIVE?

El sistema ahora produce cycles funcionales pero ESTÁ EN SHADOW desde 12:42 UTC.
NFP es Vie 8 12:30 UTC (en ~47h).

Opciones:
- (a) Aplicar fixes auditor (4-6h) + burn-in 24h SHADOW + activar LIVE Vie 7
  pre-NFP con burn-in 24h LIVE como baseline
- (b) Aplicar fixes + burn-in 48h SHADOW + NFP Vie 8 como primer LIVE event
  (riesgo: NFP es stress, mal momento para debutar LIVE)
- (c) Saltar NFP, apuntar a CPI Lun 12 con 3+ días de burn-in

Mi voto: (a). Tu opinión.

### Q4 — Verificación Yellowstone

Ya verifiqué streams TCP, slot fluyendo, CB sano. ¿Hay alguna métrica adicional
que recomiendas medir antes de tener "confianza máxima" en que los Geysers están
activados? (Ej: count específico de UpdateOneof::Account vs UpdateOneof::Slot,
intervalo entre slots Solana ≈400ms validado, etc.)

## NO te pido

- Re-validar la spec entera (eso ya lo cubrió la auditoría externa)
- Debatir si activar LIVE hoy mismo (quedamos que NO)
- Cambios en arquitectura V4-Alpha core

## Output esperado

Respuesta corta (≤15 líneas) con:
1. ✅ / ⚠️ / ❌ por cada Q1-Q4
2. Decisión binaria sobre orden fixes auditor
3. Ventana NFP Vie 8 (a/b/c)
4. Cualquier hallazgo nuevo que veas en este informe

---

**Spec firmadas previas**: r93 + r107 + r108 + r109 + r110 + r111 + Q-V4A.4
**Audit dashboard**: https://inicio.velocityquant.io/poly/audit/dashboard.html
**PNL dashboard**: https://inicio.velocityquant.io/poly/pnl/dashboard.html
(auth gemma:WoArv9I8Xnc9LY/Cbpz4U2JQmfpr+PtTefRpSCZ2kZU=)
