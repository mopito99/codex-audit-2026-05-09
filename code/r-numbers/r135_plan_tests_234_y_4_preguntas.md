# r135 · Plan Tests 2/3/4 + 4 preguntas Gemma

**Para**: Gemma
**De**: Marco (vía Claude)
**Fecha**: 2026-05-06 ~17:50 UTC
**Status**: Test 1 Conditional PASS firmada D. Procediendo Tests 2/3/4.

---

## Q1 — Parámetros + success criteria Tests 2/3/4

### Test 2 — `max_debt_cap_usd` configurable

| Sub-test | Procedimiento | Pass criteria |
|---|---|---|
| 2a unit | `cargo test --release --lib` config tests | 145/145 pass ✅ ya validado |
| 2b deploy | Edit `.env`: `LIQ_MAX_DEBT_CAP_USD=50` + restart liquidator_rs | log "CircuitBreaker init... max_debt_cap_usd=50" + stats.json shows 50 |
| 2c restore | Restore `.env` default + restart | log shows max_debt_cap_usd=200 |

NO mock de liquidación posible — Kamino disabled (`LIQ_KAMINO_DISABLE=true`).
Validación = config-driven, sin requests reales.

### Test 3 — Symmetric depeg multi-leg

| Sub-test | Procedimiento | Pass criteria |
|---|---|---|
| 3a unit t1-t6 | `cargo test depeg_tests` | 6/6 pass ✅ ya validado |
| 3b runtime | Verify cycles activos con `depeg_blocked=false` (mercado normal) | últimas 100 cycles cyclic_shadow.jsonl sin depeg blocks espurios |
| 3c synthetic Pyth | Diferido — requiere infra Pyth fake feed que no existe | acordamos: cobertura suficiente con 3a unit + 3b runtime |

### Test 4 — Stale sidecar + auto-reset CB

| Sub-test | Procedimiento | Pass criteria |
|---|---|---|
| 4a stale detect | Stop sidecar Dallas 60s, verify V4 entra mode=Stale | logs V4 muestran "is_stale=true" o mode=BlockOnStale |
| 4b auto-recover | Restart sidecar, verify V4 vuelve a Normal | mode=Normal en ≤30s post sidecar OK |
| 4c CB auto-reset | Inyectar slot_lag fake high → CB trip → verify auto-reset 30 samples healthy | journal: TRIPPED + AUTO-RESET dentro de 15s post recovery |

## Q2 — Refactor btc_feed.py y gemma_oracle.py: prioridad pre-deploy?

`btc_feed.py` ya está limpio post-r129 revert (residuos r118 §Q2 removidos
literalmente). Funcionalidad: 3-source consensus (Coinbase/Kraken/Pyth) con
weighted_median + outlier reject. **NO veo refactor pendiente**.

`gemma_oracle.py` — **no existe** en `/home/administrator/poly_sidecar/`.
Asumo te refieres al sidecar Polymarket sentiment como conjunto. Si tienes
spec específica en mente, pásamela en r136.

**Mi recomendación**: NO refactor adicional pre-deploy Jue 7. Stack es
estable post r125+r129+r131. Los riesgos de tocar más código sin sign-off
exceden el beneficio.

## Q3 — Update SLA config p99<2000ms ahora o esperar audit checklist Jue 7?

Voto **esperar Jue 7 audit checklist**. Razones:
- SLA p99<2000ms NO está en código (es spec/doc)
- Es valor textual en r118 §Q4 + r122 §Q2 (firmas previas)
- Cambiar específicamente esos r-numbers reescribiría historia firmada
- Audit checklist Jue 7 es momento natural para emitir nueva spec consolidada
  con SLA recalibrado

Documento el cambio en r135 (este MD) como referencia. La codebase NO tiene
hard-coded el SLA — solo el test runner (criterion strings).

## Q4 — Monitor sidecar load Dallas más cerca durante Tests 2-4?

Tests 2-4 NO incrementan load del sidecar:
- Test 2 = config change V4 binary, sidecar sin cambio
- Test 3a/3b = unit + JSONL read passive, sidecar sin cambio
- Test 4a/4b = stop/restart sidecar deliberado (load bajísima durante stop)

Entonces **NO hace falta monitoring extra** durante Tests 2-4.

PERO sí hace falta verificar que **post-tests el sidecar Dallas resume con
btc_price válido** sin warmup eterno (issue r129 ya resuelto). Voy a
verificar `/api/state` después de cada test.

## Plan ejecución inmediato

```
T+0     17:50  Test 2 (3 sub-tests, ~5 min)
T+5     17:55  Test 3 (3 sub-tests, ~3 min)
T+8     17:58  Test 4 (3 sub-tests, ~5 min)
T+13    18:03  r136 con resultados + sign-off pre burn-in
T+15    18:05  Burn-in 24h arranca (si todo PASS)
T+24h   Jue 7 18:05  Burn-in completo
T+26h   Jue 7 ~20:00  audit checklist + deploy V4-Alpha
T+~70h  Vie 8 12:30  NFP audit-only event
```

Ventana 21:05 UTC perfectamente cumplible con margen.

NO toco nada hasta tu firma sobre Q1 criterios. Pero si me autorizas tácito
con tu firma D anterior, comienzo Test 2 ahora.

---

**Spec firmadas previas**: r93 + r107-r134
**Estado**: Conditional PASS T1 → ready Tests 2/3/4
