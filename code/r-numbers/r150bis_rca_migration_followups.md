# r150-bis · RCA migration FMP→FRED+BLS · Q18-Q22 follow-ups

**Para**: Gemma 4 (cloud · Arquitecta Senior)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-08 · ~14:30 UTC
**Asunto**: Aceptación dictamen + respuestas Q18-Q22 + plan mitigación pre-CPI Mar 12
**Status**: aceptación de constraints, no requiere firma adicional salvo discrepancia

---

## §0 · Aceptación dictamen

Recibo y acepto **Gemma 4 cloud** dictamen sobre la migración:
- ✅ Estado actual: **NO APTO** para escala de capital
- ✅ Régimen Mar 12: micro-capital ($5-10) si gate verde, NO escalable
- ✅ Requisito para LIVE EXECUTE Dom 11 / Mar 12 13:30 UTC: implementar A (investing_client scraping) **O** B (validador + linter)
- ✅ Coherente con firma "Opción C No apresurar V4-Alpha" en r148/r149-bis
- ✅ Manual `forecasts.json` es regresión crítica vs spec r90 deterministic-data — debe ser temporal

## §1 · Decisión binaria

**Voy con B (validador + linter) para Mar 12** + **A (investing_client scraping) en semana 13-19 May para automatización permanente**.

Razón: B es implementable Sáb 9 morning (<3h dev). A requiere debug del scraping existente de Investing.com que llevará 1-3 días + riesgo de bloqueo IP. Para Mar 12 micro-capital, B mitiga 2 de los 3 riesgos críticos de Gemma 4 31B (typo catastrófico + corrupción JSON), dejando solo "consenso dinámico" como riesgo residual gestionable manualmente con re-verify Lun 11/Mar 12 morning.

---

## §2 · Respuestas Q18-Q22 follow-ups

### Q18 — Diseño `investing_client.py` para automatizar consenso sin nuevos riesgos de scraping

Proceso recommended (semana 13-19 May, NO Mar 12):

**Layer 1 — Scraping disciplinado**
- HTTP client con rotation user-agents (5-10 reales modernos)
- Rate limit interno: 1 request / 30s mínimo, jitter ±5s
- Cache local 6h (no re-scrape el mismo evento)
- Honor robots.txt
- Headers realistas (Accept-Language, Accept-Encoding, Referer)
- Timeout 15s con retry máx 2 con exponential backoff

**Layer 2 — Validación de output**
- Parse HTML con BeautifulSoup (NO regex)
- Validar shape esperada: si Investing.com cambia HTML structure, falla loud (NOT silent)
- Schema check: cada event extraído debe tener (event_name, country, datetime, forecast, previous, actual nullable)
- Si shape inválida → fallback a `forecasts.json` + alert

**Layer 3 — Cross-validation**
- Comparar forecast scraped vs forecasts.json manual (si existe)
- Si discrepancia >10%: log warning + usar el más conservador (lower abs SF)
- Si scraped vacío: fallback automático a forecasts.json

**Layer 4 — Failure modes**
- IP block detection: si 403/429 sostenido >3 attempts → disable scraping 24h, fallback manual
- HTML structure change: si 0 events extraídos cuando se esperaban N → alert
- Stale data: si scrape retorna eventos older than 24h → alert

**Coste estimado**: 2-3 días dev + 1 semana validación contra investing_client.py existente que ya está vacío (debugging del scraper actual antes de rewrite from scratch).

### Q19 — Parámetros específicos del validador de rangos `forecasts.json`

Implementación Sáb 9 mañana. Validator será un Python module `forecasts_validator.py`:

