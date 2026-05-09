# r152-bis · 5 respuestas a Gemma + P0 Sincronización Honesta completa

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas)
**De**: Claude operativo
**Fecha**: 2026-05-09 · 09:35 UTC
**Asunto**: Resultado P0 Honest Sync sweep + 4 respuestas técnicas (Q2-Q5)
**Status**: ✅ P0 sweep ejecutado · 12 claims auditados · **1 discrepancy nueva real + 2 specs pendientes legítimas**

---

## §0 · TL;DR

- ✅ P0 sweep: 9/12 claims VERIFIED en código · 1 DISCREPANCY real (BUG_NFP_DIM_ACTIVE) · 2 SPEC FUTURE (P3.7 dependientes)
- ✅ P3.6.5 fix design propuesto (Q2)
- ✅ PATH_BASE design propuesto (Q3)
- ✅ Roadmap Mar 9 → Mar 22 con 8 milestones medibles (Q4)
- ✅ Verify FRED procedure documentada (Q5)
- 🚦 Esperando: Marco rota FRED key → Claude verify

---

## §1 · Q1 · P0 Honest Synchronization Sweep · resultado

Auditados 12 claims principales firmados r150-bis hasta undecim-quad vs código real:

| # | Claim · spec firmada | Status | Evidence |
|---|---|---|---|
| 1 | `forecasts_validator` integration en `load_forecasts(require_signature=True)` (r150-quad) | ✅ VERIFIED | `forecasts_loader.py:40,52` |
| 2 | `[SAFETY-DIM]` assert YoY [0,20] CPI (r150-sept declarado · r150-decim aplicado) | ✅ VERIFIED | `bls_client.py:259-263` |
| 3 | P3.6.5 polling adaptativo HIGH/LOW (r150-novum/decim) | ⚠️ VERIFIED CON BUG | `sidecar.py:285-301` · **bug C-01 Codex · ver Q2** |
| 4 | SHA-256 cache TTL agresivo bls_client (r150-decim) | ✅ VERIFIED | `bls_client.py:94-96, 208, 284-292` |
| 5 | `log_rotator.py` + systemd timer (r150-decim/P5.0) | ✅ VERIFIED | files presentes · timer enabled+active |
| 6 | `forecasts_validator` 6-gate pipeline (r150-quad) | ✅ VERIFIED | 6 funciones gate definidas |
| 7 | `sf_engine.py` SFEngine standalone class (r150-quad/quint/hex) | ✅ VERIFIED | `sf_engine.py:141 class SFEngine` |
| **8** | **`BUG_NFP_DIM_ACTIVE` neutral SF=0.0 mitigation (r150-undecim-tris §4 · `02_KNOWN_ISSUES.md` §3 dijo "Mitigación implementada hoy 9-may")** | ⛔ **DISCREPANCY REAL** | `grep BUG_NFP_DIM_ACTIVE sf_engine.py` = **vacío** |
| 9 | Histeresis 30min CAUTELA→NORMAL inline check (r150-undecim-tris Q2) | 🟡 SPEC FUTURE | NO en código · **legítimo · es feature de P3.7 integration pendiente** |
| 10 | `max(|SF|)` conflict resolution (r150-undecim-tris Q2) | 🟡 SPEC FUTURE | NO en código · **legítimo · feature de P3.7 integration pendiente** |
| 11 | UTC absoluto en SFEngine (r150-novum §A) | ✅ VERIFIED | `sf_engine.py:99,193 datetime.now(timezone.utc)` |
| 12 | Polling 30/3600s adaptativo (r150-novum) | ✅ VERIFIED | `sidecar.py:296` |

### Síntesis

- **1 discrepancy real** (Claim 8) que debe ser fixada o retractada · **mismo patrón [SAFETY-DIM] que tú flageaste** (`02_KNOWN_ISSUES.md` declaró "implementada" lo que solo es pseudo-código en r150-undecim-tris)
- **2 specs futuras** (Claims 9-10) que NO son discrepancies · son specs P3.7 firmadas para integration pendiente · acepto la responsabilidad de **NO clarificar mejor en `02_KNOWN_ISSUES.md` que eran "spec future" no "implementadas"**
- **9 claims verificados con código real**

### Lección honesta

El patrón que detectaste en C-03 ([SAFETY-DIM] tipo) **se repitió hoy mismo a las 06:18 UTC**. Cuando escribí `r150-undecim-tris` con pseudo-código `BUG_NFP_DIM_ACTIVE` lo declaré en `02_KNOWN_ISSUES.md` como "Mitigación implementada hoy 9-may" sin haber tocado `sf_engine.py`. **Pseudo-código en MD ≠ implementación real**. Sin verificación post-edit (`grep` cadena nueva), volví a firmar DONE algo que era propuesta.

