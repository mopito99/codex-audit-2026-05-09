VelocityQuant — Consulta Gemma 4: APIs Polymarket V4.1
=========================================================

Para: Gemma 4
De: Marco
Asunto: Decisión técnica sobre QUÉ endpoints de Polymarket usar para
cuantificar peso de sentimiento en fundamentales económicos, foco
ventana NYSE Open (13:30 UTC) y T-30min (13:00 UTC).

NOTA: respuesta concisa, sin tablas con padding, fórmulas exactas.
Cada pregunta máximo 5-8 líneas. Si es muy larga el bridge se trunca.

---

## 0. Contexto

V4-Alpha LIVE domingo 11-May 22:00 UTC con tu spec aprobada
(CB 8/10/4 + grace 5min + macro layer + 9 fórmulas).

V4.1 (Polymarket Sentiment Engine) post-LIVE mediados-mayo. Fórmula τ
ya validada por ti:

```
τ = 0.5·Norm(ΔProb) + 0.3·Norm(VolZScore) + 0.2·Norm(ImpliedVol)
Th_adj   = max(2, Th_base - floor(τ × 6))
Size_adj = BaseSize × (1 - τ)
ρ = Pearson(ΔBTC, ΔP_evento_bajista) — divergencia si ρ < -0.7
```

Ahora: decidir endpoints concretos y parámetros.

---

## 1. Hallazgos doc Polymarket

Tres bases públicas SIN auth para lectura:

```
gamma-api.polymarket.com    — markets, events, search
clob.polymarket.com          — midpoint, history, orderbook
data-api.polymarket.com      — volume agregado
```

Endpoints relevantes para V4.1:

```
GET  gamma-api/public-search?q=&events_status=active
GET  gamma-api/markets/{id}                       (vol24h, liquidity, clobTokenIds)
GET  gamma-api/events/{id}
GET  clob/prices/midpoint?token_id=X
GET  clob/prices/market?token_id=X&side=BUY|SELL
GET  clob/prices/history?token_id=X&interval=1h&fidelity=5
GET  clob/spread?token_id=X
GET  clob/orderbook/{token_id}
WS   wss://ws-clob.polymarket.com/ws/market
```

Rate limits Cloudflare: gamma 4000 req/10s, clob ~50-100 req/s.
Polling 5min × 10 contratos = 120 req/h → muy por debajo del límite.

NOTA: la página /trading/deposit-wallet-migration es para usuarios
que QUIEREN OPERAR en Polymarket (depositar/retirar). Para nuestro caso
de SOLO LECTURA de mercados, NO afecta — no necesitamos wallet ni auth.

---

## 2. Catálogo LIVE detectado 2026-05-05 02:00 UTC

MACRO/Fed:
- Fed Decision in June? (2026-06-17) — vol24h $909k
- How many Fed rate cuts in 2026? — vol24h $337k
- April Inflation US Annual / CPI (2026-05-12) — vol24h $6.3k
- Fed Decision in July? (2026-07-29) — vol24h $29k
- Fed rate cut by...? — vol24h $16.5k

CRIPTO:
- Will Bitcoin hit $150k by Jun 30? — vol24h $5.8M (TOP)
- Bitcoin price on May 5? — vol24h $175k (resuelve diario)
- Solana price on May 5/6/7/8 — vol24h $0.2-3k (DIRECTO al bot)
- Ethereum price on May 5/6/7 — vol24h $0.3-20k

REGULATORIO:
- Ethereum ETF Flows on May 5 — vol bajo

---

## 3. PREGUNTAS

### 3.1 Subset endpoints

  A) sólo midpoint + markets/{id}
  B) A + prices/history (para ΔProb y ρ)
  C) B + WS market channel realtime

¿A, B o C? Una línea con razón.

### 3.2 Modulación temporal weight·τ por ventana UTC

Mi propuesta:
  12:30-13:00 → 0.7
  13:00-13:30 (T-30 NYSE) → 1.5
  13:30-14:30 → 1.2
  14:30-20:00 → 1.0
  20:00-13:30 → 0.5
  Vie 21:00-22:00 (CME) → 1.3

¿Confirmas o ajustas alguno?

### 3.3 τ_macro vs τ_crypto para bot Solana MEV

Opciones:
  - separados con max()
  - weighted avg (qué pesos)
  - sólo τ_macro (los crypto-targets son short-horizon noise)
  - sólo τ_crypto enfocado en "Solana price today"

¿Cuál?

### 3.4 Eventos overlapping (FOMC + CPI mismo día)

¿Take Max(τ_event_n) — coherente con tu spec V4-Alpha — o suma ponderada?

### 3.5 Window ρ Pearson

  - 1h con fidelity=5 → 12 puntos
  - 4h con fidelity=5 → 48 puntos
  - 1d con fidelity=15 → 96 puntos

¿Cuál es estadísticamente más robusto y por qué?

### 3.6 Sigmoide Norm() params (k, x0)

```
norm(x) = 1 / (1 + exp(-k·(x - x0)))
```

¿Qué k, x0 para cada componente?
  - ΔProb (cambio relativo de probabilidad, ej: 0.6→0.8 = +0.33)
  - VolZScore (z-score volumen vs baseline 24h)
  - ImpliedVol (proxy: spread normalizado por mid-price)

### 3.7 Fallback si Polymarket cae 5min

Opciones:
  - τ = 0 (neutro, ignora sentiment)
  - mantener último τ válido por X minutos (¿cuánto?)
  - forzar Modo Cautela hasta recuperación

¿Cuál y por qué?

---

## 4. Resumen de lo que pido

1. Subset endpoints (A/B/C) con justificación
2. Modulación temporal — confirmar/ajustar
3. Macro vs Cripto — combinación
4. Overlapping — Take Max o suma
5. Window ρ — 1h vs 4h vs 1d
6. Sigmoide params — k, x0 para 3 componentes
7. Fallback API caída

Brief técnico, fórmulas exactas, sin tablas anchas con padding.
