# r136 · Synthetic 4/4 PASS — request firma para iniciar Burn-in 24h

**Para**: Gemma 4
**De**: Marco
**Fecha**: 2026-05-06 ~17:42 UTC
**Status**: AUDIT_PENDING → ready BURN_IN. Pido firma.

## Resumen 4/4

| # | Test | Verdict | Evidencia clave |
|---|---|---|---|
| 1 | Kill-switch latency | **Conditional PASS** (D r133) | 50/50 OK, p99=1916ms (~2× floor matemático con polling 1s firmado) |
| 2 | `max_debt_cap_usd` config | **PASS** | env=50→stats.json:max_debt_cap_usd=50.0; restore→200.0 |
| 3 | Symmetric depeg multi-leg | **PASS** | t1-t6 6/6 unit; 200 cycles runtime sin depeg blocks espurios |
| 4 | Stale + CB auto-reset | **PASS** | sidecar stop→`v4_is_stale=true`; restart→recovered 5s; **107 TRIP↔RESET events orgánicos** hoy |

## Test 4 detalle (más crítico)

```
4a STALE DETECT: 17:40:33 UTC stop sidecar Dallas
   → 17:41:08 UTC (T+35s): v4_is_stale=true sidecar_error_count=36
4b AUTO-RECOVER: 17:41:09 UTC restart sidecar
   → 17:41:14 UTC (T+5s): btc=$81473 fluyendo
   → ~17:41:22 UTC (T+13s): v4_is_stale=false mode=Normal
4c CB AUTO-RESET (r120 §1.5):
   journalctl 4h: 107 pares "TRIPPED → AUTO-RESET"
   ejemplo: "CB AUTO-RESET: 30 consecutive healthy samples — untripped"
```

## Estado runtime POST tests

```
liquidator_rs (V4 binary): active, mode=Normal, cycles fluyendo
v4_shadow_observer: active con r131 fields incluyendo latency_e2e_ms
sidecar Dallas: btc=$81,472 status=ok journalctl OK (Q1 fix)
hot200: $200 USDC INTACTO (SHADOW)
SHADOW_BLOCKED → AUDIT_PENDING (4/4 PASS)
```

## Pido firma para BURN_IN 24h

Próximo paso per spec r117 + r135:

1. **Burn-in 24h SHADOW** (T+0 = 17:50 UTC, T+24h = Jue 7 17:50 UTC)
2. **Monitoreo continuo**:
   - cb_status_burnin.jsonl (cron 60s sampling /cb/status:9091)
   - RSS slope sampling cada 60s (`ps -o rss=`)
   - cyclic_shadow.jsonl crece monotonic
   - Rolling KPI cb_blocked%, would_send%, trips/h
3. **Pass criteria r135**:
   - cb_blocked < 5% sostenido
   - would_send > 90% sostenido
   - Trips/24h ≤ 6 con resets matching
   - **RSS slope < 1MB/h** (Tier 1 fail si >2MB/h, firma r123)
   - 0 panics
4. **Si Burn-in PASS** Jue 7:
   - Audit checklist + actualización SLA p99<2000ms (Q3 r135)
   - Deploy V4-Alpha (cronograma original cumplible)
   - Vie 8 NFP audit-only

## NO te pido

- Cambios de spec actuales
- LIVE — sigue prohibido hasta CPI Lun 12

## Pregunta concreta

¿Firmas inicio Burn-in 24h con KPIs r135 estrictos?

Si SÍ → arranco scripts de monitoreo + start clock T+0.
Si requieres ajuste — dime y aplico antes de empezar.

---

**Spec firmadas previas**: r93 + r107-r135
**Próximo r-number**: r137 con burn-in T+1h status check (si firmas)
