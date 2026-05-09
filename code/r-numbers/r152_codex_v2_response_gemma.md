# r152-codex-v2 · 2 veredictos NO-GO confirmados empíricamente

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas)
**De**: Marco + Claude operativo
**Fecha**: 2026-05-09 · 11:10 UTC
**Asunto**: Codex V2 detectó 2 críticos NUEVOS que cierran nuestros M1+M2 como **insuficientes** · ambos verificados empíricamente
**Status**: ⛔ **NO-GO ratificado** · M1-bis + M2-bis URGENTES · plan ajuste

---

## §0 · TL;DR brutal

- ✅ Codex V2 ambos veredictos: **NO-GO** sigue
- ✅ M1-bis necesario · `/poly/` catch-all bypass público (`/poly/admin/test/*`, `/poly/health`)
- ✅ M2-bis necesario · BLS TTL cachea 3600s · `fetch_calendar()` cada 30s NO refresca actual BLS
- 🟡 Mi M1+M2 cerraron parcial · pero NO los root causes
- ⚠️ Patrón anti repetido: **claim que no resuelve realidad**

---

## §1 · CRITICAL-NEW-01 · `/poly/` catch-all bypass

### Evidencia empírica (ahora 11:08 UTC)

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" https://inicio.velocityquant.io/poly/health
200    ⛔ debería 401

$ curl -s -o /dev/null -w "%{http_code}\n" https://inicio.velocityquant.io/poly/admin/test/macro_status
200    ⛔ ADMIN ENDPOINT PÚBLICO

$ curl -X POST -s -o /dev/null -w "%{http_code}\n" https://inicio.velocityquant.io/poly/admin/test/inject_macro_state
422    ⛔ REACHABLE · solo necesita LIQ_SIDECAR_TEST_MODE=1 + body válido

$ curl -s -o /dev/null -w "%{http_code}\n" https://inicio.velocityquant.io/poly/audit/dashboard.html
401    ✅ correcto
```

### Root cause

Mi M1 fix añadió `auth_basic` solo en 3 locations específicos:
- `/poly/api/`
- `/poly/audit/`
- `/poly/pnl/`

PERO el location `/poly/` (line 59 nginx) sigue como catch-all SIN auth · proxy_pass a FastAPI root. Cualquier path nginx que no matchee uno de los 3 específicos cae aquí.

### Fix M1-bis · 2 enfoques

**Enfoque A (más simple · recomendado)**: deny `/poly/admin/` + auth_basic en `/poly/` general

```nginx
# Bloquear admin namespace explícitamente
location /poly/admin/ {
    return 404;
}

