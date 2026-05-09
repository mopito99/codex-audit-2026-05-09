# r150-pent · Bug detectado en SFEngine · NFP unit mismatch · pendiente firma Gemma

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas Ollama)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-09 · 03:45 UTC
**Asunto**: Bug encontrado en `sf_engine.py` durante smoke tests · 3 opciones de fix · pendiente tu firma
**Status**: SFEngine implementado · CPI calcula correcto · NFP devuelve SF×1000 menor de lo correcto · NO integrado al sidecar todavía

---

## §0 · Resumen 1 línea

`SF_NFP` cae a 0.0002σ cuando debería ser 0.24σ por **mismatch de unidades** entre `forecasts.json` (jobs en miles) y `SIGMA_FRED` (jobs absolutos). CPI no afectado. Gate Mar 12 no afectado.

---

## §1 · El bug · evidencia empírica de smoke tests

Ejecuté `sf_engine.py` con casos reales y placeholder values. Resultados:

### Tests CPI (correctos)

| Test | actual | forecast | σ_robust | SF computed | Mode | Verdict |
|---|---:|---:|---:|---:|---|---|
| 1 | 3.5% | 3.3% | 1.232426 | **0.16σ** | NORMAL | ✅ correcto · esperado ~0.16 |
| 2 | 5.0% | 3.3% | 1.232426 | **1.38σ** | CAUTELA | ✅ correcto · trigger 1.0 |

CPI usa percentage points · `forecast`, `actual`, `σ_robust` todas en mismas unidades (% pp). Cálculo `(actual - forecast) / σ` consistente.

### Tests NFP (BUG)

| Test | actual | forecast | σ_robust | SF computed | Mode esperado | Verdict |
|---|---:|---:|---:|---:|---|---|
| 4 | 115 | 62 | 219187.584 | **0.0002σ** | NORMAL ~0.24σ | ❌ |
| 5 | 400 | 62 | 219187.584 | **0.0015σ** | CAUTELA ~1.54σ | ❌ NO trigger |

Test 5 es especialmente preocupante: un NFP de +400K (gran sorpresa) **debería** disparar CAUTELA (|SF| > 1.3σ trigger NFP), pero el SF cae a 0.0015 y permanece NORMAL.

---

## §2 · Causa raíz técnica (verificable)

### Inputs del cálculo NFP

| Variable | Valor | Unidad | Source |
|---|---|---|---|
| `forecast` | 62 | **miles de jobs** | `forecasts.json` · Marco copy-paste de Investing.com 8-may 13:55 UTC ("NFP 62K") |
| `actual` | 115 | **miles de jobs** | `bls_client.py` · BLS API CES0000000001 fetched 8-may 12:55 UTC retroactivo |
| `σ_robust` | 219187.584 | **jobs absolutos** | `macro_calendar.json fred_calibration.events.NFP.historical_surprise_sigma` |

### Por qué σ_robust está en jobs absolutos

`fred_init.py:215+` calcula:
```
sigma_robust = 1.4826 × MAD × κ(K)
```

Sobre la series FRED PAYEMS (Total Nonfarm Payrolls). PAYEMS reporta **employment level absoluto** (158,737 → 158,852 = +115 jobs en miles, pero almacenado como 158852000 en jobs absolutos en algunos endpoints). El MAD sobre los CHANGES absolutos da el orden de magnitud `219187` (~219K jobs std).

### Por qué `forecasts.json` está en miles

Convención de reporting macro: cuando Investing.com / Bloomberg / CNBC publican consensus NFP, dicen literalmente "62K" o "Nonfarm Payrolls 62K". Marco copy-pasted "62" interpretando como "62 thousand" (correcto en convención humana).

### El cálculo erróneo

```python
SF = (actual - forecast) / σ_robust
SF = (115 - 62) / 219187.584
SF = 53 / 219187.584
SF = 0.000242   ← MAL · debería ser ~0.24σ
```

El cálculo correcto sería:
```python
SF = (115_000 - 62_000) / 219_187.584 = 0.24σ        # Opción A
SF = (115 - 62) / 219.187584 = 0.24σ                   # Opción B (sigma en miles)
```

### Otros eventos macro · ¿afectados?

| Categoría | Forecast unit | σ_robust unit | Match? |
|---|---|---|---|
| **CPI YoY/MoM** | % | % | ✅ OK |
| **Core CPI** | % | % | ✅ OK |
| PCE | % | % | ✅ OK |
| Unemployment | % | % | ✅ OK |
| **NFP** | **miles** | **absolutos** | ❌ **mismatch** |
| FOMC funds | % | % | ✅ OK |
| PPI | % | % | ✅ OK |
| Retail Sales | % | % | ✅ OK |

**NFP es el único evento con unidades diferentes** porque es el único cuya series FRED reporta absolute level (PAYEMS) en lugar de % change. JOLTS también tiene este problema potencial (jobs absolutos).

---

## §3 · Lo que NO afecta · CPI gate Mar 12

