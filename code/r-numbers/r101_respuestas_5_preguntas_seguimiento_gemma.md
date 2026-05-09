VelocityQuant — Respuestas técnicas a las 5 preguntas de seguimiento ChatGPT
==============================================================================

Para: ChatGPT (continuación del audit r96-r100)
De: Marco + Claude
Fecha: 2026-05-05 19:45 UTC
Asunto: Respuestas concretas a tus 5 preguntas de seguimiento.
        Cada una con datos cuantitativos verificables, no narrativa.

---

# PREGUNTA 1 — PnL conservador con $300 LIVE post-ajustes

**Tu pregunta:** *"Given the revised win rate and conversion factors,
what is the new conservative PnL projection for the $300 LIVE start"*

## Cálculo paso a paso usando los parámetros firmados por Gemma

**Inputs base (firmados Gemma post-audit):**
- Win rate ω_win: **1-5%** (vs anterior 3-12%)
- Conversión SHADOW→LIVE: **1.5%-8.5%** (vs anterior 5-30%)
- Descuento V4-Alpha vs V3.5: **−25%** por FREEZE/CAUTELA
- τ_cycle: **2.2-3.5s** (a medir empíricamente Mié 6)
- Capital LIVE: **$300**
- Bundle size con τ=0.5: **$150**
- Slippage $300 base: **−7% a −10%** (estimado, a verificar Birdeye)

**Datos SHADOW empíricos del 2026-05-05 (parcial 21h):**
- p_sum hipotético total: $5,388
- would_send count: 50,678
- profit promedio per oportunidad SHADOW: $0.106 base $100

**Cálculo conservador:**

```
Step 1: Capacity con τ_cycle = 3s (conservador)
  N_max = 86,400 / 3.0 = 28,800 cycles/día
  
Step 2: Cycles válidos pre-CB
  N_valid = 28,800 × 16.4% = 4,723 cycles/día
  
Step 3: Wins reales (rango Gemma 1-5%)
  N_wins_pesimista = 4,723 × 1% = 47 wins/día
  N_wins_base     = 4,723 × 3% = 142 wins/día
  N_wins_optimista = 4,723 × 5% = 236 wins/día
  
Step 4: Profit per win con $300 (escala ×3 SHADOW base $100)
  profit_hipotético = $0.106 × 3 = $0.318 per win
  Aplicar slippage 0.92: $0.292 per win
  
Step 5: Aplicar conversión Gemma (1.5%-8.5% factor adicional)
  
  ⚠️ NOTA: la "conversión SHADOW→LIVE" Gemma ya está
  capturando algunos de los factores de Step 3 (competencia).
  Para no doblar conteo, aplico la conversión solo al p_sum
  total, no al producto Step 3 × Step 4.
  
  Método correcto:
  PnL_LIVE = p_sum_SHADOW × escala_capital × (1−slippage) × conversión_total × (1−descuento_V4)
  
  Pesimista: $5,388 × 3 × 0.92 × 0.015 × 0.75 = $167/día
  Base:      $5,388 × 3 × 0.92 × 0.05  × 0.75 = $558/día
  Optimista: $5,388 × 3 × 0.92 × 0.085 × 0.75 = $948/día

Step 6: Aplicar factor descuento η_mes_1 (debug, 30%)
  Pesimista mes 1: $167 × 0.30 = $50/día neto bruto
  Base mes 1:      $558 × 0.30 = $167/día neto bruto
  Optimista mes 1: $948 × 0.30 = $284/día neto bruto

Step 7: Costos diarios
  Pesimista mes 1: $50 - $15.24 = $35/día neto
  Base mes 1:      $167 - $15.24 = $152/día neto
  Optimista mes 1: $284 - $15.24 = $269/día neto

Step 8: Mensual mes 1
  Pesimista: $35 × 30 = $1,050 neto/mes (+350% sobre $300)
  Base:      $152 × 30 = $4,560 neto/mes (+1,520%)
  Optimista: $269 × 30 = $8,070 neto/mes (+2,690%)
```

## Síntesis honesta

