VelocityQuant — Pedir backtest analítico macro a Gemma 4
==========================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~09:00 UTC
Asunto: Antes del deploy SHADOW miércoles, valida cuantitativamente
        tu spec V4-Alpha §4.7 contra históricos. Tú tienes acceso
        analítico histórico mejor que el mío.

---

## Contexto

Tienes ya integrados en VelocityQuant:
- **σ_FRED calibrados con 12 años** (FOMC=17.10 bps, CPI=2.12% YoY,
  NFP=1807k, PCE=0.15% MoM, JOLTS=383, GDP=1.69% QoQ, UNEMPLOYMENT=0.94pp,
  RETAIL=2.33% MoM, ISM=1.0pt fallback)
- Spec V4-Alpha §4.7 con distribución BTC pre/post-evento que tú definiste:
  ```
  Pre-evento:    Volume drop 20-40%, Spread mult 1.5-2x
  Spike T0-T+5:  BTC mean ±1.2%, std 0.8%, P(>2σ) ≈ 15-20%
  Repricing T+5-T+30: mean reversion 30-50% del move inicial
  ```

Antes de cablear V4-Alpha mañana miércoles, **necesitamos verificar
empíricamente que esa spec sigue válida con la realidad reciente**.

---

## Pregunta concreta

Tú tienes acceso analítico desde el nacimiento de los mercados crypto
(2014+) y a series macro completas FRED. Solicitud:

**Para los principales releases macro de los últimos 12 años (NFP, CPI,
FOMC, PCE), genera el resumen estadístico de:**

1. **Movimiento BTC en ventanas T-30min, T+5min, T+30min** post-release
2. **Frecuencia P(|move| > 2σ)** real → comparar con tu spec "15-20%"
3. **Mean reversion T+5 a T+30** real → comparar con tu spec "30-50%"
4. **Decomposición por categoría**: ¿NFP mueve más que CPI? ¿FOMC > NFP?
   ¿Hay régimen distinto post-2021 (QE/inflación) vs pre-2021 (calma)?

**Devuelve:**
- Tabla con n eventos, mean |move|, std, P(>2σ), mean reversion observado
- Comparativa estadísticamente honesta vs tu spec V4-Alpha §4.7
- ¿La spec sub-estima, sobre-estima o está en línea?
- Si discrepa → recálculo recomendado para `btc_response_profile` en
  `macro_calendar.json`

---

## Sub-pregunta: refinamiento σ_FRED

Tras calibrar con 12 años, vimos:
- **σ_NFP = 1807k** (ENORME, incluye COVID-19 -22M jobs Apr 2020 + recuperación)
- σ_FOMC = 17 bps (vs default 25 → más reactivo)
- σ_CPI = 2.12% YoY (vs default 0.1% → mucho menos reactivo)

**Pregunta crítica:** ¿deberíamos winsorizar outliers COVID (Mar-Sep 2020)
o excluir ese período del cálculo σ? Sin filtrar, σ_NFP es tan grande que
el bot **nunca reaccionará a un NFP normal de ±200k surprise**.

¿Cuál es tu recomendación cuantitativa:
- (a) Mantener σ con outliers (régimen real incluye eventos extremos)
- (b) Winsorize 3σ trimming
- (c) Excluir período Mar-Sep 2020 explícitamente
- (d) Usar mediana de absoluto (MAD) en lugar de σ — robusto a outliers
- (e) Otra técnica que prefieras

---

## Sub-pregunta: τ_proxy retroactivo en Polymarket

Polymarket history (CLOB) está disponible 1m/1h/6h/1d/1w atrás. Si tienes
acceso analítico a **historia más antigua de Polymarket** (desde 2020+),
¿podrías:
- Para los contratos macro tipo "FOMC rate decision", "CPI release",
  identificar momentos donde τ_per_contract retroactivo > 0.7
- Cross-correlate con fechas de release macro
- Devolver: ¿cuántas veces τ saltó coincidiendo con evento macro?
  ¿% true positive vs false positive del τ histórico?

Si Polymarket no tiene esa historia (proyecto relativamente nuevo) →
ignora esta sub-pregunta.

---

## Output que necesito de ti

Brief técnico con:
1. **Tabla NFP/CPI/FOMC/PCE últimos 12 años:** n eventos, mean BTC move,
   std, P(>2σ), mean reversion
2. **Comparativa vs spec V4-Alpha §4.7:** ¿alineada o requiere update?
3. **Recomendación de refinamiento σ_FRED** (a/b/c/d/e o tu propuesta)
4. **(Opcional)** Validación retroactiva τ Polymarket si tienes histórico

Con eso decido si:
- Mañana miércoles deploy V4-Alpha SHADOW con spec actual (si está
  validada empíricamente)
- O hacemos primero un re-calibration round con tus números actualizados

Marco se basa en tu llamada cuantitativa.

Gracias.
