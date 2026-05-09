# r140b · r140 calibración WORKING + respuesta 4 preguntas

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 04:47 UTC
**T+5min post-r140 (TRIP=22, RESET=5 desde 04:41:59 UTC)**

---

## TL;DR — r140 funciona dramáticamente

| KPI | T+10h45min pre-r140 | T+5min post-r140 | Delta |
|---|---|---|---|
| `cb_blocked%` | 77.7% | **0.0%** | -77.7pt |
| `would_send%` | 17.6% | **37.0%** | +19.4pt |
| `trips/h` | 31.8 | **0** (4min window) | -31.8 |
| `slot_lag avg` | (alto) | **5.1** | dentro [reset=5, trip=22) |
| CB state | tripped 77% | NOT tripped, healthy=6 | recuperando |

Esto valida la decisión de calibrar a p95 — eliminó el trip-loop completamente
en <5 min. Procedo a observar T+15min y T+1h per spec r140.

## Respuesta a 4 preguntas seguimiento

### Q1 — Qué monitorear primeros 15 min para validar nuevos thresholds?

Mi check list operacional:

| Métrica | Esperado | Indicador de fallo |
|---|---|---|
| `cb_blocked%` rolling 15min | <5% sostenido | >20% = nuevo trip-loop |
| `consecutive_healthy` | crece monotónico (0→30→reset cycle) | bouncing 0-15 = jitter alto |
| `journalctl TRIPPED` count | 0-2/15min OK | >5 = TRIP=22 aún sensible |
| `journalctl AUTO-RESET` matching | trip≈reset | trips > resets = stuck |
| `slot_lag avg` cyclic_shadow | 3-7 normal | >10 sostenido = network deg |
| `would_send%` últimos 100 cycles | 30-60% baseline | <20% = otra causa bloqueando |
| RSS slope | sigue +0.08 MB/h | desviación >5x = leak |

Comando único monitor:
```bash
$SSH "tail -100 /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl" | <python aggregator>
```

### Q2 — Si cb_blocked%>25% post-1h con TRIP=22, ¿TRIP=25 inmediato o re-evaluar?

Mi propuesta: **re-evaluar slot_lag distribution** primero, NO saltar a TRIP=25.

Lógica:
- Distribución pre-r140 mostró p95=22. Calibramos AT p95.
- Si cb_blocked>25% con TRIP=22, significa que la distribución **CAMBIÓ**
  (network burst, congestión Solana mayor que antes).
- Subir a TRIP=25 sin verificar = persigues una distribución móvil → siempre
  estarás un step atrás.

Plan condicional:
1. T+1h: si cb_blocked >25% → recompute histogram últimos 5000 cycles
2. Si nuevo p95 ≤ 22 (mismo) → bug, investigar otra causa
3. Si nuevo p95 ∈ (22, 28] → subir TRIP a nuevo_p95
4. Si nuevo p95 > 28 → Solana network catastrophic, considerar abort burn-in

### Q3 — Lógica systemd timer para evitar silent wakeup failures

Diseño propuesto del timer en Dallas:

```bash
# /etc/systemd/system/vq-burnin-watchdog.timer
[Timer]
OnUnitActiveSec=15min
OnBootSec=2min

# /etc/systemd/system/vq-burnin-watchdog.service
[Service]
ExecStart=/home/administrator/poly_sidecar/scripts/burnin_watchdog.py
```

`burnin_watchdog.py` ejecuta cada 15min:

```python
1. Check liquidator_rs uptime: si <60s → CRASH detected, alert
2. Check RSS slope ÚLTIMA hora: si >2 MB/h → Tier 1 trigger
3. Check cb_blocked% últimos 60min: si >50% sostenido → calibration regression
4. Check 0 panics desde último check: si >0 → CRITICAL alert
5. Si CUALQUIER check fail → write /poly_sidecar/data/burnin_alerts.jsonl
   + (opcional) telegram push si configurado
6. Si TODOS pass → escribir burnin_status.json (consumido por dashboard)
```

Esto es **sustituto del wakeup runtime**. Corre indefinidamente, no
depende de mi sesión Claude. Lo armo si lo apruebas (15 min de trabajo).

### Q4 — ¿TRIP=22 introduce risk al deploy V4-Alpha Jue 7 17:46 UTC?

**No introduce risk arquitectónico** pero sí ajusta la spec safety:

| Aspecto | Antes (TRIP=8) | Post-r140 (TRIP=22) |
|---|---|---|
| Sensibilidad a degradación | alta (trip casi cualquier jitter) | media (trip solo eventos severos) |
| False positives | 25-30% trips espurios | <5% proyectado |
| Capacidad detección catastrofic | excelente | sigue cubriendo lag>22=4.4s degraded |
| Coherencia con realidad Solana | desalineada (p95=22) | alineada con p95 |
| Window deploy Jue 7 17:46 UTC | bloqueado por calibration FAIL | **viable si T+24h burn-in valida** |

**Risk real al deploy**:
- Si NFP Vie 8 12:30 UTC genera spike >22 slots: bot trip, pierde event capture
  - Mitigación: NFP es audit-only firmado, sin LIVE flag. Trip sería
    documented como degradación esperada.
- Si Solana congestion drops to <5 lag during NFP: bot funciona normal
  con TRIP=22, sin cambios visible.

**Conclusión**: TRIP=22 es OK para deploy SHADOW Jue 7. Para considerar
LIVE post-CPI, podría re-evaluarse a algo intermedio (15) si datos en
tiempo de calma muestran p95 más bajo que 22.

## Plan próximas 4h (hasta T+24h)

```
04:42 UTC ✅ r140 applied
04:47 UTC ✅ T+5min check: cb_blocked 0%, would_send 37%
05:00 UTC    T+15min check: validar comportamiento sostenido
05:42 UTC    T+1h post-r140: KPIs completos, decisión Q2 si fail
07:42 UTC    T+3h post-r140: confirmación healthy zone consolidada
17:46 UTC    Burn-in T+24h end → audit checklist → deploy V4-Alpha
```

NO toco nada más hasta tu decisión sobre Q3 (watchdog systemd timer).

---

**Spec firmadas**: r93 + r107-r140
**Status**: BURN_IN healthy zone post-calibración
**Próximo r-number**: r141 con T+1h post-r140 KPIs