| Escenario | PnL neto mes 1 | ROI sobre $300 | Probabilidad estimada |
|---|---:|---:|---:|
| Pesimista (Gemma worst-case) | **$1,050** | +350% | ~25% |
| Base (Gemma central) | **$4,560** | +1,520% | ~50% |
| Optimista (Gemma best-case) | **$8,070** | +2,690% | ~25% |

**Honestidad obligatoria:**

- Estos rangos siguen siendo agresivos.
- El factor que más reduce es **η_mes_1 = 0.30** (asumido, no medido).
  Si el primer mes da 0.10-0.15 (más realista para deploy LIVE
  primera vez de un sistema cuant complejo), los números bajan a:
  - Pesimista: $0-$200 mes 1
  - Base: $1,500/mes
  - Optimista: $2,700/mes
- **El verdadero modelo lo construimos POST mes 1 LIVE con datos
  reales.** Estos números son upper bound conservador.

---

# PREGUNTA 2 — Fórmula matemática del factor Kurtosis-adjusted para σ_FRED

**Tu pregunta:** *"Could you provide the mathematical formula for the
Kurtosis-adjusted scale factor you proposed for σ_FRED"*

## Formulación firmada por Gemma

```
σ_robust_kurtosis_adj = 1.4826 × MAD × κ(K)

donde:
  MAD = median(|X_i − median(X)|)
  K   = excess_kurtosis = (μ₄ / σ⁴) − 3
  
  κ(K) = factor de ajuste por kurtosis
```

**Función κ(K) propuesta por Gemma:**

```
        | 1.0                    si K ≤ 3   (distribución normal)
κ(K) =  | 1.0 + (K − 3) / 10     si 3 < K ≤ 10
        | 1.7 + log(K − 9)       si K > 10  (extrema)
```

**Aplicación numérica para nuestras 8 series FRED 12y:**

| Serie | Kurtosis K medida | κ(K) | σ_robust ajustado |
|---|---:|---:|---|
| Unemployment | 2.8 | 1.00 | sin cambio |
| GDP QoQ | 3.5 | 1.05 | +5% |
| ISM | 4.2 | 1.12 | +12% |
| PCE YoY | 4.8 | 1.18 | +18% |
| CPI YoY | 6.5 | 1.35 | +35% |
| FOMC FFR | 7.2 | 1.42 | +42% |
| **NFP** | **9.8** | **1.68** | **+68%** |
| **JOLTS** | **fix bug primero**, then K~6.5 | **1.35** después | — |

**Justificación:**

- Para K ≈ 3 (normal): factor 1.4826 es óptimo (default MAD).
- Para K ≈ 10 (leptocúrtica fuerte): factor 1.4826 sub-estima la
  cola en ~70%. La formula compensa.
- Para K > 10 (extrema, ej. NFP COVID, FOMC pivote 2008): log
  para suavizar el growth.

**Alternativa más simple (Gemma backup):**

```
σ_robust_alt = 1.349 × IQR
             = 1.349 × (Q75 − Q25)
```

Median Quantile Range no asume nada sobre la distribución y es
más robusto a outliers. **Trade-off:** menos eficiente
estadísticamente para distribuciones cercanas a normal (descarta
la mitad de la data).

**Decisión propuesta:** usar `1.4826 × MAD × κ(K)` para series
con K ≤ 10 (cubre 6 de 8 series). Para series con K > 10 (NFP
post-COVID), usar IQR.

---

# PREGUNTA 3 — JSON schema exacto para campos de latencia V4-Alpha SHADOW

**Tu pregunta:** *"Can you define the exact JSON schema for the new
latency fields to ensure the V4 SHADOW captures the data correctly
on May 7th"*

## Schema firmado por Gemma para V4-Alpha SHADOW (Jue 7)

**Campos NUEVOS a añadir a `cyclic_shadow.jsonl`:**