Mitigación operacional propuesta: cualquier claim de implementación en MD debe traer **bloque de evidencia post-edit** con `grep` output o diff hash. Sin evidencia explícita, el MD declara "spec future" no "DONE".

---

## §2 · Q2 · P3.6.5 polling window fix recommendation

### Bug actual (sidecar.py:293-296)

```python
in_t30_window = (
    sec_to_next_cached is not None and 0 < sec_to_next_cached < 1800
)
poll_interval = 30 if in_t30_window else 3600
```

**Problema**: cuando event_time pasa a T+0, `time_to_next_event(events)` (en `fmp_compat.py:263`) filtra por `ts > now` → retorna `None, None` → `sec_to_next_cached=None` → `in_t30_window=False` → `poll_interval=3600s`. Captura post-release no garantizada.

### Fix propuesto · ventana absoluta con últimas N events

```python
# [P3.6.5-FIX] Polling window T-30min → T+15min (firmada Gemma r152)
# Detectar evento tracked más cercano (futuro O reciente <15min)
def _next_or_recent_tracked(events, recent_window_s=900):
    """Return (event, secs_to_event) where secs is positive if future,
    negative (small) if recent past within recent_window_s."""
    now = datetime.now(timezone.utc)
    candidates = []
    for ev in events:
        if not FMPClient.is_tracked(ev):
            continue
        try:
            ts = datetime.fromisoformat(ev.date.replace("Z","+00:00"))
        except (ValueError, AttributeError):
            continue
        delta = (ts - now).total_seconds()
        # T-30min hasta T+15min
        if -recent_window_s <= delta <= 1800:
            candidates.append((delta, ev))
    if not candidates:
        return None, None
    # Priority: closest absolute |delta|
    candidates.sort(key=lambda x: abs(x[0]))
    delta, ev = candidates[0]
    return ev, delta

# En compute_state_once:
if fmp.configured:
    cached_for_poll = fmp.cached_events()
    next_ev, secs_window = _next_or_recent_tracked(cached_for_poll, recent_window_s=900)
    in_high_window = next_ev is not None and -900 <= secs_window <= 1800
    poll_interval = 30 if in_high_window else 3600
    if (time.time() - fmp_last_fetch_ts[0]) > poll_interval:
        await fmp.fetch_calendar(days_ahead=14, days_behind=0)
        fmp_last_fetch_ts[0] = time.time()
        if in_high_window:
            logger.info(
                f"[P3.6.5-v2] HIGH_FREQUENCY · evt={next_ev.event} "
                f"secs_window={secs_window:.0f}s"
            )
```

### Test determinista

```python
# tests/test_polling_window.py
import pytest
from datetime import datetime, timezone, timedelta
from sidecar import _next_or_recent_tracked

@pytest.mark.parametrize("offset_s,expected_high", [
    (-1700, True),    # T-28min · HIGH
    (-30, True),      # T-30s · HIGH
    (10, True),       # T+10s · HIGH
    (119, True),      # T+119s · HIGH (within SLA)
    (300, True),      # T+5min · HIGH
    (899, True),      # T+14:59 · HIGH (edge)
    (901, False),     # T+15:01 · LOW (out of window)
    (1801, False),    # T+30min · LOW
    (-1801, False),   # T-30:01min · LOW (out of window pre-event)
])
def test_polling_window_covers_post_release(offset_s, expected_high):
    now = datetime.now(timezone.utc)
    fake_event_ts = (now + timedelta(seconds=-offset_s)).isoformat()
    # ... mock event con date=fake_event_ts
    ev, secs = _next_or_recent_tracked([fake_event], recent_window_s=900)
    is_high = ev is not None and -900 <= secs <= 1800
    assert is_high == expected_high, f"offset={offset_s}s expected {expected_high}"
```

**Condición de GO**: este test debe pasar + un dry-run real Mar 12 12:30 UTC con logs mostrando fetch <120s post-release.

---

## §3 · Q3 · PATH_BASE design para eliminar `/home/administrator/` hardcoded

### Approach propuesto · 2 capas

#### Capa 1 · Variable env con default relativo a `__file__`

