# r152-M1-bis + M2-bis · evidence post-implementation · ambos críticos cerrados

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas)
**De**: Claude operativo
**Fecha**: 2026-05-09 · 11:40 UTC
**Asunto**: M1-bis + M2-bis IMPLEMENTED + verificados empíricamente · pendiente tu firma cierre + autorización Codex re-audit V3
**Status**: 🟢 **AMBOS P0 CLOSED** · 15/15 tests PASS · sidecar restart OK

---

## §0 · TL;DR

- ✅ M1-bis nginx Deny-by-Default · `/poly/admin/*` 404 · `/poly/health|metrics` 401 · `/poly/` catch-all auth_basic
- ✅ M2-bis BLS force_refresh · 4 nuevos tests PASS · runtime verified (5×force=5 HTTP calls)
- ✅ M2 regression 11/11 tests PASS · sin regresiones
- ✅ sidecar restart OK · PID 1505021 active · zero warnings
- ⏳ Bundle Codex pendiente actualizar para V3 audit
- 🟡 Tiempo total fix M1-bis + M2-bis: 25 min

---

## §1 · M1-bis · Nginx Deny-by-Default · evidence

### Diff config

```nginx
# ANTES (vulnerable)
location /poly/ {
    proxy_pass http://127.0.0.1:8090/;
    # ... sin auth_basic · catch-all expuesto
}

# DESPUÉS (M1-bis)

# Bloquear admin namespace explícitamente ANTES del catch-all
location /poly/admin/ {
    return 404;
}

# Bloquear health/metrics públicos
location = /poly/health {
    return 401;
}
location /poly/metrics {
    return 401;
}

location /poly/ {
    # Auth_basic en catch-all (Deny-by-Default)
    auth_basic "VelocityQuant Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd_vq;
    proxy_pass http://127.0.0.1:8090/;
    # ... resto
}
```

### Verify externamente · todos los códigos esperados

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/admin/test/macro_status"
404                ✅ (era 200)

$ curl -X POST -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/admin/test/inject_macro_state"
404                ✅

$ curl -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/health"
401                ✅ (era 200)

$ curl -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/randompath"
401                ✅ (catch-all auth_basic activo)

$ curl -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/audit/dashboard.html"
401                ✅ sin auth

$ curl -s -o /dev/null -w "%{http_code}\n" "https://inicio.velocityquant.io/poly/api/state"
401                ✅ sin auth

$ curl -s -o /dev/null -w "%{http_code}\n" -u 'marco:<pass>' "https://inicio.velocityquant.io/poly/audit/dashboard.html"
200                ✅ con auth

$ curl -s -o /dev/null -w "%{http_code}\n" -u 'marco:<pass>' "https://inicio.velocityquant.io/poly/api/state"
200                ✅ con auth

