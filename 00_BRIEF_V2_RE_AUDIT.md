# 00_BRIEF_V2 · Codex re-audit · post M1+M2 fixes

**Para**: Codex (OpenAI · agente externo)
**De**: Marco vía Claude operativo
**Fecha**: 2026-05-09 · 14:55 UTC
**Asunto**: Re-audit V2 · evaluar si los fixes M1+M2 cierran los CRITICAL/HIGH del primer audit
**Bundle**: `codex_audit_2026-05-09_v2.tar.gz` · GitHub `mopito99/codex-audit-2026-05-09` (force-push commit nuevo)

---

## §0 · Mission

Hace ~7 horas devolviste 2 veredictos **NO-GO** sobre VelocityQuant V4-Alpha (Mar 12 LIVE microcapital target). Identificaste 6 CRITICAL + 6 HIGH + 5 MEDIUM + 2 LOW.

Marco aceptó NO-GO · postpone target a **Mar 22 13:30 UTC** · Gemma 4 31B firmó UNLOCKED arquitectura · sprint M1-M8 con fixes priorizados.

**Hoy (9-may) ya completamos M1 + M2**:
- M1 (saneamiento secrets/endpoints) · cerrado 11:00 UTC con tu hash GEMMA4-SR-QUANT-B31-M1-SANEAMIENTO-DONE-20260509T1100UTC
- M2 (Codex C-01 polling fix) · implementado + 11/11 tests PASS · Gemma firmó hash GEMMA4-SR-QUANT-B31-M2-VALIDATED-20260509T1345Z
- M3-prelim (Codex C-02 BLS period validation) · spec firmada 14:40 UTC · deploy bloqueado hasta T+12h soak M2 (22:05 UTC)

**Mission re-audit**: confirma o refuta que los fixes M1+M2 son técnicamente sólidos · cero filtros · enfocate en **regresiones** y en **lo que aún no fixamos** (M3-M7).

---

## §1 · Lo que ha cambiado vs primer audit

### M1 · Saneamiento (CLOSED 11:00 UTC)

| Tu finding original | Tu severity | Fix aplicado |
|---|---|---|
| **C-03b** FRED key leakeada en logs sample bundle | CRITICAL | FRED key rotada · vieja `95e369bf...` revoked verified DEAD via `curl 400 not registered` · nueva en `.config/fred/api_key` mode 600 |
| **C-04** Hot wallets + dashboards públicos | CRITICAL | nginx `/poly/audit/`, `/poly/pnl/`, `/poly/api/` ahora con `auth_basic` · `htpasswd_vq` mode 640 root:www-data · bcrypt -B · verified 401/200/401 |
| **C-05** Nginx claim "Basic Auth" pero NO en config | CRITICAL | Implementado realmente · ya no es claim falso |
| **M-02** httpx logs filtran query strings con keys | MEDIUM | Filter v3 en sidecar.py (líneas 55-95) · root cause: lazy `%s` con `httpx.URL` object · fix: coerce non-str args **solo si match secret pattern** (preserva `%d` int) |
| **M-01** `.bak` debris 33 files | MEDIUM | 13 shred -u en árboles productivos · 8 backups rollback emergency mode 600 7d retention |
| **Secrets adicionales detectados**: Anthropic key + Telegram bot | CRITICAL | Anthropic key revoked · Telegram bot ELIMINATED via BotFather · `.env.bak_pre_r66` shredded Newark + Dallas |
| Git history clean | - | Force-push `bfg`-style amended commit (1-commit repo) · Gitea+GitHub purgado · hash 71a51ca→37e4047 |

### M2 · Codex C-01 polling fix (VALIDATED 13:45 UTC)

Tu finding C-01: ventana `0 < sec_to_next_cached < 1800` se desactiva post-T=0 → captura BLS post-release no garantizada.

**Fix aplicado** (`code/poly_sidecar/sidecar.py:107-141 + 370-398`):

```python
# Helper nuevo:
def _next_or_recent_tracked(events, recent_window_s=900):
    """Ventana absoluta T-30min → T+15min · delta puede ser negativo."""
    now = dt.datetime.now(dt.timezone.utc)
    candidates = []
    for ev in events:
        if not FMPClient.is_tracked(ev): continue
        ts = dt.datetime.fromisoformat(ev.date.replace("Z","+00:00"))
        delta = (ts - now).total_seconds()
        if -recent_window_s <= delta <= 1800:
            candidates.append((delta, ev))
    if not candidates: return None, None
    candidates.sort(key=lambda x: abs(x[0]))
    return candidates[0][1], candidates[0][0]

# Refactor block polling:
if fmp.configured:
    cached_for_poll = fmp.cached_events()
    next_or_recent_ev, secs_window = _next_or_recent_tracked(cached_for_poll, 900)
    in_high_window = next_or_recent_ev is not None and -900 <= secs_window <= 1800
    poll_interval = 30 if in_high_window else 3600
    # ... fetch + log [P3.6.5-v2] HIGH_FREQUENCY si in_high_window
```

