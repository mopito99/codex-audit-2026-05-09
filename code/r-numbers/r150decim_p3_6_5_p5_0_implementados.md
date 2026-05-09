# r150-decim · P3.6.5 + P5.0 implementados · pendiente OK restart Marco

**Para**: Marco (decisión final restart) · Gemma 4 31B (visibilidad)
**De**: Claude operativo
**Fecha**: 2026-05-09 · 05:36 UTC
**Asunto**: Implementación P3.6.5 (polling LOW/HIGH + cache TTL SHA-256) + P5.0 (log_rotator + systemd timer) + corrección honesta de un bug histórico
**Status**: Código aplicado · syntax OK · 5/5 smoke tests PASS · timer activo · **PENDIENTE Marco firma restart sidecar**

---

## §0 · TL;DR honesto

✅ P3.6.5 polling adaptativo aplicado en `sidecar.py` líneas 284-306
✅ P3.6.5 SHA-256 cache TTL aplicado en `bls_client.py` (3 ediciones)
✅ P5.0 `log_rotator.py` creado + `systemd` timer enabled + active
✅ 5/5 smoke tests offline PASS (cache, assert positive, assert negative, log_rotator dry-run, polling syntax)
⚠️ **Disclosure**: el `[SAFETY-DIM]` assert YoY [0,20] que el MD r150-sept dijo "DONE" nunca llegó al archivo. Lo aplicado AHORA por primera vez.

---

## §1 · Hallazgo crítico antes de empezar · regla "verificar antes de afirmar"

### Evidencia

```bash
$ wc -c bls_client.py bls_client.py.bak_pre_assert_20260509T040917Z
   10422 bls_client.py
   10422 bls_client.py.bak_pre_assert_20260509T040917Z
$ diff bls_client.py bls_client.py.bak_pre_assert_20260509T040917Z
(salida vacía · archivos idénticos)
```

El backup pre-assert (creado 04:09 UTC para "rollback") es **idéntico byte a byte** al `bls_client.py` actual. El edit del [SAFETY-DIM] que el MD r150-sept reportó como aplicado nunca se ejecutó realmente.

### Causa probable

Sospecho que el Edit de las 04:09 UTC retornó "success" pero el `old_string` no matcheó (yo lo verifiqué visualmente, no programáticamente con `grep` post-edit). Sin error visible, asumí éxito.

### Lección

Aplica la regla firmada `feedback_inventar_no_es_equivocarse.md`:
- "El MD lo dice" ≠ "el código está modificado"
- Tras cada Edit, verificar con `grep` que la cadena nueva existe en el archivo
- Si no hay verificación post-edit, no firmar "DONE"

### Mitigación aplicada en r150-decim

Tras cada Edit en este r-number, ejecutado:
1. `py_compile` verifica sintaxis
2. `python -c "import bls_client"` verifica imports
3. Smoke test funcional con datos reales BLS API

No declaré nada DONE sin las 3 verificaciones.

---

## §2 · Cambios aplicados · file:line

### A. `bls_client.py` (12372 bytes · era 10422)

**Edit 1 · línea 23**: añadir `import hashlib`

**Edit 2 · líneas 87-94** (`__init__`):
```python
# [P3.6.5] Cache TTL agresivo · SHA-256 sobre tuple parsed data
# Si hash igual al previo → extender TTL a 3600s · evita consumir API
self._prev_data_hash: dict[str, str] = {}
self._cat_last_fetch_ts: dict[str, float] = {}
self._cat_aggressive_ttl: dict[str, bool] = {}
```

**Edit 3 · líneas 198-210** (cache check en `get_latest_actual`):
```python
# [P3.6.5] Cache TTL adaptativo
# - default TTL: 300s (5min)
# - aggressive TTL: 3600s (1h) si hash datos parseados igual al previo
ttl = 3600 if self._cat_aggressive_ttl.get(category, False) else 300
last_fetch = self._cat_last_fetch_ts.get(category, 0.0)
cached = self._cache.get(series_id)
if not cached or (time.time() - last_fetch) > ttl:
    cached = self.fetch_series(series_id)
    if not cached:
        return None
    self._cat_last_fetch_ts[category] = time.time()
```

**Edit 4 · líneas 254-291** (assert + hash post-cómputo CPI/CPI_CORE):
```python
if yoy_obs:
    yoy_pct_raw = (latest.value - yoy_obs.value) / yoy_obs.value * 100
    # [SAFETY-DIM] Hard-assert firmado Gemma S-C-CLOSE-R150-HEX-20260509
    # Range histórico CPI YoY: -2.1% (2009) a 14.6% (1980)
    # Range conservador [0, 20] excluye deflation periods · ampliable
    # a [-3, 20] si entramos en periodo deflacionario futuro.
    assert 0 <= yoy_pct_raw <= 20, (
        f"Dimensionality Error: CPI YoY {yoy_pct_raw} outside "
        f"realistic bounds [0, 20]. Series={series_id} "
        f"latest={latest.value} yoy_obs={yoy_obs.value}"
    )
    result["yoy_pct_change"] = round(yoy_pct_raw, 4)

# ... (al final de get_latest_actual, antes de return)
# [P3.6.5] SHA-256 hash sobre tuple parsed data (Q2 Gemma firma · parsed object)
hash_tuple = (series_id, latest.year, latest.period, latest.value, previous.value)
cur_hash = hashlib.sha256(json.dumps(hash_tuple, sort_keys=True).encode()).hexdigest()
prev_hash = self._prev_data_hash.get(category)
if prev_hash == cur_hash:
    self._cat_aggressive_ttl[category] = True
else:
    self._cat_aggressive_ttl[category] = False
    self._prev_data_hash[category] = cur_hash
```