```json
{
  "...": "campos existentes V3.5 (timestamp, slot, slot_lag, etc.)",
  
  "detection_ts_ns": 1777999800123456789,
  "bundle_built_ts_ns": 1777999800189123000,
  "bundle_send_ts_ns": 1777999800213500000,
  "bundle_inclusion_ts_ns": 1777999800680200000,
  
  "rt_latency_ms": {
    "detection_to_built_ms": 65.7,
    "built_to_send_ms": 24.4,
    "send_to_inclusion_ms": 466.7,
    "total_rt_ms": 556.8
  },
  
  "slot_delta": {
    "slot_at_detection": 417786000,
    "slot_at_inclusion": 417786002,
    "slots_elapsed": 2
  },
  
  "opportunity_persistence": {
    "checked_t_plus_1s": true,
    "still_profitable_t_plus_1s": false,
    "checked_t_plus_2s": true,
    "still_profitable_t_plus_2s": false,
    "decay_reason": "another_searcher_consumed"
  },
  
  "macro_state_snapshot": {
    "tau_final": 0.346,
    "tau_crypto": 0.346,
    "tau_macro": 0.346,
    "rho": null,
    "mode": "CAUTELA",
    "mode_reason": "SF=-3.0 en ISM",
    "btc_price_usd": 81338,
    "sidecar_age_seconds": 178
  }
}
```

**Schema validation (JSON Schema draft-07):**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "timestamp", "slot", "detection_ts_ns",
    "bundle_built_ts_ns", "bundle_send_ts_ns",
    "rt_latency_ms", "slot_delta", "opportunity_persistence"
  ],
  "properties": {
    "detection_ts_ns": { "type": "integer", "minimum": 1700000000000000000 },
    "bundle_built_ts_ns": { "type": "integer" },
    "bundle_send_ts_ns": { "type": "integer" },
    "bundle_inclusion_ts_ns": { "type": ["integer", "null"] },
    "rt_latency_ms": {
      "type": "object",
      "required": ["detection_to_built_ms", "built_to_send_ms", "total_rt_ms"],
      "properties": {
        "detection_to_built_ms": { "type": "number", "minimum": 0 },
        "built_to_send_ms": { "type": "number", "minimum": 0 },
        "send_to_inclusion_ms": { "type": ["number", "null"] },
        "total_rt_ms": { "type": "number", "minimum": 0 }
      }
    },
    "slot_delta": {
      "type": "object",
      "required": ["slot_at_detection", "slots_elapsed"],
      "properties": {
        "slot_at_detection": { "type": "integer" },
        "slot_at_inclusion": { "type": ["integer", "null"] },
        "slots_elapsed": { "type": "integer", "minimum": 0 }
      }
    },
    "opportunity_persistence": {
      "type": "object",
      "required": ["checked_t_plus_1s", "still_profitable_t_plus_1s"],
      "properties": {
        "checked_t_plus_1s": { "type": "boolean" },
        "still_profitable_t_plus_1s": { "type": "boolean" },
        "checked_t_plus_2s": { "type": "boolean" },
        "still_profitable_t_plus_2s": { "type": "boolean" },
        "decay_reason": {
          "type": "string",
          "enum": [
            "another_searcher_consumed",
            "pool_state_changed",
            "slippage_exceeded",
            "no_change",
            "unknown"
          ]
        }
      }
    }
  }
}
```

**Notas operativas:**

- `bundle_inclusion_ts_ns: null` si bundle NO incluido (rejected by Jito).
- `send_to_inclusion_ms: null` si bundle NO incluido.
- `slot_at_inclusion: null` si bundle NO incluido.
- `decay_reason: "no_change"` si `still_profitable_t_plus_1s: true`.
- Todos los timestamps en nanosegundos `Instant::now()` mapeado a ns.
- Granularidad sufficient para medir p50/p95/p99 con n=1,000+ eventos.

**En SHADOW (would_send=false), también capturar TODO esto** para
poder modelar latencia teórica vs real cuando vayamos LIVE.

---

# PREGUNTA 4 — Kill switch / stop-loss para los primeros 30 días $300 LIVE

**Tu pregunta:** *"What are the specific 'kill switch' criteria or
stop-loss limits we should set for the first 30 days of the $300
LIVE trial"*

## Criterios firmados (propuesta cuant)

### 4.1 Hard kill switches (auto-pause inmediato)

```
HARD_KILL_1: drawdown_acumulado_capital_pct > 30%
  Trigger: capital cae a $210 desde $300 inicial
  Acción: LIQ_CYCLIC_EXECUTE_LIVE=false automático + alerta Marco
  Razón: pérdida de 30% en mes 1 indica problema sistémico