# Auth_basic en location /poly/ general (catch-all)
location /poly/ {
    auth_basic "VelocityQuant Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd_vq;
    proxy_pass http://127.0.0.1:8090/;
    # ... resto config
}
```

**Enfoque B**: granular · permitir `/poly/health` público pero el resto auth · más complejo · NO recomiendo.

### Impacto Mar 12

Si LIVE Mar 22 con esto abierto + `LIQ_SIDECAR_TEST_MODE=1` accidentalmente activado: cualquiera puede inyectar mode CAUTELA falsa via POST · trigger trades incorrectos. Severity = CRITICAL real, no teórico.

---

## §2 · CRITICAL-NEW-02 · BLS TTL bypass durante high window

### Evidencia empírica (ahora 11:09 UTC)

```python
# 5x get_latest_actual('CPI') in rapid succession
Test 1: primer fetch · BLS API call · 454ms · CPI YoY 3.2564%
Test 2: fetch inmediato · cache hit · 0ms · aggressive_ttl=True
Test 3: 5 calls back-to-back · 0 BLS API POST calls (todas cache)
```

### Root cause

- M2 fix `sidecar.py:285-307`: `fetch_calendar()` cada 30s during high window ✅
- **Pero `fetch_calendar()` NO llama BLS API directamente**
- `fetch_calendar()` → llama `bls_client.get_latest_actual('CPI')` internamente
- `get_latest_actual()` (`bls_client.py:198-211`) tiene **TTL interno**:
  - default: 300s
  - aggressive (si hash igual al previo): **3600s**
- Mi SHA-256 cache TTL fix (M1) hace que post-2 calls iguales → TTL 3600s

### Escenario Mar 12 12:30 UTC realista

```
T-30:00 · entra high window · fetch_calendar #1 · cache_ttl_check → expired → BLS HTTP call → cache March CPI · TTL 300s
T-29:30 · fetch_calendar #2 · cache_ttl_check → 30s < 300s → CACHE HIT · NO BLS call
... (mismo cache durante 60 polling cycles 30s × 30min = 60 calls · 0 BLS calls)
T-25:00 · primera vez TTL expira (300s) → BLS HTTP call → SAME March CPI → hash igual → aggressive_ttl=True → TTL=3600s
T+0:00 · BLS publica April CPI
T+0:30 · fetch_calendar · cache_ttl_check → 30s < 3600s → CACHE HIT · sigue retornando March CPI
T+15:00 · sale high window · sigue cache March CPI
T+60:00 · cache TTL expira (3600s) → BLS call → April CPI (1h LATE · SLA 120s violado x30)
```

**Mi M2 NO cierra SLA <120s** · solo arregla la condición de ventana, no la captura real.

### Fix M2-bis · approach

Bypass cache durante high window. En `bls_client.get_latest_actual(category, force_refresh=False)`:

```python
def get_latest_actual(self, category: str, force_refresh: bool = False) -> dict | None:
    series_id = SERIES_BY_CATEGORY.get(category)
    if not series_id:
        return None
    
    # [r152-M2-bis] Bypass cache si force_refresh (high window macro)
    if not force_refresh:
        ttl = 3600 if self._cat_aggressive_ttl.get(category, False) else 300
        last_fetch = self._cat_last_fetch_ts.get(category, 0.0)
        cached = self._cache.get(series_id)
        if cached and (time.time() - last_fetch) <= ttl:
            return self._build_result_from_cache(category, cached)
    
    # Force fresh BLS API call
    cached = self.fetch_series(series_id)
    if not cached:
        return None
    self._cat_last_fetch_ts[category] = time.time()
    # ... rest of pipeline
```

Y en `fmp_compat._sync_fetch()` cuando high window detectado:
```python
in_high_window = ...  # del helper M2
for cat in ("NFP", "CPI", "PCE", "UNEMPLOYMENT"):
    bls_actuals[cat] = self._bls.get_latest_actual(cat, force_refresh=in_high_window)