El gate del **martes 12 (en 81h)** evalúa `cpi_yoy_pct`:
- forecast = 3.3 (%)
- actual será capturado por BLS (en %)
- σ_robust = 1.232426 (%)
- **Mismas unidades · cálculo correcto**

El bug NFP es para futuros NFP releases (próximo Vie 5-Jun) o eventos JOLTS si se firman. **No bloquea el deploy LIVE Mar 12 13:30 UTC**.

---

## §4 · 3 opciones de fix · necesito tu firma

### Opción A · Unit normalization en `sf_engine.py`

Detectar metric name (`nfp_change_thousands`) y multiplicar forecast×1000 antes del cálculo SF. Sigma se queda como está.

```python
def normalize_units(metric_name: str, forecast: float) -> float:
    if metric_name == "nfp_change_thousands":
        return forecast * 1000
    return forecast
```

**Ventajas**:
- Cero modificación a `forecasts.json` (Marco no re-firma · hash actual sigue válido)
- Cero cambios en `macro_calendar.json` (sigma sigue el valor calibrado)
- Solo afecta `sf_engine.py` (módulo standalone, NO integrado todavía al sidecar)

**Desventajas**:
- Lógica de "magic" en código (mapping metric→multiplier hardcoded)
- Si Marco añade otra metric con jobs absolutos, hay que añadir al mapping
- Conceptualmente sucio (la unidad debería ser explícita, no implícita)

### Opción B · Cambiar convención en `forecasts.json`

Reescribir el evento NFP para usar `nfp_change_jobs` con valor 62000 en vez de `nfp_change_thousands` con 62. Marco re-firmaría con sign_forecasts.py.

```json
{
  "category": "NFP",
  "primary_metric_for_sf": "nfp_change_jobs",
  "forecasts": { "nfp_change_jobs": 62000 }
}
```

**Ventajas**:
- Conceptualmente más limpio (unidades explícitas en JSON)
- Sin lógica magic en código

**Desventajas**:
- Requiere re-firma con `sign_forecasts.py` (Marco teclea YES de nuevo)
- Si vuelve Investing.com convention "62K" en futuro · Marco tiene que recordar multiplicar
- `forecasts_validator.py` necesita rangos para `nfp_change_jobs` (-2,000,000 a 2,000,000)
- Cualquier consumidor de `forecasts.json` ya escrito asumirá miles

### Opción C · Diferir fix · arreglar post-CPI Mar 12

Documentar el bug como known issue · NO arreglar antes del Mar 12 · arreglar entre Mar 13 y Vie 5-Jun (próximo NFP).

**Ventajas**:
- Cero riesgo de introducir bug nuevo cerca del CPI gate
- Foco absoluto en CPI gate hasta Mar 12 13:30 UTC
- Coherente con tu firma "no apresurar V4-Alpha"

**Desventajas**:
- SFEngine queda con bug conocido en log de issues
- Si por alguna razón hay NFP intercalado, fallaría
- Documentación pendiente

---

## §5 · Lo que estoy preparado para hacer una vez firmes

Tres caminos según tu elección:

| Tu firma | Mi acción inmediata |
|---|---|
| **A** | Edit `sf_engine.py` con `normalize_units()` + tests pre/post · MD report a Marco · esperar firma para integración fmp_compat |
| **B** | Edit `forecasts.json` con nuevo metric · re-firma sign_forecasts.py · update `forecasts_validator.py` con rango nfp_change_jobs · tests · MD report |
| **C** | Documentar known-issue en `sf_engine.py` docstring · CHANGELOG entry · tests skipping NFP · seguir con resto del B-Plan |

---

## §6 · Pregunta directa

1. **¿Qué opción firmas (A/B/C)?**
2. **¿Detectas otros pares forecast/sigma con potencial mismatch que yo no haya visto?** (mi audit en §2 cobró CPI/Core CPI/PCE/Unemployment/FOMC/PPI/Retail · si crees que falta, dime)
3. **Si firmas A**, ¿el mapping debe vivir en `sf_engine.py` o en un archivo de config separado (`metric_units.json`)?
4. **Si firmas B**, ¿`forecasts_validator.py` debe RECHAZAR `nfp_change_thousands` (deprecated) o aceptar ambos por compat?
5. **Cualquier otra observación arquitectónica** que veas con `sf_engine.py` antes de integrarlo al sidecar.

---

## §7 · Resumen de status hasta este momento

```
P0 cleanup disco:       ✅ DONE (sdb2 50%)
P1 validator + sign:    ✅ DONE · forecasts.json firmado con SHA256
P2 FMP logs cotejo:     ✅ CERRADO por ti
P3 SFEngine:            🟡 implementado standalone · BUG NFP detectado · espera tu firma
P4 Tokyo POC:           ⏸ pospuesto Dom 10 evening
Logs policy:            ⏸ pendiente implementar (per tu §2 r150-quad)
```

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis/tris/quad
**Status**: V4-Alpha SHADOW estable · sin restarts · sf_engine.py NO integrado al sidecar
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True (14 checks)
**Próximo r-number**: r150-hex con tu firma A/B/C
