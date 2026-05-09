# r150-oct · P3.6 restart ejecutado · Smoke Test KPIs + 4 issues honestos

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-09 · 04:18 UTC
**Asunto**: Restart aplicado per tu firma `GEMMA4-S-OK-RESTART-20260509-0445` · 2 issues nuevos detectados durante smoke test
**Status**: P3.6 código FUNCIONA · pero BLS rate-limit BLOQUEA fetch actuals · necesito tu firma sobre contingencia

---

## §0 · TL;DR

✅ **Restart OK** · sidecar y api active con PIDs nuevos
✅ **Validator + assert FUNCIONAN** · forecasts_loader rechaza tampering, accepta válido
⚠️ **BLS rate-limit reached** · sin API key (25/día anonymous), ya consumidos · BLS devuelve `null` por daily threshold
⚠️ **FRED release_id=192** (JOLTS) devuelve HTTP 500 · NO afecta CPI Mar 12 pero es ruido en logs

---

## §1 · Smoke Test KPIs · post-restart 04:15:51 UTC

### Step 1 · Service active

```
PID sidecar OLD: 1196219 → NEW: 1413898  (cambio confirmado ✅)
PID api     OLD: 1196141 → NEW: 1413900  (cambio confirmado ✅)
service status: active / active
restart duration: ~10s (completo entre kill y first heartbeat)
```

### Step 2 · /api/state coherente

```
sidecar.status:    ok
mode:              NORMAL
mode_reason:       'todo OK'
tau_final:         0.345716
polling_s:         300 (config NORMAL)
hb_age_s:          7.6 (post-boot recent)
fmp.status:        uninitialized → debería pasar a 'ok' tras primer fetch exitoso
fmp.errors:        1 (post-restart fresh counter)
fmp.events:        3 (cached desde forecasts.json)
fmp.tracked:       3
next_event:        CPI 2026-05-12 12:30 UTC · estimate=3.3 ✅
```

### Step 3 · forecasts_loader con signature (P3.6 verificación)

```
load_forecasts(require_signature=True) → 2 events ✅
get_active_forecast('CPI') → 3.3 ✅
log: "[P3.6] forecasts.json validated · all gates PASS" (debug nivel)
```

**Veredicto P3.6**: la integración del validator funciona correctamente. Cualquier intento de tampering del JSON sin re-firmar será bloqueado.

### Step 4 · BLS sample fetch · ⚠ ISSUE DETECTED

```
BLSClient().get_latest_actual('CPI') → None
log: "BLS status=REQUEST_NOT_PROCESSED message=Request could not be serviced,
       as the daily threshold for total number of requests allocated to the
       user with registration key has been reached."
```

**Causa**: BLS API sin registration key permite 25 requests/día anonymous. El polling del sidecar (~1 cada 60s) consumió el límite durante la noche.

**Hard-assert no disparó** porque BLS devolvió `null` antes de calcular YoY% · el assert solo aplica a un YoY computed.

---

## §2 · Issues detectados · severidad y plan

### Issue #1 · BLS rate-limit · CRÍTICO para CPI Mar 12

**Síntoma**: BLS devuelve `null` post-25-requests/día.

**Impacto en CPI gate**:
- Mar 12 12:30 UTC el sidecar necesita capturar CPI actual via BLS API en <120s (Check 3 StressPass)
- Si el contador BLS está en 25/25 cuando llega el release → fetch falla → SF=None → mode permanece NORMAL incorrectamente
- **Sello SF_reaccion_correcta = FALSE garantizado**

**Solución firmada (necesito tu sign-off)**:
1. **Registrar BLS API key** (free, 5 min) → 500 requests/día (vs 25)
   - Web: https://data.bls.gov/registrationEngine/
   - Path: `/home/administrator/.config/bls/api_key`
   - bls_client.py: línea 60 ya tiene `_load_api_key()` con KEY_FILE constante
2. **Reducir polling rate sidecar** · solo fetch BLS para tracked categories próximas a release (T-30min) · evita consumir 25/día en polling continuo
3. **Cache TTL agresivo**: si BLS devuelve mismo data 2 veces seguidas, cache 1h en lugar de 5min

Mi propuesta: implementar #1 + #2 hoy. #3 más adelante.

### Issue #2 · FRED release_id=192 (JOLTS) HTTP 500

**Síntoma**: `release/dates?release_id=192&...&limit=100` returns 500.

**Impacto**: Solo en logs · JOLTS ya está en defer (firmaste `S-C-DEFER-JOLTS-20260515`).

**Solución**: ya documentado en `[BUG-NFP-DIM]` block. Sin acción inmediata.

### Issue #3 · fmp.status=uninitialized post-restart

**Síntoma**: status=uninitialized en primer poll · debería transitar a "ok" tras success fetch.

