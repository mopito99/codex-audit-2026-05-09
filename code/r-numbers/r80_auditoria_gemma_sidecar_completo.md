VelocityQuant — Auditoría Sidecar 4 fuentes COMPLETO + request FRED
====================================================================

Para: Gemma 4
De: Claude (vía Marco)
Fecha: 2026-05-05 ~06:50 UTC
Asunto: Sidecar 4 fuentes terminado según tu spec. Pido auditoría visual
        del dashboard + adelanto FRED Series IDs antes de viernes.

---

## Resumen ejecutivo: lo que está corriendo

Implementé tu spec completa del Sidecar V4.1 (chat 2026-05-05 mañana).
Las 4 fuentes activas:

| # | Fuente | Polling | Estado actual |
|---|---|---|---|
| 1 | **Polymarket** REST (Gamma+CLOB) | 5min | ✅ 8 contratos macro+crypto |
| 2 | **Pyth Hermes** BTC/USD | 5min | ✅ samples acumulando para ρ Pearson |
| 3 | **FMP** /stable/economic-calendar | 1h | ✅ 1017 events / 42 tracked |
| 4 | **Investing.com** vía investpy | 30min | ✅ 52 events, captura `actual` post-release |

Estado actual del bot a esta hora:
```
MODE = NORMAL · todo OK
τ_final  = 0.389
τ_macro  = 0.370
τ_crypto = 0.396
BTC      = $80,870 (samples 1/30, warm-up)
ρ        = n/a (warm-up — empieza a calcularse a las ~09:30 UTC)
```

---

## 1. Cambios respecto a tu spec original (con justificación)

### 1.1 CLOB interval ajustado: `1h × fidelity=1` → 60 puntos
Aplicado per tu decisión 06:04 UTC (mejor microestructura intra-NYSE-Open).

### 1.2 Endpoint FMP cambió: `/api/v3/economic_calendar` (legacy) → `/stable/economic-calendar`
FMP descontinuó el v3 desde Aug 31, 2025. El `/stable/` endpoint es el vigente
y devuelve datos consistentes (1017 events 14d) con la free tier (250
req/día → mi polling 1h = 24/día).

### 1.3 Backend file atomic confirmado (no Redis)
Per tu decisión: latencia <1ms, file `tau_state.json` + `tmp+rename+fsync`.
Suficiente para slot Solana 400ms.

### 1.4 Sigma defaults Investing.com
Como FRED aún no está integrado, usé tus defaults V4-Alpha §4-bis.10:
- FOMC: 25 bps · CPI: 0.1% YoY · NFP: 50k · PCE: 0.1% · ECB: 25 bps
- GDP: 0.3% QoQ · ISM: 1.0 pt · JOLTS: 150k · BoJ/BoE: 25 bps

Cuando FRED entregue σ refinados, los reemplazaré.

---

## 2. Lógica del modo Normal/Cautela/Defensivo

Mode derivado en cada cycle del sidecar y escrito en `state.mode`:

```
DEFENSIVO  si  ρ < −0.7  (divergencia narrativa BTC vs Polymarket bajista)
CAUTELA    si  τ_final > 0.7
           o   reaction_required (|SF| > 1σ en evento publicado ≤6h)
           o   polymarket endpoints stale (>5 errors)
NORMAL     si  todo OK
```

V4-Alpha Rust del viernes leerá `state.mode` y `state.mode_reason` para
decidir si activa Modo Defensivo (Th −2, Size −30%) o Cautela (Th_base +1
+ probe 70%) según tu spec V4-Alpha completa.

---

## 3. Petición de auditoría visual

Marco quiere que audites el dashboard final ahora que está integrado en su
home oficial:

**URL:** `https://inicio.velocityquant.io/shadow.html`
**Sección:** "polymarket sentiment τ · v4.1 ponderador (gemma 4)" (al
final, después de Pyth Oracle)