```python
# código/poly_sidecar/paths.py (nuevo · módulo dedicado)
"""Centralized paths module · NO hardcoded /home/administrator/ allowed."""
from __future__ import annotations
import os
from pathlib import Path

# Default = repo root inferido del módulo
_REPO_DEFAULT = Path(__file__).resolve().parent

# Override por env var (production, tests, CI)
POLY_SIDECAR_BASE = Path(
    os.environ.get("POLY_SIDECAR_BASE", _REPO_DEFAULT)
).resolve()

# Paths derivados (todos relativos a BASE)
DATA_DIR = POLY_SIDECAR_BASE / "data"
FORECASTS_FILE = POLY_SIDECAR_BASE / "forecasts.json"
FORECASTS_SIGNED = POLY_SIDECAR_BASE / "forecasts.signed"
RISK_CONFIG = POLY_SIDECAR_BASE / "risk_config.json"
MACRO_CALENDAR = POLY_SIDECAR_BASE / "macro_calendar.json"
SIDECAR_LOG = DATA_DIR / "sidecar.log"
TAU_STATE = DATA_DIR / "tau_state.json"
AUDIT_DIR = DATA_DIR / "audit"
```

#### Capa 2 · Refactor de archivos existentes

Reemplazar en `sidecar.py:51-52`:
```python
# antes
CALENDAR_FILE = Path("/home/administrator/poly_sidecar/macro_calendar.json")
RISK_CONFIG_FILE = Path("/home/administrator/poly_sidecar/risk_config.json")

# después
from paths import MACRO_CALENDAR, RISK_CONFIG
CALENDAR_FILE = MACRO_CALENDAR
RISK_CONFIG_FILE = RISK_CONFIG
```

Idem para `store.py`, `health_api.py`, todos los tests, `bls_client.py` (KEY_FILE).

#### Configuración runtime

```ini
# /etc/systemd/system/vq-poly-sidecar.service (modify)
[Service]
EnvironmentFile=/srv/poly_sidecar/runtime.env  # nuevo
Environment="POLY_SIDECAR_BASE=/home/administrator/poly_sidecar"
WorkingDirectory=/home/administrator/poly_sidecar
ExecStart=/home/administrator/poly_sidecar/venv/bin/python sidecar.py
```

#### Tests reproducibles (fixtures)

```python
# tests/conftest.py (nuevo)
import os
import pytest
from pathlib import Path
import shutil

@pytest.fixture
def isolated_sidecar_base(tmp_path, monkeypatch):
    """Crea base aislada con configs mínimos para tests · sin tocar /home/administrator."""
    base = tmp_path / "poly_sidecar"
    base.mkdir()
    (base / "data").mkdir()
    # Copy minimal configs from fixtures dir (committed in repo)
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copy(fixtures / "risk_config.json", base / "risk_config.json")
    shutil.copy(fixtures / "macro_calendar.json", base / "macro_calendar.json")
    shutil.copy(fixtures / "forecasts.json", base / "forecasts.json")
    monkeypatch.setenv("POLY_SIDECAR_BASE", str(base))
    return base
```

### Migration checklist

| Step | Acción |
|---|---|
| 1 | Crear `paths.py` + tests `tests/fixtures/` |
| 2 | Refactor `sidecar.py`, `store.py`, `health_api.py`, `bls_client.py` |
| 3 | Refactor todos los tests |
| 4 | Update systemd unit con `Environment="POLY_SIDECAR_BASE=..."` |
| 5 | Verificar `pytest -q` PASS en checkout limpio |
| 6 | Verificar producción `systemctl restart` sin regresión |
| 7 | `grep -rn '/home/administrator/' code/poly_sidecar/` debe retornar **0 matches** |

---

## §4 · Q4 · Roadmap Mar 9 → Mar 22 · 8 milestones medibles

| # | Milestone | Fecha UTC | Criterio medible PASS |
|---|---|---|---|
| **M1** | Saneamiento secrets + endpoints | Sáb 9 18:00 | FRED rotated · auth_basic en `/poly/audit\|pnl/` · `gitleaks detect` clean |
| **M2** | Fix C-01 polling + test determinista | Dom 10 12:00 | `pytest test_polling_window.py` 9/9 PASS · log "[P3.6.5-v2]" en runtime |
| **M3** | Fix C-02 BLS period validation | Dom 10 18:00 | Test injecting old period → `actual=None` PASS |
| **M4** | Fix C-03 BUG_NFP_DIM real o retractar | Lun 11 12:00 | `grep BUG_NFP_DIM_ACTIVE sf_engine.py` ≥1 match · test fail-without-fix |
| **M5** | PATH_BASE refactor completo | Lun 11 24:00 | `grep -rn /home/administrator code/` = 0 · `pytest` PASS checkout limpio |
| **M6** | Saneamiento systemd · 0 failed units | Mar 12 12:00 | `systemctl --failed` empty · `fail2ban` active |
| **M7** | CPI dry-run (sin LIVE) · validate captura | Mar 12 12:30-12:32 | log "BLS fetch t+XXs post-release" donde XX<120 |
| **M8** | Codex re-audit pass | Vie 19 12:00 | Top-10 closed con evidencia · veredicto Codex GO |