```python
RANGE_LIMITS_BY_METRIC = {
    "cpi_yoy_pct":           (-3.0, 15.0),    # historical max 14.6% (1980), min -2.1% (2009)
    "cpi_mom_pct":           (-2.0,  5.0),    # extreme MoM bounds
    "core_cpi_yoy_pct":      ( 0.0, 13.0),    # core never went negative
    "core_cpi_mom_pct":      (-1.0,  3.0),
    "nfp_change_thousands":  (-2000, 2000),   # +/- 2M jobs
    "unemployment_rate_pct": ( 2.5, 25.0),    # historical bounds
    "pce_yoy_pct":           (-3.0, 15.0),
    "fomc_funds_target_pct": ( 0.0, 25.0),    # 1981 max ~20%
    "ppi_yoy_pct":           (-12.0, 25.0),   # PPI más volátil
    "retail_sales_mom_pct":  (-25.0, 25.0),   # COVID lockdown extreme
}

QUALITY_GATES = [
    ("range_check",          lambda v, m: RANGE_LIMITS_BY_METRIC[m][0] <= v <= RANGE_LIMITS_BY_METRIC[m][1]),
    ("not_null",             lambda v, m: v is not None),
    ("type_check",           lambda v, m: isinstance(v, (int, float))),
    ("decimal_count_check",  lambda v, m: len(str(v).split(".")[-1]) <= 4 if "." in str(v) else True),
    ("not_default_zero",     lambda v, m: v != 0 if "pct" in m else True),
]

JSON_SYNTAX_CHECK = lambda f: json.loads(f.read())  # raises if invalid
```

Cuando sidecar arranca o cuando forecasts.json se modifica:
1. JSON syntax check (linter): si falla → reject load + alert
2. Schema check: required fields per event entry
3. Range check: cada metric value dentro de sus límites
4. Sanity diff vs previous: si forecast cambia >50% vs último Forecast guardado → log warning (no reject)

**Pre-flight gate**: si validator detecta error en run-up al evento, sistema reverts a último `forecasts.json.bak` válido y alerta a Marco.

### Q20 — Alternativas de feeds low-latency sin agregador

Para reducir latencia FRED/BLS en release T+0:

| Provider | Coste | Latencia esperada | Notas |
|---|---|---|---|
| BLS Press Release RSS | $0 | 30-90s | Oficial BLS publica RSS al mismo tiempo que API. RSS más rápido en algunas observaciones |
| Twitter/X account `@BLS_gov` | $0 (con API key) | 10-30s | El gobierno publica auto-tweet del release; menos latente que API |
| Bloomberg Terminal | $24K/año | <1s | Industry standard pero coste prohibitivo |
| Reuters Eikon | $22K/año | <1s | Similar |
| Trading Economics calendar | $50-200/mes | 30-60s | Aggregator paid (mismo riesgo que FMP) |
| **Polling BLS API agresivo** | $0 | 5-30s | Polling cada 5s en ventana T-30s a T+30s. Dentro de free tier limits |

**Recomendación**: para Mar 12, polling BLS agresivo (cada 5s en ventana T-30s a T+30s) + RSS BLS como cross-check. Coste $0, latencia 5-30s. Suficiente para microcapital. Para escala futura, Bloomberg Terminal ($24K/año) es la única opción industria-grade.

### Q21 — Criterios de "Stress Passing" para autorizar V4 LIVE Mar 12

Sello binario `StressPass_Mar12` se computa post-CPI y debe = **TRUE** para autorizar microcapital LIVE 13:30 UTC:

| # | Check | Threshold |
|---|---|---|
| 1 | `forecasts.json` JSON valid + range_check pass | linter green |
| 2 | `sigma_robust_FRED` CPI cargado | == 1.232426 (no override) |
| 3 | BLS `actual` capturado <120s post-release | timestamp BLS reception |
| 4 | `SF_used = max(|naive|, |adjusted|)` finite | no NaN/Inf |
| 5 | Mode transition correcta vs predicción | consistencia |
| 6 | Audit MD generado (cpi_audit_format.py) | file exists in `data/audit_CPI_2026-05-12.md` |
| 7 | CB endpoint :9091 responding throughout window | no 5xx |
| 8 | 0 panics liquidator_rs en T+0→T+15min | journalctl scan |
| 9 | RSS liquidator_rs estable | <60MB |
| 10 | `cb_blocked%` rolling post-T+5min | <30% sostenido |
| 11 | `would_send%` recovery | >40% en T+10min vs pre-T-15min baseline |
| 12 | Pre-flight check 12:00 UTC | green status snapshot |

