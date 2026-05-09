VelocityQuant — Follow-ups V4-Alpha (3 preguntas técnicas)
============================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~08:30 UTC
Asunto: 3 de las 4 preguntas que sugeriste como follow-up. Skip la 1
        (polling 10s ya respondida en tu brief). Necesito 2+3+4 antes
        de la implementación de mañana miércoles.

---

## Pregunta 2 — Estructura exacta del test "Graceful Degradation"

Tu spec dice: *"Si el state.json está corrupto o vacío, ¿el bot cae
automáticamente en MODE=CAUTELA y τ=0?"*

Necesito el procedimiento exacto que valides. Mi propuesta inicial:

### Test 1 — state.json vacío
1. `mv state.json state.json.bak`
2. `touch state.json` (file vacío)
3. Verificar logs Rust: `[MACRO_FALLBACK] state.json empty → MODE=CAUTELA τ=0`
4. Verificar dispatch loop sigue corriendo sin crashear
5. Restaurar `mv state.json.bak state.json`
6. Verificar que en próximo polling 10s vuelve a leer correctamente

### Test 2 — JSON corrupto
1. `echo "{ corrupt json [" > state.json`
2. Esperar 15s
3. Verificar log: `[MACRO_FALLBACK] state.json parse error → MODE=CAUTELA τ=0`
4. Verificar dispatch loop estable

### Test 3 — state.json con campos faltantes
1. Escribir `{"heartbeat_ts": 1000000}` (sin tau_final, sin mode)
2. Verificar fallback a τ=0 + MODE=CAUTELA por safety

### Test 4 — heartbeat stale (>10min)
1. Escribir state válido pero con `heartbeat_ts` 15min en el pasado
2. Verificar log `[MACRO_FALLBACK] heartbeat stale → MODE=CAUTELA τ=0`

### Test 5 — file lock concurrencia
1. Mientras Rust lee, Sidecar Python re-escribe (atomic rename)
2. Rust nunca debe leer un JSON parcial (gracias al rename atomic POSIX)

¿Confirmas estos 5 tests como suficientes? ¿Añades alguno?

---

## Pregunta 3 — KPIs comparator V3.5 vs V4-Alpha

Tras viernes (NFP) y lunes (CPI), comparator V3.5 SHADOW vs V4-Alpha
SHADOW. ¿Qué KPIs específicos priorizar para determinar si la modulación
τ está realmente mejorando el bot, o solo añadiendo ruido?

Sugerencia inicial Marco:

### KPIs primarios (decisivos para LIVE)
1. **Quote acceptance rate alrededor de eventos macro** — V4-Alpha debería
   reducir trades en T-30min y aumentar en T+20min
2. **Drawdown máximo** durante eventos NFP/CPI — V4-Alpha debería evitar
   los spikes de pérdida que V3.5 sí toma
3. **Hit rate** post-evento (T+5 a T+30) — V4-Alpha en Capture mode debería
   capturar mejor las ineficiencias del re-pricing

### KPIs secundarios
4. Tiempo total en MODE=CAUTELA / DEFENSIVO vs eventos efectivamente impactantes
5. Falsos positivos: ¿cuántas veces τ activó CAUTELA cuando el evento fue benigno?
6. Falsos negativos: ¿cuántas veces el bot operó normal y el evento fue volátil?
7. Slippage promedio en bundles ejecutados durante macro windows

### Métricas de ruido (descartar τ si...)
- Si τ_final pasa >40% del tiempo en CAUTELA sin reactividad real → ruido
- Si la correlación entre τ y volatilidad real BTC < 0.3 → señal débil

¿Confirmas este set? ¿Cuál es el threshold cuantitativo de "mejora suficiente
para LIVE"? (ej: V4-Alpha drawdown ≤ 70% de V3.5, hit rate ≥ V3.5 + 5%)

---

## Pregunta 4 — GO criteria exactos LIVE EXECUTE Dom 11 22:00 UTC

Si miércoles deploy + jueves estabilización van perfectos, ¿qué criterios
específicos tienen que cumplirse para activar `LIQ_CYCLIC_EXECUTE_LIVE=true`?

Necesito un semáforo cuantitativo, no subjetivo. Sugerencia:

### Hard gates (cualquiera falla → NO LIVE)
- [ ] V4-Alpha SHADOW corrió ≥48h sin un solo crash
- [ ] 0 panics en `journalctl -u v4alpha`
- [ ] Memoria estable (no leak detectable en muestras de 8h)
- [ ] Sidecar 4 fuentes con uptime ≥95% en últimas 48h
- [ ] τ_final OSCILA (no plano permanente, no errático)
- [ ] NFP del viernes: V4-Alpha respondió como esperado
- [ ] CPI del lunes: V4-Alpha respondió como esperado

### Soft gates (señal de cuidado pero no bloqueante)
- [ ] Comparator V4 ≥ V3.5 en hit rate post-macro
- [ ] Comparator V4 drawdown ≤ V3.5
- [ ] Sin ruido excesivo en transiciones de modo (≤10/día)

### Hard cancel (Marco cancela LIVE)
- ¿Qué señal específica te haría decir "NO procede dominador"?
  - ¿τ medio > 0.6 en último día? (sentimiento extremo persistente)
  - ¿Eventos macro con SF > 3σ los días previos?
  - ¿Polymarket APIs caídas >2h en 48h?

¿Cuáles GO/NO-GO criteria firmas tú? Marco se basará en tu lista para
decidir el domingo.

---

## Roadmap actualizado (per tu Opción C)

| Día | Acción |
|---|---|
| Hoy mar 5 | V3.5 + Sidecar siguen calibrando |
| Mié 6 mañana | Implementación Rust + audit |
| Mié 6 tarde | Deploy V4-Alpha SHADOW |
| Jue 7 | Estabilización + verify lectura τ |
| Vie 8 12:30 UTC | NFP — primer test |
| Lun 12 12:30 UTC | CPI — segundo test |
| Dom 11 22:00 UTC | LIVE EXECUTE (target) |

---

Tu llamada en estas 3 define cómo programo el comparator y los criteria
exactos para el domingo.

Gracias.
