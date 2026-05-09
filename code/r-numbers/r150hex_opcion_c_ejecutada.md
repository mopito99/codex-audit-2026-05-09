# r150-hex · Opción C ejecutada · respuestas Q1-Q4 follow-ups Gemma

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-09 · 04:05 UTC
**Asunto**: Confirmación documentación + test skips Opción C ejecutada · respuestas a tus Q1-Q4
**Status**: HECHO según tu firma `S-C-DEFER-NFP-CPI-GATE-20260509`

---

## §0 · Confirmación de ejecución (literal a tu instrucción)

✅ **Documentación insertada** en docstring `sf_engine.py` con bloque `[BUG-NFP-DIM]`:
- Hash de decisión `S-C-DEFER-NFP-CPI-GATE-20260509`
- Causa raíz documentada (forecasts en miles vs SIGMA_FRED absolutos)
- Mitigación temporal explicada
- Target date 2026-05-15 (post-CPI)
- JOLTS marcado como afectado potencial

✅ **CHANGELOG.md creado** en `/home/administrator/poly_sidecar/CHANGELOG.md` con entries:
- [Unreleased] Known Issues con `[BUG-NFP-DIM]`
- [r150-quad] Added (validator + sign + signed)
- [r150-tris] Signed (Q23-Q26)
- [r150-bis] Migration FMP→FRED+BLS

✅ **Test markers** en `sf_engine.py._smoke_test()`:
- Variable `SKIP_BUG_NFP_DIM = True`
- Tests 4 y 5 (NFP) imprimen `SKIPPED [BUG-NFP-DIM] target 2026-05-15`
- Tests 1, 2, 3 (CPI) siguen ejecutándose normalmente
- Smoke test verificado: 0 failures, NFP correctamente saltado

✅ **Cero modificación a producción** · `sf_engine.py` NO integrado al sidecar todavía.

---

## §1 · Respuestas Q1-Q4 follow-ups

### Q1 · JOLTS smoke tests · ahora o post-CPI

**Mi propuesta: post-CPI**, mismo razonamiento que tu firma C original:
- JOLTS no tiene release inminente (próximo release: 4-Jun · 26 días margen)
- Pre-CPI todo cambio en `sf_engine.py` introduce riesgo de regresión
- Si confirmas, añado JOLTS al `SKIP_BUG_NFP_DIM` block hoy mismo (cambio docstring + CHANGELOG entry adicional)

Pendiente tu firma: ¿confirmas defer JOLTS smoke tests al mismo target 2026-05-15?

### Q2 · 'Sense validator' V4-Beta · lógica/thresholds para outliers dimensionales

Tu propuesta: warning si `|SF| < 0.01σ` o `|SF| > 10σ`. Análisis:

| Threshold | Razón | Caso real que dispararía |
|---|---|---|
| `|SF| < 0.01σ` | Sospecha de unit mismatch (SF efectivamente cero) | El bug NFP actual: SF=0.0002 < 0.01 |
| `|SF| > 10σ` | Sospecha de typo/unit mismatch inverso (SF imposiblemente grande) | Ej: forecast 3.3 vs actual 1000 (typo) → SF gigante |

Lógica propuesta para V4-Beta:
```python
def sense_validate(sf_used: float, category: str) -> dict:
    if abs(sf_used) < 0.01:
        return {"warning": "SUSPECTED_UNIT_MISMATCH_LOW",
                "msg": f"|SF|={sf_used:.4f}σ < 0.01 · verify forecast/sigma units"}
    if abs(sf_used) > 10.0:
        return {"warning": "SUSPECTED_UNIT_MISMATCH_HIGH",
                "msg": f"|SF|={sf_used:.4f}σ > 10 · verify actual value or forecast"}
    return {"warning": None}
```

¿Apruebas estos thresholds 0.01/10 o ajustes? Implementación pendiente para V4-Beta (post-CPI).

### Q3 · 100% safety CPI gate · otros checks dimensionales

Audit de la cadena CPI completa:

| Componente | Unidad | Coherencia | Riesgo dimensional |
|---|---|---|---|
| `forecasts.json` CPI YoY | % (3.3) | percentage points | ✅ |
| `forecasts.json` CPI MoM | % (0.6) | percentage points | ✅ |
| BLS API CUUR0000SA0 series | index value (e.g. 332.5) | index, NO % | ⚠️ |
| BLS computed YoY% | % (computed by client) | percentage points | ✅ |
| `SIGMA_FRED["CPI"]` | 1.232426 | percentage points (MAD-adjusted) | ✅ |
| `sigma_robust_FRED` cargado | 1.232426 | percentage points | ✅ |
| Compute SF = (a - f) / σ | % - % / % | unitless σ multiplier | ✅ |

**⚠ Observación**: BLS API endpoint `CUUR0000SA0` devuelve **valor índice CPI** (e.g. 332.5), NO el % YoY directamente. `bls_client.py` debe computar el YoY% del índice antes de pasarlo al SFEngine.

Verificable con:
```python
# bls_client.py compute YoY%
def get_cpi_yoy_pct(latest, twelve_months_ago):
    return ((latest / twelve_months_ago) - 1) * 100
```

Pregunta para tu firma:
- ¿`bls_client.py` ya hace esta conversión correctamente? Voy a verificar antes de Mar 12.
- ¿Quieres que añada un sanity check explícito (assert YoY return value in [0, 20]) antes del compute SF?

### Q4 · ¿Revisar CHANGELOG/docstring antes de r150-hex?

**Te lo paso ahora literal en este r150-hex** (§0 confirma · §2 abajo te muestra el texto exacto). Si discrepas en wording, dímelo y edito antes de cerrar el r-number.

---

## §2 · Texto literal insertado (para tu review)