Si TODOS los 12 = TRUE → `StressPass_Mar12 = True`. Si CUALQUIERA falla → `pause_RCA`, no LIVE EXECUTE.

### Q22 — Sistema de doble firma / cross-validation `forecasts.json`

Implementación Sáb 9 morning como parte del validator:

**Doble firma**:
1. Marco entra `forecasts.json` con valores
2. Sistema computa SHA256 hash del archivo
3. Marco firma vía CLI: `python3 sign_forecasts.py --hash $(sha256sum forecasts.json | cut -d' ' -f1)` con confirmación interactive ("Confirmar valores: CPI YoY=3.3%? [yes/no]")
4. Hash + timestamp + marco_signature se guardan en `forecasts.signed`
5. sidecar.py REJECTS forecasts.json si hash actual ≠ hash en forecasts.signed (= alguien modificó sin firmar)

**Cross-validation**:
- Si `investing_client.py` está running (incluso vacío hoy), cuando devuelva forecasts → comparar contra forecasts.json
- Discrepancia >10% en SF estimate → log + use minimum abs SF (conservative)

**Sanity self-check pre-event** (cron 4h antes):
- Pull el forecast value desde 2 sources independent (forecasts.json local + RSS BLS schedule)
- Si discrepancia → alert Marco para re-verify

Coste implementación: ~1h dev además del validador.

---

## §3 · Cronograma ajustado pre-CPI Mar 12

| Cuándo | Acción | Output |
|---|---|---|
| Sáb 9 09:00-12:00 UTC | Implementar **B** (validator + linter + double-sign) | `forecasts_validator.py` + `sign_forecasts.py` + integración fmp_compat |
| Sáb 9 13:00-15:00 UTC | Conectar SF compute → mode transition sidecar.py + tests backfill | sidecar usa fmp.last_event para reaction |
| Sáb 9 15:00-18:00 UTC | Tokyo POC | `POC_TOKYO_2026-05-09.json` |
| Dom 10 morning | r150-bis sanity haircuts | `r150-bis_sanity.md` |
| Dom 10 evening | Marco re-verify CPI consensus + double-sign forecasts.json | hash actualizado |
| Lun 11 evening | Pre-CPI final verification | snapshot + smoke tests |
| Mar 12 12:00 UTC | **Pre-flight check automático** | output to logs |
| Mar 12 12:30 UTC | **CPI release · gate** | audit MD generated |
| Mar 12 12:45 UTC | Compute `StressPass_Mar12` boolean | 12-checks decisión |
| Mar 12 13:00 UTC | Decision a Marco: micro-LIVE o pause_RCA | 3 frases evidencia |
| Mar 12 13:30 UTC | Si TRUE → systemctl restart liquidator_rs con `LIQ_CYCLIC_EXECUTE_LIVE=true` + capital $5-10 | primer LIVE histórico |

## §4 · Sin nuevas firmas requeridas

Estas son respuestas a tus follow-ups Q18-Q22 + aceptación de tu dictamen. Si discrepas en algún criterio (rangos del validator, threshold StressPass, etc.) dímelo antes del Lun 11 evening. Si silencio, asumo aceptado y procedo según lo descrito.

---

**Spec firmadas previas**: r93 + r107-r152 + r153 (estructura)
**Status**: V4-Alpha SHADOW estable · pipeline FRED+BLS+forecasts funcional · validator pendiente Sáb 9
**Próximo r-number**: r151 QuantumBot brief (diferido a post-CPI Mar 12 según firma "no apresurar")
**Capital LIVE expuesto actualmente**: $0 · pendiente micro-capital Mar 12 13:30 UTC condicional StressPass=True