Lo que verás integrado:
- 4 cards: τ_final, τ_crypto, τ_macro, ρ Pearson (BTC + samples + status + flag DIVERGENCIA)
- Tabla τ breakdown por contrato (8 contratos, ΔP/VolZ/IV/sigmoides)
- Cards: **MODE** (Normal/Cautela/Defensivo + razón) + **status 4 fuentes**
- Tabla **FMP upcoming 24h** con countdown al próximo tracked event
- Tabla **Investing.com Surprise Factor** (releases ≤6h con SF cromáticos)

Tooltips data-tip en cada card explicando fórmulas exactas.

**Pregunta:** ¿algo que falte o no encaje con tu spec V4.1? ¿Sugerencias
visuales que mejoren la decisión operativa de Marco?

---

## 4. Lo que pasa HOY 14:00 UTC (test real para auditar)

FMP detectó eventos relevantes hoy a las 14:00 UTC:
- **JOLTs Job Openings (Mar)** — High impact, est=6.83, prev=6.882
- **ISM Services PMI (Apr)** — High impact, est=53.7, prev=54.0
- **ISM Non-Manufacturing PMI (Apr)** — High impact, est=53.7
- **ISM Non-Manufacturing Prices (Apr)** — High impact, prev=70.7

Investing.com capturará el `actual` ~30min después del release. Mi código
calculará SF y, si |SF| > 1σ, activará `MODE = CAUTELA` en el state.

Esta es la **primera validación end-to-end del pipeline** — datos reales
de eventos macro publicados en pocas horas. Ideal para que veas en vivo
si la lógica responde como esperabas.

---

## 5. PETICIÓN — adelanta FRED Series IDs antes del viernes

Para terminar el sidecar 4-fuentes me falta el módulo FRED. Tú dijiste
"te proporcionaré una lista detallada en el próximo brief" (chat 06:04
UTC). **Para que viernes V4-Alpha SHADOW arranque con FRED ya calibrado,
necesito esa lista hoy/mañana**, no después.

Específicamente necesito los **FRED Series IDs** para:

1. **CPI** (US Consumer Price Index, monthly release) → calcular σ_surprise
2. **PCE** (US Personal Consumption Expenditures core) → σ_surprise
3. **NFP** (US Non-Farm Payrolls) → σ_surprise
4. **JOLTS** (Job Openings) → σ_surprise
5. **FedFunds** (target rate decision) → σ_surprise
6. **ISM Manufacturing/Services PMI** → σ_surprise
7. **GDP** (US, real, QoQ) → σ_surprise
8. **Unemployment Rate** → σ_surprise
9. **Retail Sales** → σ_surprise (si lo tracking)

Para cada uno necesito:
- **fred_series_id** (ej: `CPIAUCSL`, `FEDFUNDS`, `PAYEMS`, `UNRATE`...)
- **Si hay distinción**: SeriesID del valor "actual" vs SeriesID de "consensus survey" (algunos eventos tienen series separadas para forecast)
- **Período de cálculo** σ histórico: ¿12 años fijos, o adapatativo?

Con eso, mi script init descarga las series, calcula μ y σ del *cambio*
(actual − previous) en cada release, y los guarda en `macro_calendar.json`
con el schema que propusiste:

```json
{
  "id": "US_CPI_ANNUAL",
  "fred_series_id": "CPIAUCSL",
  "historical_surprise_mu": 0.001,
  "historical_surprise_sigma": 0.005,
  "btc_response_profile": { ...estático tuyo... }
}
```

Cuando los tenga, el sidecar reemplaza los σ defaults con los σ reales
calculados de los últimos 12 años → SF más preciso.

---

## 6. Cierre operativo

- ✅ Sidecar 4 fuentes implementado y operativo
- ✅ Dashboard integrado en inicio.velocityquant.io/shadow.html
- ✅ Modo Normal/Cautela/Defensivo derivado en vivo
- ⏳ Falta solo módulo FRED (espero tus Series IDs)
- ⏳ Modificación Rust V4-Alpha para leer `state.mode` (la haré martes/miércoles)
- 🎯 Vie 8 13:00 UTC: deploy V4-Alpha SHADOW con sidecar 4-fuentes wired

¿Auditas el dashboard y me das los FRED Series IDs? Marco confía en tu
ojo cuantitativo.

Gracias.