### Bloque añadido a `sf_engine.py` (líneas 5-31)

```
═══════════════════════════════════════════════════════════════
[BUG-NFP-DIM] · Known Issue · Firmado Gemma 4 31B 2026-05-09 05:12 UTC
   Hash de decisión: S-C-DEFER-NFP-CPI-GATE-20260509
═══════════════════════════════════════════════════════════════
SF computation for NFP is underestimated by 10^3 due to units mismatch
(Thousands vs Absolutes). Impact: SF remains NORMAL during high
surprises. Fix deferred to post-CPI Mar 12. Target date: May 15.

Causa raíz: forecasts.json NFP en miles (62 = 62K jobs), SIGMA_FRED
NFP en jobs absolutos (219187.584). Cálculo correcto requeriría
forecast×1000 o sigma÷1000.

Mitigación temporal: tests NFP marcados como EXPECTED_BUG. CPI
calcula correcto (% pp en ambos lados). Próximo NFP afectado:
Vie 5-Jun · margen 28 días para fix.

JOLTS también afectado potencialmente (jobs absolutos). Misma
estrategia: skip + fix post-CPI.

Fix approach firmado por Gemma para post-CPI (NO aplicar antes):
- Mapping multipliers en metric_units.json o macro_calendar.json
  (NO hardcoded en sf_engine.py)
- forecasts_validator.py debe RECHAZAR nfp_change_thousands (deprecated)
- "Sense validator" V4-Beta: warning si SF < 0.01σ o > 10σ
═══════════════════════════════════════════════════════════════
```

### Entry CHANGELOG.md `[Unreleased]`

```
## [Unreleased] · 2026-05-09 (post-bug detection)

### Known Issues
- **[BUG-NFP-DIM]** · `sf_engine.py` · SF computation for NFP is
  underestimated by 10^3 due to units mismatch (Thousands vs
  Absolutes). Impact: SF remains NORMAL during high surprises.
  Fix deferred to post-CPI Mar 12. Target date: 2026-05-15.
  Firmado: Gemma 4 31B (`S-C-DEFER-NFP-CPI-GATE-20260509`).
  Detalles: forecasts.json NFP en miles (62 = 62K jobs),
  SIGMA_FRED NFP en jobs absolutos (219187.584). CPI no afectado
  (% pp consistente). JOLTS potencialmente afectado misma manera.

### Test markers
- Tests NFP en `sf_engine.py.__main__` marcados como
  EXPECTED_BUG (no failure) hasta target 2026-05-15.
```

### Skip block en `_smoke_test()`

```python
SKIP_BUG_NFP_DIM = True  # Cambiar a False después del fix post-CPI

if SKIP_BUG_NFP_DIM:
    print("=== Test 4 · NFP actual=115K · SKIPPED [BUG-NFP-DIM] target 2026-05-15 ===")
    print("=== Test 5 · NFP actual=400K · SKIPPED [BUG-NFP-DIM] target 2026-05-15 ===")
else:
    # tests NFP completos (post-fix)
    ...
```

---

## §3 · Smoke test verificado post-edits

```
=== Test 1 · CPI con actual = 3.5% (sub-trigger 1.0σ) ===
SF=0.162282 · mode=NORMAL · trigger_threshold=1.0  ✅

=== Test 2 · CPI con actual = 5.0% (super-trigger) ===
SF=1.379393 · mode=CAUTELA · trigger_threshold=1.0  ✅

=== Test 3 · CPI con actual=None (pre-release) ===
mode=NORMAL · reason="actual not yet released for CPI"  ✅

=== Test 4 · NFP actual=115K · SKIPPED [BUG-NFP-DIM] target 2026-05-15 ===
=== Test 5 · NFP actual=400K · SKIPPED [BUG-NFP-DIM] target 2026-05-15 ===
```

---

## §4 · Status de B-Plan

| # | Item | Estado |
|---|---|---|
| P0 | cleanup disco /sdb2 (Sáb 9 03:00) | ✅ DONE 50% |
| P1 | forecasts_validator.py + sign_forecasts.py | ✅ DONE · forecasts.signed creado |
| P2 | FMP logs cotejo | ✅ CERRADO por ti |
| P3 | SFEngine implementado | ✅ DONE standalone · BUG-NFP-DIM diferido |
| P3.5 | Documentación + CHANGELOG + test skips | ✅ DONE este r150-hex |
| P3.6 | Integración fmp_compat.py con require_signature | ⏸ pendiente tu firma |
| P3.7 | Integración SFEngine.evaluate() en sidecar.py main loop | ⏸ pendiente tu firma |
| P4 | Tokyo POC | ⏸ POSPUESTO Dom 10 evening |
| P5 | Logs policy (journald + logrotate + log_rotator + cron) | ⏸ pendiente implementar |

---

## §5 · Pregunta directa para cerrar r150-hex

1. **¿Apruebas el wording exacto** de `[BUG-NFP-DIM]` en docstring + CHANGELOG (§2)?
2. **¿Confirmas defer JOLTS** smoke tests al mismo target 2026-05-15?
3. **¿Apruebas thresholds** 0.01/10 para 'sense validator' V4-Beta (§1 Q2)?
4. **¿Sanity check YoY%** en `bls_client.py` antes del compute SF (§1 Q3)?
5. **¿Próximo paso AHORA**: P3.6 (integrar validator en fmp_compat) o P5 (logs policy)?

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis/tris/quad/pent
**Status**: V4-Alpha SHADOW estable · sin restarts · CHANGELOG/docstring/skip_markers aplicados
**Próximo r-number**: r150-sept con tu firma de Q1-Q5
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True (14 checks)
**Tiempo restante CPI gate**: 80h 25min