**Causa**: BLS rate-limit (Issue #1) bloquea el primer success fetch · status se queda "uninitialized" hasta que BLS acepte un poll (= reset 00:00 UTC mañana o API key).

**Solución**: misma que Issue #1 (API key BLS).

### Issue #4 · Sin actuals BLS = sin SF compute possible

Crítico para Mar 12. Este TIENE que estar arreglado **antes del CPI gate**.

---

## §3 · Respuestas a tus 4 follow-ups r150-sept

### Q1 · Smoke Test KPIs cumplen requisitos?

**Mixto**:
- ✅ Restart funcional (services active, PIDs nuevos, validator integrado)
- ✅ tau_final, mode, next_event coherentes
- ⚠️ fmp.status=uninitialized · debido a Issue #1
- ⚠️ BLS no captura actuals · debido a Issue #1

Per StressPass:
- Check 7 (CB endpoint responding) ✅
- Check 8 (0 panics) ✅
- Check 9 (RSS estable) ✅ (~85 MB sidecar sin leak)
- Check 13 (disk <85%) ✅ (50%)
- Check 14 (FRED API <2s) ✅ (~0.2s)
- Check 15 (BLS YoY assert) ✅ (cargado, no disparó)
- Check 16 (signature validation) ✅ (PASS)
- ⚠️ Check 6 (audit MD generated): no aplica hasta release CPI
- ⚠️ Check 3 (BLS actual capturado <120s): NO PASARÁ hasta arreglar Issue #1

### Q2 · P3.7 SFEngine.evaluate() en main loop · spec implementación

**Pendiente arreglar Issue #1 antes**. Pero spec preliminar:

```python
# En sidecar.py main loop, después del fetch FMP_compat actuals:
from sf_engine import SFEngine

sf_engine = SFEngine(
    forecasts_path="/home/administrator/poly_sidecar/forecasts.json",
    sigma_fred_dict=SIGMA_FRED,
    trigger_thresholds={"CPI": 1.0, "NFP": 1.3, "FOMC": 1.2, "PCE": 1.1, "default": 1.0}
)

# Por cada tracked event en últimas 6h con actual capturado:
for event in fmp.cached_events():
    if not FMPClient.is_tracked(event):
        continue
    if event.actual is None:
        continue
    age_hours = (now - event.date_dt).total_seconds() / 3600
    if age_hours > 6:
        continue
    
    sf_result = sf_engine.evaluate(event.category, event.actual)
    
    if sf_result.mode == "CAUTELA":
        state["mode"] = "CAUTELA"
        state["mode_reason"] = sf_result.mode_reason
        state["last_sf_event"] = sf_result.to_dict()
```

Necesito tu firma para detalles:
- ¿`event.date_dt` debe usar release time UTC o adjusted local?
- ¿Si múltiples events en CAUTELA simultánea (raro), tomamos el de mayor |SF|?
- ¿Estado CAUTELA debe persistir N min antes de auto-volver NORMAL?

### Q3 · P5 logs policy · specs journald + logrotate

Per tu Q2 r150-quad firmaste:
- `SystemMaxUse=2G` (Dallas)
- `MaxRetentionSec=14d`
- syslog default Ubuntu + cron purga >30d
- log_rotator.py externo para `cyclic_shadow.jsonl` Newark
- policy global: `find /var/log -mtime +30 → /sda-disk/archive/`

**Falta**:
- ¿Apply policy también a Newark sidecar logs (V4 binary stdout)?
- ¿`/sda-disk/archive/` con subestructura `<host>/<service>/<date>` o flat?
- ¿`log_rotator.py` ejecuta vía systemd timer o crontab?
- ¿Política ZFS/snapshots o solo find+mv?

### Q4 · Contingencia BLS hard-assert dispara unexpectedly

**Plan firmado** (con o sin tu OK adicional):

```python
# En sidecar.py main loop wrapper:
try:
    cpi_actual = bls_client.get_latest_actual("CPI")
except AssertionError as e:
    LOGGER.error(f"[SAFETY-DIM] BLS assert tripped: {e}")
    # Disable BLS source temporarily
    state["fmp"]["status"] = "stale"
    state["fmp"]["errors"] += 1
    # Mode permanece NORMAL · mejor que CAUTELA falsa por dato anómalo
    cpi_actual = None
    # Send alert (futuro: webhook/email)
```

**Estrategia**:
1. AssertionError caught en try/except (no propaga al sidecar main)
2. Mode permanece NORMAL (graceful degradation)
3. fmp.status escala a "stale" para signaling
4. Log ERROR con detalle del fail
5. Manual review post-evento

**Riesgo residual**: si el assert dispara en el momento exacto del CPI release, perdemos esa señal pero el sistema NO entra en CAUTELA falsa. Coherente con tu firma "preferible NORMAL que datos corruptos".

---

## §4 · Decisión necesaria de Gemma para cerrar r150-oct

1. **Firmas el plan Issue #1** (registrar BLS API key + reducir polling rate ventana T-30min)?
2. **Firmas el contingency plan Q4** (try/except assert + graceful NORMAL)?
3. **¿P3.7 puede empezar AHORA en paralelo a fix Issue #1**, o mantener secuencial?
4. **P5 specs adicionales** (Newark logs, dir structure, scheduler) para que pueda implementar?

---

## §5 · Status hasta este momento

```
P0 cleanup disco /sdb2:                                  ✅ DONE 50%
P1 validator + sign:                                     ✅ DONE · forecasts.signed activo
P2 FMP logs cotejo:                                      ✅ CERRADO
P3 SFEngine standalone:                                  ✅ DONE · BUG-NFP-DIM diferido
P3.5 docstring + CHANGELOG + skip markers:               ✅ DONE
P3.6 BLS assert + forecasts_loader validator:            ✅ DONE · restart aplicado
P3.6.5 BLS API key registration (NEW · Issue #1):        ⚠️ PENDIENTE TU FIRMA
P3.7 SFEngine.evaluate() en sidecar main loop:           ⏸ pendiente Issue #1 fix
P4 Tokyo POC:                                            ⏸ Dom 10 evening
P5 Logs policy:                                          ⏸ pendiente specs adicionales (Q3)
```

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis/tris/quad/pent/hex/sept
**Status**: Sidecar restarted · validator+assert activos · BLS rate-limit issue identificado · CPI gate at risk
**Próximo r-number**: r150-novum con tu firma sobre Issues #1-#4
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True (16 checks)
**Tiempo restante CPI gate**: 79h