**Tests parametrizados nuevos** (`code/poly_sidecar/tests/test_polling_window.py`):
- 9 casos parametrizados (T-30min edge, T-1min, T+30s, T+119s SLA edge, T+5min, T+14:59, T+15:01 out, T+30min, T-30:01)
- 2 individuales (no_tracked_events, multiple_picks_closest_abs)
- **11/11 PASS** en 0.08s

### M3-prelim (LOCKED hasta 22:05 UTC)

C-02 fix DRAFT en `code/r-numbers/r152_M3_prelim_bls_period_validation.md`:
- Helper `_parse_data_period_to_bls()` para gate accept/reject
- 29 tests parametrizados pre-written en `staging_m3/`
- Deploy bloqueado per orden Gemma hasta soak M2 cierra

---

## §2 · Lo que NO ha cambiado (todavía)

| Tu finding | Severity | Estado | Plan |
|---|---|---|---|
| **C-02** BLS period validation | CRITICAL | LOCKED hasta 22:05 UTC | M3 deploy 22:10+ UTC |
| **C-03 (claim falso)** BUG_NFP_DIM_ACTIVE en sf_engine | CRITICAL | identificado · scheduled M4 | M4 Lun 11 12:00 UTC |
| **C-06** Tests con paths absolutos `/home/administrator/` | CRITICAL | scheduled M5 | M5 Lun 11 24:00 UTC |
| **HIGH-01** assert vs raise (Codex M-03) | HIGH | scheduled M5 (cleanup junto con paths) | Lun 11 24:00 UTC |
| **HIGH-02** systemd sandboxing | HIGH | scheduled M6 | Mar 12 12:00 UTC |
| **HIGH-04** failed services + fail2ban | HIGH | scheduled M6 | Mar 12 12:00 UTC |
| **H-03** error fallback heartbeat camuflage | HIGH | scheduled M5/M6 | Lun 11 |
| **H-06** auto-refill SOL/USDC | HIGH | scheduled post-CPI | Mar 13+ |
| **MEDIUM-01** forecasts.signed = hash pin no firma criptográfica | MEDIUM | aceptado (renombrar) | post-CPI |
| **MEDIUM-04** Newark mirror stale | MEDIUM | scheduled M6 verify | Mar 12 |

Roadmap completo en `code/r-numbers/r152_M2_evidencia.md` §9.Q3 y `r152_M2_prelim_polling_fix.md` §7.Q3.

---

## §3 · Áreas focus para tu re-audit

### A · Verificar fixes M1 son robustos (cero regresiones)

Cross-check específico para evitar repetir patrón [SAFETY-DIM]:
1. **httpx filter v3** en `sidecar.py:62-95` · ¿el regex `_REDACT_PATTERN` cubre todos los secret schemes (`api_key`, `registrationkey`, `token`, `secret`, `password`)?
2. **Filter coerce logic** en lines 75-87 · ¿hay edge case (e.g. `bytes` arg, `URL` con custom `__str__`) que rompa?
3. **nginx auth_basic** en `configs/nginx/inicio.velocityquant.io` · ¿location `/poly/api/` correctamente ANTES de `/poly/`? · ¿hay endpoints fuera de auth que deberían estar protected?
4. **htpasswd_vq mode 640** root:www-data · ¿bcrypt cost factor adecuado?

### B · Verificar fix M2 es correcto

Específicamente:
1. `_next_or_recent_tracked()` líneas 107-141 · ¿ventana `[-900, 1800]` cubre **todos** los escenarios CPI release?
2. ¿`min(|delta|)` selección correcta cuando hay 2 events cercanos al mismo time?
3. ¿`time_to_next_event()` (legacy `fmp_compat.py:259-278`) sigue siendo llamado en otro lugar? Debería ser solo el helper nuevo
4. Test edge cases que YO no consideré: events con `date` inválido, events con timezone naive, multi-day windows

### C · Lo NO fixed · ¿es aceptable temporalmente?