$ curl -s -o /dev/null -w "%{http_code}\n" -u 'marco:<pass>' "https://inicio.velocityquant.io/poly/"
200                ✅ catch-all funciona con auth
```

### Backup pre-edit

```
/etc/nginx/sites-available/inicio.velocityquant.io.bak_pre_M1bis_20260509T113419Z
```

✅ **CRITICAL-NEW-01 cerrado**.

---

## §2 · M2-bis · BLS force_refresh · evidence

### Cambios en 3 archivos

#### `bls_client.py:192-241` (signature + bypass logic)

```python
def get_latest_actual(
    self,
    category: str,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """...
    Args:
        force_refresh: si True bypassa cache + aggressive_ttl · forza HTTP call BLS.
            Activado por sidecar durante macro window T-30→T+15min para garantizar
            SLA <120s post-release (Codex CRITICAL-NEW-02 fix · firmado Gemma r152-M2-bis).
    """
    series_id = SERIES_BY_CATEGORY.get(category)
    if not series_id:
        return None

    if force_refresh:
        # Bypass total · cache + aggressive_ttl ignorados
        cached = self.fetch_series(series_id)
        if not cached:
            return None
        self._cat_last_fetch_ts[category] = time.time()
        LOGGER.info(
            f"[r152-M2-bis] {category} force_refresh=True · BLS HTTP call forced "
            f"(macro window) · cache + aggressive_ttl bypassed"
        )
    else:
        # Cache TTL adaptativo (LOW frequency · normal)
        ttl = 3600 if self._cat_aggressive_ttl.get(category, False) else 300
        # ... resto idéntico al pre-fix
```

#### `fmp_compat.py:135-181` (propagar parameter)

```python
async def fetch_calendar(
    self,
    days_ahead: int = 14,
    days_behind: int = 7,
    force_refresh_bls: bool = False,
) -> list[MacroEvent]:
    """...force_refresh_bls propaga a BLSClient durante macro window."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, self._sync_fetch, days_ahead, days_behind, force_refresh_bls,
    )
    return list(self._cache)


def _sync_fetch(
    self, days_ahead, days_behind,
    force_refresh_bls: bool = False,
) -> None:
    # ... FRED calendar fetch
    for cat in ("NFP", "CPI", "PCE", "UNEMPLOYMENT"):
        bls_actuals[cat] = self._bls.get_latest_actual(
            cat, force_refresh=force_refresh_bls,
        )
```

#### `sidecar.py:387-405` (activar durante high window)

```python
if (time.time() - fmp_last_fetch_ts[0]) > poll_interval:
    try:
        # [r152-M2-bis] force_refresh_bls=True durante high window
        # bypass cache TTL · garantiza SLA <120s post-release
        await fmp.fetch_calendar(
            days_ahead=14,
            days_behind=0,
            force_refresh_bls=in_high_window,  # ← clave
        )
        fmp_last_fetch_ts[0] = time.time()
        if in_high_window:
            logger.info(
                f"[P3.6.5-v2] HIGH_FREQUENCY poll · "
                f"evt={next_or_recent_ev.event} "
                f"secs_window={secs_window:.0f}s "
                f"(neg=post-release · BLS force_refresh=True)"
            )
```

### Tests M2-bis 4/4 PASS

```
tests/test_m2bis_force_refresh.py::test_force_refresh_bypasses_cache PASSED [25%]
tests/test_m2bis_force_refresh.py::test_force_refresh_5_calls_5_http PASSED [50%]
tests/test_m2bis_force_refresh.py::test_default_low_frequency_caches_correctly PASSED [75%]
tests/test_m2bis_force_refresh.py::test_force_refresh_returns_data_correctly PASSED [100%]

============================== 4 passed in 0.05s ==============================
```

### Tests M2 regression 11/11 PASS

```
tests/test_polling_window.py · 11 passed in 0.07s · zero regresiones
```

### Verify funcional empírico (real http intercept)

```python
Test A · 5x get_latest_actual('CPI') WITHOUT force_refresh (LOW window)
  BLS API calls: 1 (esperado: 1 · primera cache miss)

Test B · 5x get_latest_actual('CPI', force_refresh=True) (high window M2-bis)
  BLS API calls: 5 (esperado: 5 · cada call fuerza HTTP) ✅

Test C · tras force_refresh · LOW vuelve a cache
  Post-bypass · cache hit: YES ✅
```

### Backup pre-edit

```
bls_client.py.bak_pre_M2bis_20260509T113534Z
fmp_compat.py.bak_pre_M2bis_20260509T113534Z
```

✅ **CRITICAL-NEW-02 cerrado**.

---

## §3 · Sidecar restart + verify post-fix

```
PIDs: 1486192 → 1505021 (cambio confirmado)
ActiveState sidecar: active
ActiveState api:     active
mode:                NORMAL
fmp.status:          ok
fmp.errors:          0
next_event:          CPI in 72.9h
RSS:                 105.3 MB (estable)

journalctl -p warning --since='5 min ago': -- No entries --
httpx redaction:     activo (api_key=<REDACTED> en logs)
[P3.6.5-v2] log:     0 (correcto · CPI 72.9h lejos · LOW)
```

---

## §4 · Quota BLS estimada con M2-bis · sanity check

Tu pregunta del plan original: "El costo de un HTTP request extra es insignificante comparado con el riesgo de un trade basado en un dato stale."

Cálculo concreto:
- BLS quota daily con API key: **500 calls/día**
- LOW frequency normal: 1 call/category × 4 categories × 24h cycles ≈ **24-30 calls/día**
- Macro window M2-bis: ~45min × 30s polling × 4 categories = **360 calls** durante window
- 4 events macro/mes (CPI + NFP + UNEMP + PCE) × 1 window × 360 = **1,440 calls/mes en bursts**
- Daily máximo en evento day: 30 (LOW) + 360 (window) = **~390 calls/día evento**
- ≪ 500 limit · holgura ~22%

✅ Quota OK.

---

## §5 · Respuestas a tus 4 follow-ups (11:35 UTC screenshot)

### Q1 · Snippet exacto Nginx Deny-by-Default

**Implementado · ver §1 arriba**. Pattern:

```nginx
# 1. Specific blocks SIN auth (priority longest prefix)
location /poly/api/    { auth_basic ...; proxy_pass ...; }
location /poly/audit/  { auth_basic ...; proxy_pass ...; }
location /poly/pnl/    { auth_basic ...; proxy_pass ...; }

# 2. Explicit DENY ANTES del catch-all
location /poly/admin/  { return 404; }
location = /poly/health { return 401; }
location /poly/metrics  { return 401; }

# 3. Catch-all con auth_basic (Deny-by-Default)
location /poly/ {
    auth_basic "VelocityQuant Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd_vq;
    proxy_pass http://127.0.0.1:8090/;
}
```

**Filosofía**: cualquier path bajo `/poly/` que no esté explícitamente permitido sin auth requiere credenciales O retorna 4xx. Cero superficie expuesta sin firma.

### Q2 · Implementación `force_refresh` sin rate limits

**Implementado · ver §2 arriba**. Strategy:
1. **Default `force_refresh=False`** · respeta cache TTL (300s LOW · 3600s aggressive)
2. **`force_refresh=True` SOLO durante high window** · activado por `in_high_window` en sidecar (T-30→T+15min del próximo tracked event)
3. **Quota math**: ~390 calls/día evento day vs 500 daily limit · holgura 22%
4. **Logs explícitos** `[r152-M2-bis] CPI force_refresh=True · BLS HTTP call forced`

Razón quota OK: el window dura 45min, no todo el día. Fuera de window vuelve a cache.

### Q3 · Tests integration BLS HTTP refetch durante high window

**4 tests parametrizados creados en `tests/test_m2bis_force_refresh.py`**:

1. `test_force_refresh_bypasses_cache` · verify cache MISS post-force
2. `test_force_refresh_5_calls_5_http` · verify N×force = N HTTP calls
3. `test_default_low_frequency_caches_correctly` · verify N×default = 1 HTTP (cache hits)
4. `test_force_refresh_returns_data_correctly` · verify schema dict idéntico force vs default

**Adicional propuesto** (M3 cuando deploy): test integration end-to-end:
```python
def test_high_window_real_run_once():
    """Setup mock event T+30s · run sidecar.compute_state_once · verify BLS API hit."""
    # Inyectar mock event próximo a now
    # Capturar httpx.Client.post calls durante run_once()
    # Assert: ≥1 call con api.bls.gov tras passing tick
```

Lo agrego a M3 deploy plan si firmas.

### Q4 · CI gate mínimo · Makefile/pipeline

**Propuesta** (NO implemento sin tu firma):

```makefile
# /home/administrator/poly_sidecar/Makefile
.PHONY: ci ci-fast lint test secrets-scan whitespace

# Gate mínimo · pre-commit + pre-deploy
ci: lint test secrets-scan whitespace

ci-fast:
	./venv/bin/pytest tests/ -q

lint:
	./venv/bin/python -m py_compile sidecar.py bls_client.py fmp_compat.py forecasts_loader.py forecasts_validator.py sf_engine.py log_rotator.py

test:
	./venv/bin/pytest tests/ -v --tb=short

secrets-scan:
	gitleaks detect --config /home/administrator/codex_audit_2026-05-09/custom_vq.toml \
		--source . --no-git --no-banner --exit-code 1

whitespace:
	git diff --check HEAD~1 HEAD || (echo "ERROR: trailing whitespace"; exit 1)

# Pre-deploy hard gate (incluye dry-run replay)
deploy-gate: ci
	@echo "✅ ci passed · listo para deploy"
```

Pre-commit hook simple:
```bash
#!/bin/bash
# .git/hooks/pre-commit (NO en repo · local install)
make -C poly_sidecar ci-fast || exit 1
```

Si firmas · creo `Makefile` + hook + GitHub Actions equivalente · ~30 min.

---

## §6 · Status post fixes M1-bis + M2-bis

```
M1 saneamiento + endpoints       ✅ CLOSED
M1-bis nginx Deny-by-Default     ✅ CLOSED (esta sesión)
M2 polling helper                ✅ VALIDATED
M2-bis BLS force_refresh         ✅ CLOSED (esta sesión · M2 ahora completo)
M3 BLS period validation         🔒 LOCKED hasta T+12h soak (22:05 UTC)
M4 BUG_NFP_DIM real fix          ⏸ Lun 11
M5 PATH_BASE + asserts→raises    ⏸ Lun 11
M6 systemd hardening             ⏸ Mar 12
M7 CPI dry-run hard gate         🚨 Mar 12 12:30 UTC
M8 Codex re-audit V3             ⏸ Vie 19 (planificado)
LIVE microcapital                🎯 Mar 22 13:30 UTC

Codex re-audit V3 · ¿AHORA o esperar más milestones?
```

---

## §7 · Próximas acciones por tu firma

1. **¿Apruebas M1-bis nginx fix** verified empírico (8 curl tests todos códigos esperados)?
2. **¿Apruebas M2-bis BLS force_refresh** (4 tests + runtime verify · quota safe)?
3. **¿Procedo Codex re-audit V3 ahora** con bundle actualizado para validar M1-bis + M2-bis cierran críticos?
4. **¿Apruebas creación Makefile CI gate** (Q4 propuesta)?
5. **¿Avanzo a sanitización bundle** (eliminar balance_snapshots + wallet pubkeys del audit bundle)?

---

**Spec firmadas previas**: r93 + r107-r152 + r152-bis + r152-M1 (CLOSED hash M1-SANEAMIENTO-DONE-20260509T1100UTC) + r152-M2 (VALIDATED) + r152-M3-prelim (APPROVED) + r152-codex-v2 (NO-GO)
**Próximo r-number**: r152-M2-bis-validated post tu firma · luego r152-V3-audit-prep
**Capital LIVE expuesto**: $0
**Tiempo restante target Mar 22 13:30 UTC**: 12d 0h
**Tiempo restante CPI dry-run hard gate**: 2d 21h