### B. `sidecar.py` (28257 bytes · era 27463)

**Edit 1 · líneas 284-306** (polling adaptativo en `compute_state_once`):
```python
# [P3.6.5] FMP polling adaptativo · firmado Gemma r150-novum
# LOW_FREQUENCY = 3600s · default fuera de ventana T-30min
# HIGH_FREQUENCY = 30s · cuando seconds_to_event de next tracked < 1800s
# Razón: Mar 12 12:30 UTC CPI gate necesita capture <120s post-release
if fmp.configured:
    cached_for_poll = fmp.cached_events()
    _, sec_to_next_cached = (
        time_to_next_event(cached_for_poll) if cached_for_poll else (None, None)
    )
    in_t30_window = (
        sec_to_next_cached is not None and 0 < sec_to_next_cached < 1800
    )
    poll_interval = 30 if in_t30_window else 3600
    if (time.time() - fmp_last_fetch_ts[0]) > poll_interval:
        try:
            await fmp.fetch_calendar(days_ahead=14, days_behind=0)
            fmp_last_fetch_ts[0] = time.time()
            if in_t30_window:
                logger.info(
                    f"[P3.6.5] HIGH_FREQUENCY poll · sec_to_next={sec_to_next_cached:.0f}s"
                )
        except Exception as e:
            logger.warning(f"FMP fetch error: {e}")
```

### C. `log_rotator.py` (4283 bytes · nuevo)

Standalone script · 142 LOC · gzip + mv a `/sda-disk/archive/<host>/<service>/<YYYY-MM-DD>/`.

Targets configurados:
- `poly_sidecar/data/sidecar.log*` → service="poly_sidecar"
- `poly_sidecar/data/audit/*.log` → service="poly_sidecar_audit"
- `poly_sidecar/data/audit/*.json` → service="poly_sidecar_audit"

Retention: 30 días · idempotente · exit codes 0/1/3.

### D. systemd · `/etc/systemd/system/poly_log_rotator.{service,timer}` (nuevo)

```ini
# poly_log_rotator.timer
[Timer]
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true
RandomizedDelaySec=300
```

```bash
$ sudo systemctl is-enabled poly_log_rotator.timer
enabled
$ sudo systemctl is-active poly_log_rotator.timer
active
$ sudo systemctl list-timers poly_log_rotator.timer
NEXT                        LEFT LAST PASSED UNIT                   ACTIVATES
Sun 2026-05-10 03:30:00 UTC  21h -         - poly_log_rotator.timer poly_log_rotator.service
```

### E. `/sda-disk/archive/` (creado)

```bash
$ ls -ld /sda-disk/archive
drwxr-xr-x 2 administrator administrator 4096 May  9 05:34 /sda-disk/archive
$ df -h /sda-disk
/dev/sda1   11T   57G   11T   1%   /sda-disk
```

11 TB libres · headroom abundante.

---

## §3 · Smoke tests · 5/5 PASS

### Test 1 · CPI fetch real BLS

```
CPI YoY: 3.2564%  (debe estar [0,20])  ✅
aggressive_ttl post-1st fetch: False (primera vez · sin hash previo)  ✅
prev_data_hash present: True  ✅
```

### Test 2 · Cache hit · mismo data → aggressive TTL

```
CPI YoY: 3.2564% (segunda llamada)
aggressive_ttl: True  ✅ (hash igual → próximo fetch usará TTL 3600s)
```

### Test 3 · NFP + UNEMPLOYMENT (sin assert)

```
NFP change: 115.0K  ✅
UNEMPLOYMENT: 4.3%  ✅
```

### Test 4 · [SAFETY-DIM] assert dispara con YoY=100% (inyectado)

```python
fake_latest=200, fake_yoy=100 → YoY = 100%
ASSERT FIRED OK: Dimensionality Error: CPI YoY 100.0 outside realistic
bounds [0, 20]. Series=CUUR0000SA0 latest=200.0 yoy_obs=100.0  ✅
```

El assert que llevaba 1h 20min documentado pero no en código, **ahora sí dispara**.

### Test 5 · log_rotator dry-run

```
$ python3 /home/administrator/poly_sidecar/log_rotator.py --dry-run
2026-05-09 05:35:15 [INFO] log_rotator: summary: archived=0 failed=0  ✅
```

Cero errores · cero archivos archivados (logs frescos · esperado).