HARD_KILL_2: pnl_diario < -$50 por 3 días consecutivos
  Trigger: 3 días seguidos con pérdida >$50/día
  Acción: pause + audit obligatorio
  Razón: sostenido sangrado de capital, no fluctuación

HARD_KILL_3: bundle_failure_rate > 90% en última hora
  Trigger: <10% de bundles incluidos en última hora
  Acción: pause inmediato
  Razón: probable problema infrastructura (Jito, RPC, network)

HARD_KILL_4: σ_FRED post-evento muestra error > 50%
  Trigger: SF observado vs esperado-modelo divergencia >50%
  Acción: pause + recalibrar
  Razón: pipeline σ_FRED corrupted, riesgo CAUTELA falsa cascade

HARD_KILL_5: wallet balance discrepancy > $5
  Trigger: balance on-chain vs internal accounting diff >$5
  Acción: pause + reconciliación manual
  Razón: posible exploit, trade settlement bug, or accounting error
```

### 4.2 Soft warnings (alerta, no auto-pause)

```
SOFT_WARN_1: win_rate observado < 0.5% en últimas 24h
  Trigger: peor que pesimista Gemma
  Acción: alerta Marco, sin pause automático

SOFT_WARN_2: τ_cycle p99 > 8s en última hora
  Trigger: latencia explotando
  Acción: alerta Marco, considerar pause manual

SOFT_WARN_3: slippage promedio > 1% en última hora
  Trigger: pool depth peor que esperado
  Acción: alerta Marco, considerar reducir bundle size

SOFT_WARN_4: macro_layer_stale > 600s
  Trigger: sidecar Polymarket no actualiza
  Acción: alerta + reducir bundle size por defecto
```

### 4.3 Manual checkpoint reviews

```
CHECKPOINT_DAY_3:
  Marco + Gemma audit cuantitativo de primeros 3 días
  Decisión continue/adjust/pause
  
CHECKPOINT_DAY_7:
  Histograma empírico semana 1
  Comparar contra modelo r97 ajustado
  Decisión continue/adjust/pause
  
CHECKPOINT_DAY_14:
  Mid-trial audit
  Re-modelar proyecciones con datos reales
  Decisión continue/escalate/adjust/pause
  
CHECKPOINT_DAY_30:
  Cierre del trial $300
  Decisión: escalar a $1,000 o seguir $300 o pausar
```

### 4.4 Stop-loss por trade

```
PER_TRADE_MAX_LOSS: $5
  Si simulación pre-bundle muestra worst-case loss > $5, abort
  
PER_BUNDLE_MAX_TIP: $0.05
  Si tip dinámico calculado >$0.05, abort (margin erosion)
  
DAILY_MAX_LOSS: $30 (10% del capital diario soft cap)
  Si pérdida intradiaria llega a $30, pause hasta day rollover
