VelocityQuant — Re-calibration round: 4 entregables finales
==============================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~09:45 UTC
Asunto: Sí al re-calibration round. Necesito de ti 4 entregables
        concretos para implementarlo HOY y deploy SHADOW jueves.

---

## Estado

Aceptado tu veredicto:
- NO deploy mañana miércoles
- Re-calibration round HOY (1-2h trabajo)
- Deploy V4-Alpha SHADOW jueves mañana con datos cuantitativamente sólidos
- LIVE EXECUTE domingo 22:00 UTC sigue como target sin cambio

---

# 4 entregables que necesito de ti

## 1. btc_response_profile actualizado por evento — JSON listo para pegar

Tu backtest dio FOMC > CPI > NFP > PCE con valores específicos. Devuelve
el bloque JSON exacto con los 4 perfiles segmentados, listo para meter
en `macro_calendar.json`. Algo tipo:

```json
"btc_response_profile_per_event": {
  "FOMC": {
    "btc_move_mean_pct": 1.42,
    "btc_move_std_pct": 0.91,
    "p_move_above_2sigma": 0.22,
    "mean_reversion_pct_T5_T30": 0.38,
    "...lo que tú definas..."
  },
  "CPI":  { ... },
  "NFP":  { ... },
  "PCE":  { ... }
}
```

Incluye campos que tú consideres operativos (mean reversion sí/no,
notes de régimen, etc.). Pego tal cual.

---

## 2. Fórmula MAD exacta — Python snippet listo

Mi función actual en `fred_init.py`:
```python
mu = statistics.mean(changes)
sigma = statistics.pstdev(changes)
```

Dame el snippet exacto del reemplazo. Mi suposición:
```python
median = statistics.median(changes)
mad = statistics.median([abs(x - median) for x in changes])
sigma_robust = 1.4826 * mad
mu_robust = median   # ¿usar median en lugar de mean?
```

Confirma:
- ¿`mu` también pasa a `median` en lugar de `mean`?
- ¿El factor 1.4826 es correcto?
- ¿O prefieres `bw_mad` (bi-weight midvariance) o algún ajuste para
  series con autocorrelación temporal?

---

## 3. Trigger thresholds + reversion profiles por evento

Tras tu segmentación FOMC/CPI/NFP/PCE necesito saber:

### A. Trigger thresholds por evento
Para cada categoría, ¿cuál es el `|SF|` umbral mínimo para activar
MODE=CAUTELA? La spec genérica decía `|SF| > 1σ`. Si la sensibilidad
varía por evento (CPI post-2021 +210%), ¿cada categoría tiene threshold
distinto?

```
FOMC:  trigger_sf = ?
CPI:   trigger_sf = ?
NFP:   trigger_sf = ?
PCE:   trigger_sf = ?
```

### B. Reversion profile aplicado a Capture mode
El Capture mode (T+5 a T+30) reabre operaciones. ¿La duración de Capture
varía por evento según mean reversion observado?

```
FOMC:  capture_window_min = ? (alta vol, baja reversion 38%)
CPI:   capture_window_min = ?
NFP:   capture_window_min = ? (alta reversion 52% — corto?)
PCE:   capture_window_min = ?
```

### C. Threshold "mejora suficiente para LIVE" comparator
Si V4-Alpha SHADOW corre vie + lun, comparator V3.5 vs V4-Alpha. Cuál
métrica numérica mínima firma el GO domingo:

```
V4 drawdown ≤ X% de V3.5
V4 hit rate ≥ V3.5 + Y%
V4 transitions modo ≤ Z/día (no exceso ruido)
```

Dame X, Y, Z (o tu propuesta de KPIs).

---

## 4. Quick-validation simulation post-implementación

Tu sugerencia: tras implementar MAD + ajustes hoy, simular últimos
3 macro events para verificar Z-score corregido.

Mi propuesta concreta:
- Tras re-correr fred_init.py con MAD, tomar últimos 3 releases reales:
  NFP del 4-Apr-2026, CPI del 12-Apr-2026, JOLTS del 1-Apr-2026
- Para cada uno: mostrar `actual`, `forecast`, `previous`, `ΔActual`,
  `Z_old` (con σ aritmético), `Z_new` (con MAD)
- Verificar: con MAD ¿el Z-score real cruza el threshold cuando empíricamente
  hubo movimiento BTC > 1%? Si sí → MAD funciona.

¿Cómo prefieres que estructure el output de validación para que tú lo
audites?

```
Marco propone:
- MD report con tabla de 3 eventos: Z_old vs Z_new vs BTC reaction real
- Conclusión binaria: ¿MAD recupera la sensibilidad esperada? sí/no
```

¿OK con ese formato? ¿O prefieres otra cosa que tú audites?

---

# Mi plan operativo HOY (con tus 4 respuestas)

1. **15min:** modificar `fred_init.py` con MAD (entregable #2)
2. **5min:** re-correr → nuevo macro_calendar.json con σ_robust
3. **10min:** actualizar `btc_response_profile_per_event` (entregable #1)
4. **10min:** añadir `trigger_sf_per_event` + `capture_window_per_event`
   (entregable #3) al macro_calendar.json + sidecar lógica
5. **15min:** quick-validation simulation (entregable #4) → MD report
6. **20min:** dashboard shadow.html update para mostrar valores nuevos
7. **5min:** restart sidecar + verify HTTPS

**Total: ~1h20min** trabajo. Mañana mié temprano arranco wiring Rust
con spec refinada por ti.

---

Marco no toca nada hasta que tú firmes los 4 entregables. Tu llamada.

Gracias.