---

## §4 · Estado pre-restart · evidencia

```
mode:                       NORMAL
mode_reason:                "todo OK"
tau_final:                  0.345568
fmp.status:                 ok          ✅
fmp.errors:                 0           ✅
fmp.events_in_cache:        3
next_event:                 CPI 2026-05-12T12:30:00 UTC
seconds_to_event:           284,051 (= 78.9h)
```

**Importante**: Los cambios en `bls_client.py` y `sidecar.py` están en disco · el sidecar **runtime sigue corriendo el código viejo** porque los módulos están cargados en memoria. Para activar:

```bash
sudo systemctl restart vq-poly-sidecar vq-poly-api
```

`log_rotator` no requiere restart sidecar (es proceso independiente vía timer).

---

## §5 · Backups · rollback en <10s

```
bls_client.py.bak_pre_p3_6_5_20260509T052811Z   (10422 bytes)
sidecar.py.bak_pre_p3_6_5_20260509T052811Z      (27463 bytes)
```

Rollback completo:
```bash
cd /home/administrator/poly_sidecar
cp bls_client.py.bak_pre_p3_6_5_20260509T052811Z bls_client.py
cp sidecar.py.bak_pre_p3_6_5_20260509T052811Z sidecar.py
sudo systemctl disable --now poly_log_rotator.timer
sudo rm /etc/systemd/system/poly_log_rotator.{service,timer}
sudo systemctl daemon-reload
sudo systemctl restart vq-poly-sidecar vq-poly-api
```

---

## §6 · Plan post-restart · 12h soak count

Per firma Gemma r150-novum Q4: **soak count desde el restart de P3.6.5** (no desde el restart de las 04:15).

```
T=0      restart sidecar P3.6.5+P5.0 aplicado     (ahora · pendiente tu OK)
T+12h    si soak OK · errores=0 · sin panics      → trigger P3.7 SFEngine integration
T+78h    CPI release Mar 12 12:30 UTC             (ventana T-30min activa P3.6.5 HIGH_FREQUENCY)
```

---

## §7 · Riesgo del restart · evaluación

| Vector | Riesgo | Mitigación |
|---|---|---|
| Bug en polling adaptativo (división por None) | Bajo | `sec_to_next_cached is not None` check explícito |
| Assert dispara unexpectedly al boot | Muy bajo | YoY actual=3.26% lejos de [0,20] frontier |
| Cache TTL extiende stale data | Bajo | Solo extiende TTL si hash IGUAL · si dato cambia, vuelve a 5min |
| `log_rotator` toca `data/sidecar.log` actual | Cero | RETENTION_DAYS=30 · `sidecar.log` creado HOY |
| Downtime sidecar restart | ~10s | Aceptable · no trades activos |

---

## §8 · Pregunta directa para tu OK

1. **¿Apruebas el restart `sudo systemctl restart vq-poly-sidecar vq-poly-api`** con los cambios P3.6.5 + P5.0?
2. Si SÍ → procedo + smoke test post-restart + report KPIs en r150-undecim
3. Si prefieres delay · esperamos hasta cuándo (¿pre-CPI Lun 11 evening?)

---

## §9 · Respuestas a las 4 follow-ups Gemma (screenshot 05:42)

1. **"P3.6.5 and P5.0 implementados · 12h soak timer activo?"** → No todavía · activación requiere tu firma restart. Te pregunto en §8.

2. **"SHA-256 hash · raw JSON o parsed data?"** → Aplicado **parsed data object** (tuple `(series_id, year, period, value, prev_value)` JSON-encoded). Más estable que raw JSON (raw cambia con campos meta como `latest=true/false` que oscilan).

3. **"Tokyo POC hoy o postpone?"** → Recomiendo **postpone Dom 10 evening** o post-soak (tu decides). Justificación: ventana 12h soak es output crítico para P3.7 trigger; abrir Tokyo POC en paralelo divide attention durante la verificación más sensible (faltan 79h al CPI gate).

4. **"Métricas a monitorizar durante soak para validar P3.7 trigger?"** → Lista propuesta:
   - `fmp.errors` debe stay = 0 durante 12h consecutivas
   - `fmp.status` debe stay = "ok"
   - `tau_final` debe permanecer en rango sano [0.20, 0.50] sin spikes >0.70
   - `mode` debe permanecer NORMAL (sin transiciones falsas a CAUTELA)
   - Heartbeat sidecar debe stay <30s (no stalls)
   - `journalctl -u vq-poly-sidecar` cero `WARNING\|ERROR` repetidos
   - Polling LOW=3600s confirmado (no debe disparar HIGH_FREQUENCY hasta T-30min al CPI = Mar 12 12:00 UTC)
   - SHA-256 cache hits visibles en logs (`aggressive_ttl=True` en repeated polls)

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis...novum
**Status**: Código en disco · runtime old · pendiente Marco firma restart
**Próximo r-number**: r150-undecim post-restart con KPIs smoke test post + soak start timestamp
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True
**Tiempo restante CPI gate**: 78h 56min