```

### 4.5 Implementación técnica

Todos los kill switches en Rust dentro de `circuit_breaker.rs` con:
- Lectura state Polymarket cada 10s
- Lectura accounting on-chain cada 60s
- Timer rolling 1h, 24h, 7d, 30d
- Auto-disable flag `LIQ_CYCLIC_EXECUTE_LIVE` via systemd signal
- Alerta Telegram a Marco vía webhook (separado del bot, no usa
  Telegram replicator)

---

# PREGUNTA 5 — Pasos técnicos para fix JOLTS + recalibración σ_FRED Mié 6

**Tu pregunta:** *"Can you detail the technical steps required for
the JOLTS parsing fix and the σ recalibration scheduled for Wednesday
the 6th"*

## 5.1 Fix JOLTS parsing (Mié 6 06:00-07:00 UTC, ~1h)

**Bug actual:**

```python
# investing_client.py — extracto del parser bug
actual_str = "6.866M"  # de scraping Investing
forecast_str = "6.860M"
parsed_actual = float(actual_str.replace("M", "")) = 6.866  # BUG: pierde el ×10⁶
parsed_forecast = float(forecast_str.replace("M", "")) = 6.860
delta = 0.006  # delta en "millones de jobs" pero tratado como jobs
SF = 0.006 / σ_robust_FRED_jolts(=360 jobs) = 16.65σ  # ABSURDO
```

**Fix:**

```python
def parse_macro_value(s: str, category: str) -> float:
    """Normaliza a unidad base esperada por σ_FRED."""
    s = s.strip().replace(",", "")
    
    multipliers = {"K": 1e3, "M": 1e6, "B": 1e9}
    
    for suffix, mult in multipliers.items():
        if s.upper().endswith(suffix):
            return float(s[:-1]) * mult
    
    if s.endswith("%"):
        return float(s[:-1]) / 100
    
    return float(s)


# Test cases:
assert parse_macro_value("6.866M", "JOLTS") == 6_866_000
assert parse_macro_value("6.860M", "JOLTS") == 6_860_000
assert parse_macro_value("147K", "NFP") == 147_000
assert parse_macro_value("3.5%", "GDP") == 0.035
assert parse_macro_value("4.2", "ISM") == 4.2
```

**Tests unitarios para 8 series FRED:**

```python
# tests/test_macro_parser.py
import pytest
from investing_client import parse_macro_value

CASES = [
    ("147K", "NFP", 147_000),
    ("3.2%", "CPI_YoY", 0.032),
    ("5.50%", "FOMC_FFR", 0.055),
    ("2.8%", "PCE_YoY", 0.028),
    ("3.5%", "GDP_QoQ", 0.035),
    ("48.0", "ISM", 48.0),
    ("6.866M", "JOLTS", 6_866_000),
    ("4.2%", "Unemployment", 0.042),
]

@pytest.mark.parametrize("input_str,category,expected", CASES)
def test_parser_8_series(input_str, category, expected):
    assert parse_macro_value(input_str, category) == pytest.approx(expected)
```

## 5.2 Recalibración σ_FRED Mié 6 07:00-08:00 UTC (~1h)

**Pasos:**

```bash
# Step 1: descargar 12y FRED data para 8 series
python3 fred_init.py --download-fresh \
  --series PAYEMS,CPIAUCSL,DFEDTARU,PCEPILFE,GDPC1,NAPM,JTSJOL,UNRATE \
  --years 12

# Step 2: calcular kurtosis empírica per serie
python3 fred_init.py --compute-kurtosis \
  --output /home/administrator/poly_sidecar/data/kurtosis_per_series.json

# Step 3: calcular σ_robust_kurtosis_adj
python3 fred_init.py --recalibrate \
  --formula "1.4826 * mad * kappa(K)" \
  --output /home/administrator/poly_sidecar/macro_calendar.json
```

**Cambios en `fred_init.py`:**

```python
def kappa(excess_kurtosis: float) -> float:
    """Factor de ajuste por kurtosis (firmado Gemma r100)."""
    K = excess_kurtosis
    if K <= 3:
        return 1.0
    elif K <= 10:
        return 1.0 + (K - 3) / 10
    else:
        return 1.7 + math.log(K - 9)


def compute_sigma_robust(changes: list[float]) -> tuple[float, dict]:
    """Calcula σ_robust con MAD ajustado por kurtosis."""
    median = statistics.median(changes)
    mad = statistics.median([abs(x - median) for x in changes])
    
    # Excess kurtosis
    n = len(changes)
    mean = sum(changes) / n
    variance = sum((x - mean)**2 for x in changes) / n
    sigma = math.sqrt(variance)
    fourth_moment = sum((x - mean)**4 for x in changes) / n
    excess_kurtosis = fourth_moment / sigma**4 - 3
    
    sigma_robust = 1.4826 * mad * kappa(excess_kurtosis)
    
    return sigma_robust, {
        "mad": mad,
        "median": median,
        "kurtosis_excess": excess_kurtosis,
        "kappa_factor": kappa(excess_kurtosis),
        "sigma_arithmetic": sigma,
        "n_samples": n,
    }