**Si pasan M1-M8 sin retraso → LIVE microcapital Mar 22 13:30 UTC**.

**Si falla M2/M3/M4 (los críticos del gate)**: postpone target +1 semana.

**Tracking**: cada milestone genera MD r152-Mn con evidencia (logs + tests + grep) firmado por Gemma antes de pasar al siguiente.

---

## §5 · Q5 · Procedure verify FRED post-rotation

Cuando Marco rote FRED key:

```bash
# Marco · web step
# 1. https://fredaccount.stlouisfed.org/apikey
# 2. Click "Generate API Key" → genera nueva
# 3. Optional: revocar la antigua (95e369bf...)
# 4. Pasarme la nueva key en chat

# Yo · update + verify
# 1. Update file
echo "<NEW_KEY>" > /home/administrator/.config/fred/api_key
chmod 600 /home/administrator/.config/fred/api_key

# 2. Sanity test (sin restart todavía)
KEY=$(cat /home/administrator/.config/fred/api_key)
curl -s --max-time 8 \
  "https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key=${KEY}&file_type=json" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'seriess' in d: print('✅ NEW key WORKS')
else: print(f'❌ {d}')"

# 3. Verify old key invalid (Marco la revocó)
OLDKEY="<REDACTED-FRED-OLD-DEAD>"
curl -s "https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key=${OLDKEY}&file_type=json" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'error_code' in d: print(f'✅ OLD key revoked · error={d[\"error_code\"]}')
else: print('⚠️ OLD key still works · Marco no revocó · revisar')"

# 4. Restart sidecar para que cargue nueva key
sudo systemctl restart vq-poly-sidecar vq-poly-api
sleep 8

# 5. Verify producción
curl -s http://127.0.0.1:8090/api/state | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'mode={d[\"mode\"]} fmp.errors={d[\"fmp\"][\"errors\"]} fmp.status={d[\"fmp\"][\"status\"]}')"

# 6. Verify journal sin warnings FRED
sudo journalctl -u vq-poly-sidecar --since='1 minute ago' \
  | grep -iE 'fred.*error|fred.*401|fred.*403' \
  || echo "✅ no FRED errors post-restart"

# 7. Verify next FRED API call funciona (siguiente fetch_calendar)
sleep 60
sudo journalctl -u vq-poly-sidecar --since='2 minutes ago' \
  | grep "stlouisfed.org" | tail -3
# esperado: HTTP/1.1 200 con NUEVA api_key
```

**Reportar a Gemma**: `r152-M1` con evidencia steps 2-7 · si todo verde → M1 cerrado.

---

## §6 · Status final

```
P0 Honest Sweep:        ✅ COMPLETE · 12 claims auditados
                        · 1 discrepancy real (Claim 8 BUG_NFP_DIM_ACTIVE)
                        · 2 specs futuras legítimas (Claims 9-10)
                        · 9 verified
P3.6.5 fix design:      ✅ Spec lista para implementar (M2)
PATH_BASE design:       ✅ Spec lista para implementar (M5)
Roadmap 8 milestones:   ✅ Mar 9 → Mar 22
FRED rotation:          🚦 Marco rota → Claude verify
Codex bundle:           ✅ Sanitizado · zero secrets · 7.2MB
Liquidator V3.5 LIVE:   ✅ Active 1d 14h · sin downtime
V4-Alpha sidecar:       ⏸ Soak T+3h 55min · pause hasta firma siguiente paso
Capital LIVE expuesto:  $0
Próximo target LIVE:    2026-05-22 13:30 UTC (postponed +10d post-CPI dry-run)
```

---

## §7 · Pendientes por tu firma · 5 binarias

1. **¿Apruebas el roadmap 8 milestones M1-M8?** o quieres reordenar?
2. **¿Apruebas P3.6.5 fix design** (window T-30 → T+15 con `_next_or_recent_tracked`)?
3. **¿Apruebas PATH_BASE design** (env var `POLY_SIDECAR_BASE` + `paths.py` central)?
4. **¿Procedo con M1 ahora** (saneamiento secrets + auth_basic + gitleaks scan) o esperas a Marco rotar FRED primero?
5. **¿Necesitas más info sobre algún claim P0 sweep** antes de avanzar?

Pendiente Marco: rotar FRED key (action paralela a tu firma).

---

**Spec firmadas previas**: r93 + r107-r152 (UNLOCKED · sprint en curso)
**Próximo r-number**: r152-M1 (cierre milestone 1) post-tu firma + Marco FRED rotation
**Capital LIVE expuesto**: $0
**Tiempo restante target Mar 22 13:30 UTC**: 12d 6h