C-02 (BLS period validation) deploy bloqueado hasta 22:05 UTC por Gemma. **¿Es la decisión correcta?** O debería hacerse en paralelo con M2 soak?

### D · Nuevo finding mio durante M1: 
- `fmp.status: stale` con `fmp.errors=0` durante polling LOW (artefacto naming)
- Threshold interno `bls_client.py:102` 1800s vs polling LOW 3600s
- Fix planned post-M3 (cosmético)
- ¿Tú detectarías esto como CRITICAL/HIGH?

---

## §4 · Output esperado de tu re-audit V2

Mismo formato que primer audit + 3 secciones nuevas:

```
# CODEX RE-AUDIT V2 · 2026-05-09

## §0 · Veredicto binario · ¿LIVE Mar 22 13:30 UTC GO?

## §1 · Verification fixes M1 (¿closed?)
Para cada finding original M1 (C-03b, C-04, C-05, M-02, M-01, ...):
  - ¿FIXED · evidence file:line?
  - ¿REGRESSION introducida?
  - ¿Aceptable o sigue CRITICAL?

## §2 · Verification fix M2 (¿closed C-01?)
- ¿_next_or_recent_tracked() correct?
- ¿Tests cobertura suficiente?
- ¿Hard Gate Mar 12 alcanzable con este fix?

## §3 · Findings NUEVOS detectados en post-fix code
(Si los hay)

## §4 · Re-evaluation del NO-GO original
- Estaba bien tu NO-GO?
- ¿Ahora con M1+M2 cambiarías a GO?

## §5 · Top-N must-fix antes de Mar 22
(Lista priorizada · puede diferir del original)

## §6 · Probabilidad supervivencia 24h LIVE Mar 22
Original: 30-45%. Update?
```

---

## §5 · Reglas de juego (recordatorio)

1. **Brutal honesty obligatorio**. Sin diplomacia.
2. **Si Claude declaró DONE algo que no está**, flageaalo CRITICAL.
3. **No omitas tests reales** · si el código compila pero tests no existen para un branch crítico, dilo.
4. **Si crees que C-02 podría hacerse pre-Mar 22 sin el lock de Gemma**, dilo.
5. **Si encuentras nuevos secret leaks**, NEED_MORE_INFO + Marco rotará.

---

## §6 · Anexos en bundle

```
code/poly_sidecar/sidecar.py             ← M1 filter v3 + M2 helper polling (POST-FIX)
code/poly_sidecar/bls_client.py          ← [SAFETY-DIM] assert + SHA-256 cache TTL
code/poly_sidecar/log_rotator.py         ← M1 P5.0 nuevo
code/poly_sidecar/tests/test_polling_window.py ← M2 11 tests parametrizados
code/poly_sidecar/scripts/m7_sla_report.py ← M7 dry-run report generator
configs/nginx/inicio.velocityquant.io    ← auth_basic restored
systemd_units/poly_log_rotator.{service,timer} ← M1 P5.0
code/r-numbers/r151_codex_dual_audit_para_gemma4.md ← respuesta a tu primer audit
code/r-numbers/r152_M1_saneamiento_evidencia.md  ← M1 cierre evidencia (CLOSED)
code/r-numbers/r152_M2_prelim_polling_fix.md     ← M2 plan
code/r-numbers/r152_M2_evidencia.md              ← M2 cierre evidencia (VALIDATED)
code/r-numbers/r152_M3_prelim_bls_period_validation.md ← M3 plan (LOCKED)
gitleaks_reports/v2_clean.json           ← scan paranoid post-sanitize · 0 real secrets
```

---

## §7 · Status sistema actual (14:55 UTC)

```
Sidecar V4-Alpha:        🟡 Soak T+50min (M2 fix activo) · RSS 111MB stable
Liquidator V3.5 LIVE:    🟢 Active 1d 19h ininterrumpido
Capital LIVE expuesto:   $0
Próximo target LIVE:     Mar 22 13:30 UTC (post Mar 12 dry-run hard gate)
M3 deploy unlock:        Sáb 9 22:05 UTC (T+12h M2 soak close)
```

---

**SHA256 bundle v2**: (pending · re-package post-this-MD)
**URL repo Git**: https://github.com/mopito99/codex-audit-2026-05-09 (force-pushed v2 commit)
**URL bundle tar**: https://inicio.velocityquant.io/codex/codex_audit_2026-05-09_v2.tar.gz

**Esperando tu output del re-audit**.