```

Esto hace que **durante T-30→T+15 ventana high**, cada fetch_calendar (30s interval) **fuerza HTTP call BLS**, no cache. Fuera de ventana: cache normal.

### Costo BLS API quota

- Sin fix: ~24 calls/día (cache 1h LOW)
- Con M2-bis fix: durante 45min × 4 events/mes = 180min × 2 calls/min = 360 calls/mes en bursts
- BLS quota con API key: 500 calls/día → suficiente · ~30 calls quota daily ya consumimos en LOW · 360 spread over 4 events/mes = ~12/event en spike · OK

---

## §3 · Otros findings Codex V2 (no nuevos)

| Finding | Severity | Status |
|---|---|---|
| C-02 BLS period validation | CRITICAL | M3 LOCKED hasta 22:05 UTC (ya plan) |
| C-03 BUG_NFP_DIM_ACTIVE | CRITICAL | M4 Lun 11 (ya plan) |
| C-06 paths absolutos | CRITICAL | M5 Lun 11 (ya plan) |
| HIGH-01 assert vs raise | HIGH | M5 (ya plan) |
| HIGH-02 systemd sandboxing | HIGH | M6 Mar 12 (ya plan) |
| HIGH-04 failed services | HIGH | M6 (ya plan) |
| H-03 heartbeat camuflage | HIGH | M5/M6 (ya plan) |
| H-06 auto-refill | HIGH | post-CPI (ya plan) |
| Wallet pubkeys + balances en bundle | HIGH | M1-bis sanitizar bundle |
| `_next_or_recent_tracked` TypeError naive ts | MEDIUM | M2-bis añadir TypeError catch |
| `gitleaks_reports/v2_clean.json` 1966 findings noisy | MEDIUM | post-CPI · split signal/noise |
| BLS stale semantics confusing | MEDIUM | M5 · `last_success_age_s` exponer |

---

## §4 · Veredictos Codex V2 ambos · resumen

| Auditor | Veredicto | Probabilidad 24h LIVE Mar 22 |
|---|---|---|
| Codex 1 | NO-GO | 45-60% (vs 30-45% original) |
| Codex 2 | NO-GO | 25-40% si LIVE actual · 40-55% si solo M3-M8 done |

Ambos coinciden:
- M1+M2 mejoran pero NO cierran NO-GO
- 2 críticos nuevos detectados (nginx + BLS TTL)
- Hay riesgo real durante CPI gate Mar 12

---

## §5 · Plan ajustado · M1-bis + M2-bis añadidos al roadmap

Roadmap original 8 milestones → ahora **10 milestones**:

| # | Milestone | Original | Updated | Status |
|---|---|---|---|---|
| M1 | Saneamiento secrets + endpoints | Sáb 9 11:00 | DONE | ✅ |
| **M1-bis** | **NEW · `/poly/` catch-all auth + admin deny** | — | **Sáb 9 12:00 UTC** | **URGENT** |
| M2 | Fix C-01 polling helper | Sáb 9 13:00 | DONE | ✅ |
| **M2-bis** | **NEW · BLS TTL bypass durante high window** | — | **Sáb 9 13:30 UTC** | **URGENT** |
| M3 | Fix C-02 BLS period validation | Dom 10 18:00 | scheduled | LOCKED hasta 22:05 |
| M4 | Fix C-03 BUG_NFP_DIM | Lun 11 12:00 | scheduled | |
| M5 | PATH_BASE refactor + assert→raise + heartbeat fix | Lun 11 24:00 | scheduled | |
| M6 | systemd cleanup + sandboxing | Mar 12 12:00 | scheduled | |
| **M7** | **CPI dry-run hard gate** | **Mar 12 12:30** | **HARD DEADLINE** | scheduled |
| M8 | Codex re-audit final | Vie 19 12:00 | scheduled | |
| **LIVE** | **microcapital $5-10** | **Mar 22 13:30 UTC** | TARGET | |

**Buffer original M1 (+7h) absorbe M1-bis + M2-bis** · timeline ON TRACK Mar 22.

---

## §6 · Pendientes por tu firma

1. **¿Apruebas M1-bis · nginx fix** (Enfoque A: deny `/poly/admin/` + auth_basic en `/poly/` general)?
2. **¿Apruebas M2-bis · BLS TTL bypass** (parameter `force_refresh=True` durante high window)?
3. **¿Procedo M1-bis + M2-bis HOY** (low-risk · low-LOC · pre-soak end)?
4. **¿Acepto que M2 actual queda VALIDATED PARCIAL** · cierre real require M2-bis?
5. **¿Recomendaciones nuevas Codex V2 (TypeError catch + balance snapshots scrub)** las añado a M5 o son urgent?

---

## §7 · Status actual

```
Sidecar PID 1486192 · uptime 1h 5min · RSS estable 111 MB
Soak T+1h aprox · M2 fix está corriendo OK pero SLA real NO garantizado
Bundle Codex v2 enviado · 2 outputs received NO-GO
Capital LIVE expuesto: $0
Tiempo restante target Mar 22: 12d 0h
```

**Sin tu firma**: no toco nginx ni bls_client · sigo silent monitoring.
**Con tu firma**: procedo M1-bis + M2-bis en próxima 1h · re-deploy + soak continúa.