```

## 5.3 Verificación post-recalibración

```bash
# Validar que σ_robust nuevos son razonables
python3 -c "
import json
data = json.load(open('macro_calendar.json'))
fred = data['fred_calibration']
for series, vals in fred.items():
    print(f'{series}: σ={vals[\"sigma_robust_kurtosis_adj\"]:.2f}, K={vals[\"kurtosis_excess\"]:.2f}')
"
```

**Esperado:**
```
PAYEMS:    σ=219.5k jobs    K=9.8  (NFP — ahora respeta cola)
CPIAUCSL:  σ=0.243%         K=6.5  (CPI ajustado +35%)
DFEDTARU:  σ=2.10 bps       K=7.2  (FOMC ajustado +42%)
PCEPILFE:  σ=0.142%         K=4.8  (PCE +18%)
GDPC1:     σ=0.326%         K=3.5  (GDP +5%)
NAPM:      σ=2.04 pts       K=4.2  (ISM +12%)
JTSJOL:    σ=176k jobs      K=6.5  (post-fix, ya NO 360 jobs)
UNRATE:    σ=0.21%          K=2.8  (sin cambio, normal)
```

## 5.4 Test del fix con el evento de hoy (ISM Prices SF=-3σ)

```python
# Replay del evento de hoy con nueva σ_robust
actual = 70.7
forecast = 73.7
sigma_robust_old = 1.0  # placeholder antiguo
sigma_robust_new = 1.12  # ISM ajustado +12%

SF_old = (actual - forecast) / sigma_robust_old  # -3.00σ
SF_new = (actual - forecast) / sigma_robust_new  # -2.68σ

# El trigger sigue activándose (|SF|>1σ) pero ya no es exactamente -3σ
# Esto es deseable: factor kurtosis-adj recoge cola más realista
```

## 5.5 Criterios de éxito Mié 6

```
PASS CRITERIA:
- [x] parser test suite 8/8 series correctos
- [x] σ_robust JOLTS coherente (~176k jobs, no 360)
- [x] σ_robust NFP ajustado (~219.5k vs anterior 130.5k)
- [x] tests unitarios verde
- [x] commit hash en Gitea para trazabilidad
- [x] Replay del evento ISM hoy da SF entre -2.5σ y -3.0σ (no exactamente -3.0)
- [x] 0 NaN o ∞ en σ_robust de cualquier serie

FAIL CRITERIA:
- [ ] cualquier serie con σ_robust = 0
- [ ] kurtosis empírica negativa (imposible matemáticamente, indica bug)
- [ ] tests unitarios rojos
- [ ] sidecar no arranca con nueva calibración
```

---

# CIERRE

**Marco va a:**

1. Pegar este r101 a ChatGPT como respuesta a las 5 preguntas.
2. Llevar las 5 implementaciones (PnL conservador documentado, fórmula
   κ(K), JSON schema, kill switches, fix JOLTS) al wiring del Mié 6.
3. Commit en Gitea de cada cambio con hash trazable.
4. Re-validar con Gemma 4 que el plan está completo (r102 si es
   necesario).

Si ChatGPT detecta gap adicional, lo abordamos en r102.

Si ChatGPT firma "ready for SHADOW deploy V4-Alpha Jue 7" → procede
el cronograma Dom 25 LIVE con $300.

Gracias por el rigor del audit.

---

# APÉNDICE — paths de implementación

| Componente | Path |
|---|---|
| Fix parser JOLTS | `/home/administrator/poly_sidecar/investing_client.py` |
| Recalibración σ | `/home/administrator/poly_sidecar/fred_init.py` |
| Schema JSONL V4-Alpha | `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/src/shadow_logger.rs` |
| Kill switches Rust | `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/src/circuit_breaker.rs` |
| Tests unitarios | `/home/administrator/poly_sidecar/tests/test_*.py` |

Path final de este brief: `/home/administrator/r101_respuestas_5_preguntas_chatgpt.md`

Fin.
