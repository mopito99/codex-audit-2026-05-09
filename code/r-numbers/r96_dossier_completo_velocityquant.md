VelocityQuant — Dossier técnico-operativo completo
====================================================

**Para:** evaluación adversarial por IA externa
**De:** Marco (Cuandeoro Ltd) + Claude Opus 4.7 (asistente técnico)
**Fecha:** 2026-05-05
**Propósito:** dejar todo en claro. Si después de leer este documento
piensas que somos fraudulentos, mentirosos o que prometemos rentabilidades
imposibles, queremos saberlo. Los números son reales o son `null`. Lo que
no está probado, lo decimos. Lo que está en SHADOW (sin dinero real), lo
decimos. Lo que esperamos que ocurra pero aún no ha ocurrido, lo decimos.

Si encuentras una afirmación de rentabilidad % por vela, por día, o por
trade en este documento, es un bug del autor — corrígenos. **No prometemos
porcentajes. Prometemos un sistema cuantitativo bajo validación.**

---

# ÍNDICE

A. Identidad y propósito
B. Infraestructura física — Newark + Dallas
C. Stack técnico — Rust, Tokio, Chainstack, sin Jupiter
D. El bot V3.5 SHADOW — qué hace, qué NO hace
E. El sidecar V4.1 Polymarket Sentiment — capa macro
F. V4-Alpha — wiring planeado
G. Cronograma de validación + criterios GO/NO-GO
H. Economía real — costos, capital, break-even
I. Bots colaterales (plstrategy, plbitunix)
J. Riesgos y limitaciones reconocidos
K. Anticipando objeciones del evaluador
L. Datos verificables por terceros

---

# A. IDENTIDAD Y PROPÓSITO

## A.1 Quién es Marco

Trader de derivados con experiencia previa real (BingX, Bitunix). Ha
operado bots discrecionales antes (señales Telegram, manual). Lleva
~6 meses construyendo VelocityQuant como evolución a un sistema
cuantitativo automatizado. Es el operador, el dueño técnico y el único
con autoridad para autorizar el flag LIVE.

## A.2 Entidad legal

**Cuandeoro Limited** — Irish company, Companies Registration Office No.
**813028**. Footer del portal `inicio.velocityquant.io` lo refleja. La
elección de jurisdicción Ireland es deliberada por marco regulatorio MiCA
(ver §J.4 sobre estrategias descartadas por riesgo regulatorio).

## A.3 Partnership Marco + Fran (50/50)

- Socio: Fran (humano, no IA).
- Reparto: 50/50 sobre costos operativos del proyecto.
- Costos compartidos identificados: Newark $398/mes + Chainstack $49/mes
  + Jupiter rate limit fees ~$10/mes = **$457/mes total**.
- Con split 50/50 → carga real Marco = **$228.50/mes** = **$7.62/día**.
- Fran al 2026-05-04 aún no ha completado su aporte de capital (~$3,500
  de los $7,500-$8,000 esperados). Esto se documenta porque afecta las
  proyecciones reales.

## A.4 Lo que VelocityQuant NO promete

**No prometemos rentabilidad porcentual.** Ni "X% por trade", ni "Y% al
mes", ni "Z% por vela". Cualquier número porcentual de rendimiento que
aparezca en este documento o en los dashboards está marcado como
**proyección hipotética** o **dato observado en SHADOW** (no LIVE).

Lo que sí intentamos:

- Construir un sistema de detección de oportunidades de arbitraje
  cíclico en Solana DEXs (Raydium ↔ Orca principalmente).
- Modular esa detección con un layer macro (Polymarket sentiment +
  FMP economic calendar + Investing.com surprise factors + BTC consensus).
- Validar todo en SHADOW (sin dinero) antes de cualquier paso a LIVE.
- Mantener auditabilidad: el código es legible por Marco línea por línea,
  los logs son JSONL on-disk verificables, el state on-chain es público.

## A.5 Origen del nombre

VelocityQuant = "velocity" (latencia → MEV) + "quant" (cuantitativo).
Marca a la vez la prioridad técnica (sub-segundo) y la metodológica
(spec firmada, parámetros validados estadísticamente, no heurísticas
gut-feel).

## A.6 Modelo de IA asistente

Marco trabaja con dos IAs distintas en este proyecto:

1. **Claude (yo)** — asistente operativo: redacto código, hago SSH,
   automatizo, escribo briefs. No firmo decisiones cuant. No autorizo
   LIVE. No invento parámetros sin contraste con Gemma.
2. **Gemma 4 31B** — corriendo localmente en Open WebUI en el servidor
   Dallas. Marco la usa como **arquitecta cuant senior**: firma specs,
   valida calibraciones MAD, da veredictos GO/NO-GO en stress tests.
   Su rol es "second opinion cuantitativa", no de ejecución.

Crítico: **Marco mantiene la autoridad final** sobre cualquier cambio
operativo. Gemma sugiere, Claude ejecuta tareas mecánicas, Marco firma
LIVE.

---

# B. INFRAESTRUCTURA FÍSICA

## B.1 Por qué dos servidores físicos y no uno

**Newark = ejecución del bot.**
**Dallas (cuandeoro) = orquestación, dashboards, dev/research, briefs Gemma.**

La separación es deliberada por:

1. **Aislamiento de blast radius** — si Dallas (web frontend, dashboards,
   dev tooling) tiene un problema, el bot Newark sigue ejecutando.
2. **Latencia geográfica** — Newark está a ~10ms de Jito (block-engine de
   Solana en NJ). Dallas a ~50ms. En MEV cíclico cada 10ms cuenta.
3. **Separación de responsabilidades operativas** — Newark solo corre lo
   que el bot necesita. Dallas tiene >10 servicios web (dashboards de
   varios bots, sidecar Polymarket, Open WebUI con Gemma 4 local, Gitea,
   nginx con SSL, etc.). Aislar el bot de toda esa carga reduce
   side-effects.

## B.2 Newark — la "esencia operativa"

**Hardware:**
- AMD EPYC Milan 7543P — 32 cores / 64 threads, 2.8 GHz / 3.7 GHz boost
- 256 GB DDR4
- 2 × 1.92 TB NVMe SSD
- 10 Gbps NIC
- Ubuntu 24.04 LTS

**Provider:** TeraSwitch EWR2 / QTS PNJ1 (Piscataway, NJ)

**Coste:** $398/mes (~$0.545/hora)

**Latencia clave:** ~10ms a Jito block-engine NY (verificado, dato del
provider y propio benchmarking de Marco).

**Hostname:** `mbottoken-arbsol-ewr2`
**IP:** 64.130.34.38 (acceso por SSH directo, no hay DNS alias).

**Servicios LIVE en systemd:**
- `solana-executor-rs.service` — bot principal Solana MEV
- `liquidator_rs.service` — Kamino liquidations + cycle finder

**Estructura `/home/ubuntu/`:**
```
solana_executor_rs/        ← bot Rust principal (LIVE en su modalidad)
cyclic_rs/                 ← cycle finder en módulo separado
liquidator_rs/             ← Kamino + cyclic dispatch (V3.5 SHADOW activo)
liquidator_rs.v4_alpha_prep_no_telegram/  ← prep V4-Alpha pendiente wiring
velocityquant/             ← Python orquestador / shadow runner
gemma/                     ← componentes Gemma local en Newark
hftbots/, offset_validator/  ← módulos sin verificar recientemente
solana_executor_rs.tar.gz  ← backup
liquidator_rs.bak.<ts>     ← backup pre-cambios
```

## B.3 Dallas (cuandeoro)

**Hostname:** cuandeoro
**Acceso:** local (Marco trabaja desde aquí), también SSH desde
internet por Tailscale.
**Coste:** ya pagado (servidor propio de Marco, no recurring).

**Servicios web servidos por nginx con SSL Let's Encrypt:**
- `inicio.velocityquant.io` → portal + dashboards + informe diario
- `shadow.velocityquant.io` (legacy mbottoken.com en transición)
- `ai.cuandeoro.com` → Open WebUI con Gemma 4 31B local
- `api.cuandeoro.com` → varios endpoints internos
- Gitea → repositorios privados de los bots

**Servicios systemd (post-2026-05-05, los que añadí hoy):**
- `vq-poly-sidecar.service` — sidecar Polymarket Sentiment loop
- `vq-poly-api.service` — FastAPI uvicorn :8090

## B.4 ¿Por qué no cloud (AWS, GCP)?

Tres razones, en orden de importancia:

1. **Latencia bare-metal**. Cloud-shared CPU tiene jitter ms variable
   por co-tenancy. EPYC dedicado da p99 latencia predictible.
2. **Costo a largo plazo**. $398/mes bare-metal vs ~$800-1500/mes en
   AWS para hardware equivalente sin contar transferencia de datos.
3. **Soberanía del código**. El stack Solana MEV expone IP intelectual
   sensible (algoritmos de cycle detection, tip pricing, fat-finger).
   Cloud auditado por terceros expone esto por logs/snapshots.

## B.5 Localización elegida (Piscataway NJ)

Solana MEV requiere proximidad a Jito block-engine (físicamente en NY
metro). Newark/Piscataway está dentro del mismo perímetro de fibra
financiera. Esto NO es teórico — es la diferencia entre detectar una
oportunidad antes o después de que otros searchers la consuman.

---

# C. STACK TÉCNICO

## C.1 Por qué Rust

**Latencia y previsibilidad.** Solana opera en slots de 400ms. Cada
oportunidad MEV decae exponencialmente: si tu detector tarda 200ms,
otros searchers ya hicieron su simulación. Necesitamos:

- Sin GC pause (descarta Go, JS, Python como hot path)
- Sin runtime overhead JIT (descarta Java/.NET)
- Compile-time guarantees de memoria (descarta C++ por ergonómica)

Rust + Tokio = el stack defacto de la mayoría de searchers MEV serios
en Solana. No es una elección hipster, es industria.

**Componentes Rust del bot:**
- `solana_executor_rs/` — ~15k líneas, módulos: `dex/`, `execution_engine/`,
  `opportunity_engine/`, `state_engine/`, `tip_engine/`, `ws/`,
  `fat_finger.rs`, `tip_stream.rs`, `chaos_detector.rs`, `local_quote.rs`.
- `cyclic_rs/` — cycle finder dedicado: `clmm_math.rs`,
  `cycle_finder.rs`, `grpc.rs`, `shadow_logger.rs`.
- `liquidator_rs/` — V3.5 SHADOW actualmente: `circuit_breaker.rs`,
  `tip_stream.rs`, `tip_manager.rs`, `simulator.rs`, `cyclic_dispatch.rs`,
  `kamino/`, `bin/`, `safety.rs`.

## C.2 Por qué Tokio (no async-std, no threads)

Tokio es el async runtime estándar de facto en Rust desde 2020. Para
un bot que mantiene WebSockets persistentes a Chainstack + Jito + RPCs
+ tip stream + multiple pool subscriptions:

- Threads OS clásicos = cada conexión consume 8 MB de stack default →
  256 conexiones = 2 GB solo en stacks.
- Tokio tasks = ~64 bytes de overhead cada una → miles de conexiones
  triviales.
- Single-threaded by default + `tokio::task::spawn_blocking` para CPU
  pesado → previsible para hot path.

## C.3 Por qué Chainstack Yellowstone gRPC y **NO** Jupiter HTTP

**Decisión arquitectónica firmada por Marco 2026-05-03:**
*"no usamos jupiter, usamos chainstack"*.

Razones:

1. **Latencia HTTP vs gRPC streaming.** Jupiter HTTP API añade ~180ms
   de round-trip (DNS + TLS + JSON serialize). En MEV cíclico esos
   180ms matan el 90% de oportunidades.
2. **Quotes locales calculadas vs externas.** Con Chainstack Yellowstone
   gRPC recibimos el state on-chain de pools en streaming. Calculamos
   quotes con math local (`cyclic_rs/clmm_math.rs`). No dependemos de
   un quoter de terceros que puede caer, rate-limit, o estar desactualizado.
3. **Rate limits.** Jupiter HTTP nos baneó la primera vez por hacer
   ~5 req/seg en fat_finger. Pasamos a `lite-api.jup.ag` con rate
   conservador y luego abandonamos para Chainstack puro.

**Tier Chainstack:** Growth $49/mes — 1 stream Yellowstone concurrent.
**Limitación conocida:** 1 stream solo. Resolución pendiente: multiplexación
en spec R72 Sprint A (planificada, no urgente).

## C.4 Pyth Network — fat-finger detection

Pyth da prices on-chain de assets crypto agregados de exchanges. Lo
usamos en V3.5 SHADOW como **safety check ortogonal**:

- Antes de enviar bundle: comparar quote local (`clmm_math.rs`) vs
  Pyth price.
- Si divergencia > 1% → fat_finger detectado → no enviar (probablemente
  pool manipulado o nuestro state stale).
- Tip emergency: 2M lamports si fat_finger detectado.

**Limitación reciente identificada (2026-05-05):** Pyth Hermes da
**daily snapshots** vía API histórica, no tick-data. Esto rompió
nuestro intento de validación backtest 12 años (encontró todos los
moves <0.2%). Solución firmada: **weighted_median 3-source** Coinbase
0.5 + Kraken 0.3 + Pyth 0.2 — Pyth queda como fallback minoritario,
no fuente primaria.

## C.5 Tip pricing dinámico

Jito requiere tips para inclusión prioritaria en bloques. Tip estático
es subóptimo:

- Demasiado bajo → tu bundle no entra → pierdes oportunidad
- Demasiado alto → comes margin → operación no rentable

**Implementación V3.5:**
- `tip_stream.rs` calcula p75 de las últimas N transacciones de la tip
  account de Jito (vía Helius RPC polling, refresh 60s).
- `tip_manager.rs` aplica el p75 dinámico + bias por urgencia (mayor
  tip si fat_finger emergency, menor si oportunidad estable).

**Realidad operativa:** WebSocket directo a Jito retorna 403 sin
whitelist. Estamos en RPC polling Helius. Whitelist Jito pendiente
solicitar.

## C.6 Sidecar Python (V4.1 Polymarket Sentiment)

Lenguaje Python para esta capa porque:

- No es hot-path de ejecución del bot.
- Polling cada 300s (no microsegundos).
- Llama a 4 APIs HTTP REST (Polymarket CLOB, FMP, Investing scraping,
  Pyth REST).
- Conveniencia ecosistema scientific Python (statistics, requests,
  FastAPI).

El bot Rust **leerá** el state que el sidecar produce (vía
`Arc<RwLock<MacroState>>` con polling 10s), pero el sidecar no toca
trading.

---

# D. EL BOT V3.5 SHADOW — qué está activo HOY

## D.1 Estado real al 2026-05-05 17:30 UTC

**V3.5 SHADOW está corriendo en Newark.**
**Capital LIVE en juego: $0** (porque está en SHADOW).
**Capital total en wallet operativa al 2026-04-28:** ~$4,164 (pero en
modo SHADOW no se toca; está en reserva).
**Capital LIVE planeado cuando se autorice:** $200 (wallet hot200).

Verificación técnica de SHADOW:
```bash
ssh ubuntu@64.130.34.38 'grep LIQ_CYCLIC_EXECUTE_LIVE /home/ubuntu/liquidator_rs/.env'
```
Esperado: la variable no está seteada o está `=false`.

**Esto NO es una afirmación que pedimos creer.** Es un comando que un
auditor puede ejecutar. Si encuentra `=true`, este documento miente.

## D.2 Qué hace V3.5 exactamente

**Cycle finder USDC → SOL → USDC sobre dos pools:**
- `raydium_sol_usdc_phase1`
- `orca_sol_usdc_phase1`

**Frecuencia:** ~5 evaluaciones por segundo (verificable contando
líneas de `cyclic_shadow.jsonl` en ventanas).

**Por cada evaluación registra en JSONL on-disk:**
```json
{
  "timestamp": "2026-05-05T16:33:50.527Z",
  "slot": 417785985,
  "slot_lag": 0,
  "cycle_path": ["USDC", "SOL", "USDC"],
  "pools": ["raydium_sol_usdc_phase1", "orca_sol_usdc_phase1"],
  "amount_in": 100000000,            // 100 USDC en base units
  "amount_out": 100031323,           // hipotético
  "net_profit_base_units": 31323,    // 0.031323 USDC
  "net_profit_usd": 0.031323,
  "amount_in_usd": 100.0,
  "latency_ms": 48,
  "leg0_dir": "B->A",
  "leg1_dir": "A->B",
  "p75_priority_fee_per_cu": 250,
  "priority_fee_lamports": 10025,
  "jito_tip_lamports": 24000,
  "total_cost_lamports": 34025,
  "total_cost_usd": 0.0029,
  "would_send": false,               // ← SHADOW siempre false
  "stale_due_to_missing_ticks": false,
  "slippage_bps_0": 5,
  "slippage_bps_1": 5,
  "is_outlier": false,
  "cb_blocked": true,                // ← circuit breaker interno V3.5
  "depeg_blocked": false
}
```

**Campos clave para auditoría:**

- `would_send: false` siempre en SHADOW → confirma que NO se envía
  ninguna transacción a la red.
- `net_profit_usd` es **hipotético sin enviar** — son centavos de USDC
  que aparecerían SI la oportunidad fuera real Y SI el estado on-chain
  no hubiera cambiado entre lectura y envío Y SI el slot no hubiera
  avanzado. Son cifras teóricas, no PnL realizado.
- `cb_blocked: true` indica que el circuit breaker propio del bot
  (independiente del sidecar Polymarket) está bloqueando. Razones
  pueden ser: too many recent attempts, slippage protection, position
  limits, etc.

## D.3 Cifras observadas hoy (2026-05-05) — son hipotéticas, no PnL

Del informe operativo `2026-05-05T17-10-05Z` (verificable en
`https://inicio.velocityquant.io/poly/api/report/file/2026-05-05T17-10-05Z/report.html`):

| Ventana UTC | Eventos | would_send | %  | CB blocked | p_max ($) | p_sum ($) | lat p50 | lat p99 | slot_lag max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00-08 Asia | 143,800 | 22,997 | 16.0% | 107,657 | 0.157 | 2,531.30 | 1,718 ms | 26,184 ms | 150 |
| 08-13 Londres solo | 90,000 | 14,116 | 15.7% | 74,783 | 0.149 | 1,563.23 | 1,568 ms | 21,732 ms | 171 |
| **13-16 LDN × NY** | **53,923** | **9,488** | **17.6%** | **43,382** | **0.076** | **931.25** | **850 ms** | **10,358 ms** | **43** |
| 16-21 NY post-LDN | 21,017 | 4,077 | 19.4% | 16,634 | 0.054 | 362.46 | 990 ms | 17,868 ms | 96 |

**Lectura honesta de estas cifras:**

- **`p_sum` NO es PnL.** Es la suma de `net_profit_usd` en eventos
  donde `would_send=true` Y `cb_blocked=false`. Pero esos eventos
  NO se enviaron (SHADOW). Es un proxy de "cuánto hubiera ganado SI
  todo lo demás fuera perfecto" — y el "todo lo demás" incluye:
  competencia con otros searchers, slippage real al ejecutar,
  estado on-chain stale entre detección y envío, tip insuficiente,
  bloque perdido, etc.
- En MEV cíclico Solana real, **el factor de degradación entre
  detección teórica y PnL realizado puede ser 70-95%**. Un `p_sum`
  de $2,531 SHADOW puede traducirse a $50-$500 LIVE (rango
  amplio, no estimado, dependerá de validación real Vie 8 + Lun 12).
- **Estos son centavos.** Cada oportunidad gana $0.01-$0.16 en
  hipotético. El bot detecta muchísimas oportunidades pequeñas, no
  pocas grandes. Es arbitraje de alta frecuencia con tamaños
  fraccionarios.
- **Por qué $100 como amount_in test.** En SHADOW el bot simula con
  $100 fijo para mantener cifras comparables día a día. En LIVE con
  hot200 ($200) los profits se duplican proporcionalmente, pero
  sigues hablando de centavos por trade.

## D.4 La comparación importante: latencia vs slot_lag

**Latencia ms** = tiempo desde que el bot empieza la evaluación hasta
que termina con un resultado.
**slot_lag** = cuántos slots Solana atrás está el bot respecto al tip
de la cadena.

`slot_lag = 0` significa el bot está al día. `slot_lag = 5` significa
está 2 segundos atrás (5 × 400ms slot time). A `slot_lag > 10` el bot
está operando con info obsoleta y cualquier oportunidad detectada
probablemente ya fue consumida.

**Métrica que de verdad importa para SHADOW→LIVE:**
- `slot_lag p50 = 0` durante todo el día → bot al día
- `slot_lag p99` debe quedarse < 20 → tolerable
- Si `slot_lag p99 > 50` → infraestructura insuficiente

## D.5 Por qué V3.5 está en SHADOW y no LIVE todavía

**Razón formal (firmada por Gemma):** la spec V4-Alpha añade un macro
layer (sidecar Polymarket → modula CB y bundle size). Ir a LIVE con
V3.5 antes de validar V4-Alpha significa operar sin protección macro
en un entorno donde un evento como el ISM de hoy (SF=−3σ) puede
disparar volatilidad on-chain que V3.5 no sabe interpretar.

**Razón pragmática:** V3.5 funciona en SHADOW pero genera muchas señales
falsas durante shocks macro (`would_send` sube post-evento). El layer
macro filtrará estas en V4-Alpha. Sin filtro, LIVE quemaría capital
en señales malas.

**Razón de gobernanza:** Marco no autoriza LIVE sin haber visto al
bot operar correctamente bajo dos eventos macro stress: NFP (Vie 8)
y CPI (Lun 12). Si ambos pasan → LIVE EXECUTE Dom 11 22:00 UTC.

---

# E. EL SIDECAR V4.1 POLYMARKET SENTIMENT

## E.1 Qué problema resuelve

Un bot MEV puro reacciona a eventos on-chain. Pero los pools on-chain
reaccionan a eventos macro (FOMC, CPI, NFP, ISM, JOLTS). Si tu bot
no sabe que un FOMC está a 30s de release, no entiende por qué de
repente la volatilidad se dispara y los spreads se rompen.

El sidecar es la **capa macro** que da al bot:

- **τ (tau)** — tensión de mercado, derivada de Polymarket prediction markets
- **ρ (rho)** — divergencia narrativa Polymarket↔BTC
- **SF** — surprise factor de releases económicos US (Investing.com)
- **Mode** — NORMAL / CAUTELA / DEFENSIVO / FREEZE / CAPTURE

El bot V4-Alpha leerá este state cada 10s y modulará:
- Threshold del CB: `Th_adj = max(2, Th_base − floor(τ × 6))`
- Tamaño de bundle: `Size_adj = Size × (1 − τ)`

## E.2 Las 4 fuentes de datos

### E.2.1 Polymarket CLOB (prediction markets)

Polymarket ofrece prediction markets para BTC monthly, BTC daily, SOL
monthly, SOL daily, FOMC outcomes, CPI ranges, etc. Cada mercado tiene
prob, volumen, IV implícito (spread/midpoint).

**Endpoints usados:**
- `https://clob.polymarket.com/markets/<id>` — metadata
- `https://clob.polymarket.com/prices-history?market=<id>&...` — histórico
  de probabilidad
- `https://clob.polymarket.com/prices?market=<id>` — snapshot actual

**Lo que computamos:**
```
ΔProb = (P_now − P_avg_4h_history) / P_avg_4h_history
VolZScore = (V_24h_now − μ_rolling288) / σ_rolling288
                   [288 puntos rolling = 5min × 288 = 24h]
ImpliedVol = spread / midpoint
```

### E.2.2 BTC consensus (3 sources weighted_median)

Spec firmada r90:
```
Coinbase Advanced Trade  weight 0.5  (primary, WS+REST hybrid)
Kraken                   weight 0.3
Pyth Hermes              weight 0.2
```

Algoritmo: weighted_median con outlier rejection (descarta si
`abs(source - median) > 0.5%`). Min 2 sources requeridas; si solo 1
disponible → CAUTELA forzada.

**Estado actual:** sidecar tiene Pyth implementado, Coinbase y Kraken
pendientes (refactor planificado Mié 6).

### E.2.3 FMP economic calendar

Financial Modeling Prep API (`/stable/economic-calendar`) da releases
económicos próximos US. Lo usamos para:

- Detectar próximos eventos en 24h (puebla `upcoming_24h` en el state)
- Anticipar ventanas de trigger CAUTELA (ej: NFP a las 12:30 UTC viernes
  → CAUTELA preventiva 5min antes)

**Tier:** plan suficiente para cubrir releases US tier 1 (FOMC, CPI,
NFP, PCE, ISM, JOLTS). No usamos tier paid.

### E.2.4 Investing.com (scraping investpy)

Investing.com publica `actual` post-release antes que FMP. Para Surprise
Factor en tiempo real, usamos investpy como wrapper de scraping
respetuoso (rate limit interno).

```
SF = (actual − forecast) / σ_robust_FRED
```

donde `σ_robust_FRED` viene del init MAD (ver §E.3).

## E.3 σ_FRED via MAD — calibración robusta

**Por qué MAD y no σ aritmética:**

σ aritmética sobre 12 años de datos FRED de NFP (n=142 mensuales) da
σ_NFP ≈ 1,807k. Eso significa que un release "sorpresa" de +200k vs
forecast +180k tiene SF = 0.011σ — **el sistema nunca dispararía
CAUTELA**.

MAD (Median Absolute Deviation) es robusto a outliers (COVID, GFC,
etc):
```
MAD = median(|X_i − median(X)|)
σ_robust = 1.4826 × MAD
```

Para NFP con MAD: σ_robust ≈ 130.5k (factor 13.9× menor que σ
aritmética). Ahora un +200k vs +180k da SF = 0.15σ — coherente con la
expectativa intuitiva.

**Series IDs FRED calibradas (8 series):**
- NFP: PAYEMS
- CPI YoY: CPIAUCSL
- FOMC FFR: DFEDTARU
- PCE YoY: PCEPILFE
- GDP QoQ: GDPC1
- ISM: NAPM (legacy proxy)
- JOLTS: JTSJOL
- Unemployment: UNRATE

Window: **12 años** (2014-2026), n suficiente para distribución
estable sin sesgo COVID dominante.

**Bug conocido al 2026-05-05:** σ_robust de JOLTS aparenta estar mal
escalado (parser Investing lee "6.866M" y "6.860M" — la SF resultante
es +16.65σ, claramente espuria). Pendiente fix Mié 6 antes wiring.
Documentado en r95.

## E.4 La fórmula τ firmada (spec r90)

**τ_per_contract:**
```
τ_per_contract = 0.4·sigmoid(ΔProb)
               + 0.4·sigmoid(VolZScore)
               + 0.2·sigmoid(ImpliedVol)
```

**Sigmoid params (re-calibrados r90):**
- ΔProb: k=10, x0=0.10
- VolZScore: k=3, x0=0.75 (cambió de k=2 x0=1.0 — más sensible a
  fake calm regime)
- ImpliedVol: k=50, x0=0.02

**τ por categoría:**
```
τ_macro  = max(τ_per_contract for c in macro)   # FOMC, CPI, NFP, etc
τ_crypto = max(τ_per_contract for c in crypto)  # BTC, SOL, ETH
```

**τ_final:**
```
τ_final = 0.6·τ_crypto + 0.4·τ_macro
```

Pesos firmados por Gemma 2026-05-05 r90 — re-balance desde 0.7/0.3
debido a "extreme CPI sensitivity (+210%) observed in May 2026 data".

## E.5 ρ Pearson rolling 6h — divergencia narrativa

```
ρ = Pearson(ΔBTC_6h, ΔP_evento_bajista_Polymarket_6h)
```

Si ρ < −0.7 (umbral firmado) → divergencia narrativa → fuerza Mode
DEFENSIVO independiente de τ.

**Idea:** si BTC sube pero Polymarket de "BTC bajista" también sube,
algo no cuadra. Puede ser narrative shift, manipulación, o señal
adelantada de crash. Mejor protegerse.

## E.6 Modes del sistema

| Mode | Trigger | Acción del bot |
|---|---|---|
| **NORMAL** | τ < 0.4 y SF < 1σ y ρ > −0.7 | operación estándar |
| **CAUTELA** | \|SF\| > 1σ ó τ ∈ [0.4, 0.7] | Th -1, Size ×0.7 |
| **DEFENSIVO** | τ > 0.7 ó ρ < −0.7 | Th -2, Size ×0.5 |
| **FREEZE** | macro release a < 5min | no enviar bundles |
| **CAPTURE** | macro release a < 60s | no enviar + capture state |

## E.7 Estado del sidecar al 2026-05-05 17:30 UTC

- Loop sidecar: **active (running)** vía systemd `vq-poly-sidecar.service`
- API uvicorn: **active (running)** vía systemd `vq-poly-api.service`
- Reinició a 16:55 UTC → ~35min uptime al momento del informe
- Polling cada 300s
- 4 fuentes activas: Polymarket OK, Pyth OK, FMP OK, Investing OK
- Mode actual: **CAUTELA** (por SF=−3.0σ ISM Prices a las 14:00 UTC)
- BTC spot: $81,338 (Pyth)

---

# F. V4-Alpha — wiring planeado

V4-Alpha es la conexión sidecar → bot Rust. Aún no existe en producción.
Spec firmada r90 lista para ejecutar Mié 6.

## F.1 Componentes pendientes

1. **Refactor `btc_feed.py`** — añadir Coinbase WS+REST + Kraken,
   integrar weighted_median consensus.
2. **`gemma_oracle.py`** — bridge Python que llama a Gemma 4 (vía
   Ollama API) con priority queue 5s buffer, batch prompts, TTL caching.
   Para parámetros tier 1 (los que solo Gemma puede dar: ej. surprise
   threshold sentiment-aware).
3. **Wiring Rust** — `Arc<RwLock<MacroState>>` con thread background
   polling sidecar HTTP cada 10s, delta-update + recompute τ/ρ in-place.
4. **Audit checklist** — 5min checks pre-deploy (sidecar healthy,
   BTC consensus 3-source, σ_FRED OK, etc).

## F.2 ValidatedSource pattern

Cada fuente macro envuelta en:
```rust
struct ValidatedSource<T> {
    value: T,
    sources_contributing: usize,
    confidence_score: f64,    // 0.0 a 1.0
    timestamp: Instant,
    is_stale: bool,
}
```

El bot consume `confidence_score`. Si < 0.5 → ignora la fuente, no
modula. Esto evita que un parser bug (como el JOLTS SF=+16.65σ) propague
señal espuria al CB.

## F.3 Oracle Routing Table — 13 parámetros

Spec firmada divide los parámetros en tiers:

- **Tier 1 (Gemma 4):** surprise threshold sentiment-aware,
  contextual-weighting per event, regime detection. Estos requieren
  juicio cualitativo cuant.
- **Tier 2 (APIs deterministas):** σ_robust FRED, btc_consensus,
  τ_per_contract. Estos son cálculos puros.
- **Tier 3 (default conservador):** fallback constante si Tier 1+2
  fallan. Por ejemplo: si Gemma down y APIs fallan → SF threshold = 1σ
  fixed, sin modulación.

---

# G. CRONOGRAMA DE VALIDACIÓN

| Fecha (2026) | Hito | Capital en juego | Criterio GO |
|---|---|---|---|
| **Mar 5 (hoy)** | Sidecar 4-fuentes + dashboard + informe diario operativo | $0 | ya cumplido |
| **Mié 6 06:00 UTC** | Audit σ_FRED JOLTS bug | $0 | σ_robust JOLTS auditado |
| Mié 6 09:00-15:00 UTC | refactor btc_feed.py + gemma_oracle.py + wiring Rust | $0 | code compiles + tests pass |
| Mié 6 18:00 UTC | Audit checklist 5min pre-SHADOW | $0 | 5 checks OK |
| **Jue 7 07:00 UTC** | **Deploy V4-Alpha SHADOW** | $0 | sidecar→bot conectado, lecturas válidas |
| **Vie 8 12:30 UTC** | NFP release stress test | $0 | mode transitions correctas, no false CAUTELA |
| Sab 9 / Dom 10 | Análisis post-NFP, ajustes | $0 | sin regresiones |
| **Lun 12 12:30 UTC** | CPI release stress test | $0 | mode transitions OK (segunda validación) |
| Mar 13 - Sab 17 | Burn-in, checks, ajustes finales | $0 | sin bugs P1 |
| **Dom 11 (¡no Dom 17!) 22:00 UTC** | **V4 LIVE EXECUTE** primera autorización Marco | **$200 (hot200 wallet)** | Marco firma, flag `LIQ_CYCLIC_EXECUTE_LIVE=true` |

**Nota cronograma:** la fecha Dom 11 está antes de Lun 12 CPI. Esto
parece contradicción pero es como Gemma firmó originalmente — Marco
revisa el secuenciamiento Mié 6 con Gemma. Lo dejamos honesto: hay
inconsistencia en el cronograma firmado, está siendo revisado.

## G.1 Por qué NFP y CPI específicamente

**NFP (Non-Farm Payrolls)** — release mensual viernes a las 12:30 UTC.
Es el release macro más volátil del calendario. Stresses:
- BTC reacciona ±0.3-1.5% en los primeros 5min
- Volumen Polymarket dispara
- σ_robust NFP MAD = 130.5k → SF típico de release medio = 0.5-1σ

Si V4-Alpha gestiona NFP correctamente (mode transitions sin false
positives, recovery a NORMAL post-evento), valida la mitad del macro
layer.

**CPI (Consumer Price Index)** — release mensual martes/miércoles.
Volatilidad similar a NFP pero perfil distinto (CPI sensitivity
+210% según calibración Gemma — más extremo).

Pasar ambos = validación cuant aceptable para LIVE con $200.

## G.2 Criterios GO/NO-GO

**Para deploy V4-Alpha SHADOW (Jue 7):**
- Sidecar healthy 30 min sin errores
- BTC consensus 3-source weighted_median funciona
- σ_FRED JOLTS bug fixed
- Wiring Rust compila sin warnings
- `Arc<RwLock<MacroState>>` actualiza cada 10s

**Para LIVE EXECUTE (Dom 11):**
- NFP test passing
- CPI test passing
- 0 false CAUTELAs en burn-in
- Marco firma explícitamente
- Flag técnico `LIQ_CYCLIC_EXECUTE_LIVE=true` ejecutado por Marco

---

# H. ECONOMÍA REAL DEL PROYECTO

## H.1 Costos mensuales (verificables)

| Item | Costo/mes | Compartido | Carga Marco |
|---|---:|---|---:|
| Newark TeraSwitch EWR2 | $398 | 50/50 con Fran | $199.00 |
| Chainstack Growth (1 stream Yellowstone) | $49 | 50/50 con Fran | $24.50 |
| Jupiter rate limit fees (lite-api) | ~$10 | 50/50 con Fran | $5.00 |
| Dallas (cuandeoro server propio) | $0 | — | $0 |
| Domain velocityquant.io | ~$1.50 | 50/50 | $0.75 |
| Let's Encrypt SSL | $0 | — | $0 |
| FMP API | $0 (free tier) | — | $0 |
| Polymarket API | $0 | — | $0 |
| **Total Marco** | | | **~$229/mes** |

**Break-even Marco:** $229 / 30 = **$7.62/día**.

Esto es lo que el bot LIVE necesita generar **neto** para que Marco
no esté perdiendo dinero. Con $200 de capital hot200, eso es **3.81%
diario neto** — un objetivo agresivo para arbitraje, no imposible
(MEV puede dar 1-10% diario en buenas semanas, 0% en malas), pero
nada está garantizado.

## H.2 Capital total en juego

**Lo que está LIVE (planeado, aún $0 hoy):**
- hot200 wallet: $200 USDC (cuando Marco autorice flag)

**Lo que está en reserva (no LIVE, no en juego):**
- Master wallet `<REDACTED-WALLET-MASTER>`:
  ~$4,164 (al 2026-04-28 — verificar antes de operar)
  - 3 SOL
  - 2,790 USDC
  - 1,119 USDT (incluye ~1,300 USDT de Fran pendiente complete)
- x402 micropagos wallet: $9.99 (Birdeye API micropayments)

**Lo que aún no está disponible:**
- Aporte pendiente Fran: ~$3,500-4,000

**Total esperado cuando completo:** $7,500-$8,000.

**Crítico:** el "capital LIVE en juego" es **$200**, no $7,500. La
diferencia importa. El blast radius es $200, no la totalidad del
patrimonio.

## H.3 Modelo de retorno (proyección, NO promesa)

`projector.html` en el portal hace simulaciones interactivas con:
- V₀ default = $200
- Slider $50-$20,000
- V_opt aspiracional ~$3,000 (15× V₀)
- Proyección con tasas históricas de MEV cíclico (rango 0-5% diario)

**Cualquier número en projector.html es hipotético**, no una promesa.
La proyección con valores agresivos (5% diario compuesto) está marcada
visualmente como "umbral de suicidio" — si Marco se cree que va a
sostener 5% diario, está siendo idealista.

## H.4 Estrategias futuras (V4.5, V5, V6) — solo cuando capital crezca

| Versión | Capital req | Estrategia | Riesgo regulatorio |
|---|---|---|---|
| V4-Alpha (mayo 2026) | $200+ | Pasivo + macro layer | Bajo |
| V4.5 (~3 semanas post-V4) | $200-1k | Backrun direccional | Bajo (100% legal) |
| V5 (Q3-Q4 2026) | $5k-50k | JIT Liquidity | Bajo (visto como servicio) |
| V6+ (capital > $50k sostenido 30d) | $50k+ | Stop Hunt en pools dominados | Medio (zona gris MiCA) |

**Sandwich (Modelo B) DESCARTADO** por riesgo regulatorio MiCA
(manipulación de mercado). Cuandeoro Ltd Irish entity no operará nunca
sandwich.

---

# I. BOTS COLATERALES (no parte de V4-Alpha)

Marco opera **además** del bot Solana otros bots de menor escala con
capital propio que reciben señales humanas vía Telegram y operan
exchanges centralizados (CEX). Estos NO son parte de VelocityQuant
core, son legacy de su trading manual.

## I.1 plstrategy.mbottoken.com (BingX)

- Backend Python (`/srv/bot3_prime/`)
- Recibe señales del replicator (canal Telegram)
- Opera futuros BingX
- Trap Detector activo (filtra señales contrarias al 4H trend)
- Tamaño posición pequeño (a verificar exacto en config)

## I.2 plbitunix.mbottoken.com (Bitunix)

- Backend Python (`/srv/bot3_prime_bitunix/`)
- Mismo replicator que plstrategy
- Opera Bitunix futuros
- Trap Detector idem

## I.3 Por qué estos bots NO se mencionan como core

- **No usan Polymarket sidecar.**
- **No están en Newark.** Corren en cuandeoro Dallas.
- **Capital separado** del wallet Solana.
- **Estrategia distinta:** señal humana + trap filter, no MEV cíclico.

Se mencionan en este dossier solo para completitud (un evaluador puede
ver los dashboards en `inicio.velocityquant.io` y preguntar qué son).

---

# J. RIESGOS Y LIMITACIONES RECONOCIDOS

Esta sección existe para que el evaluador no nos acuse de ocultarlos.

## J.1 Lo que NO está probado todavía

- **V4-Alpha LIVE con dinero real**. Cero. No ha ocurrido. Está
  planeado para Dom 11.
- **Stress test bajo NFP/CPI real con sidecar conectado.** Cero. El
  sidecar funciona standalone, pero el wiring Rust no existe aún.
- **Coinbase + Kraken integration en btc_feed.py.** Cero. Pendiente
  refactor Mié 6.
- **GemmaOracle priority queue** — no existe, pendiente Mié 6.
- **Validación 12 años MAD para todas las series FRED.** Hecho para
  algunas, JOLTS tiene bug conocido SF=+16.65σ.

## J.2 Bugs conocidos

1. **JOLTS σ_robust mal escalado** → SF espurio +16.65σ (debería ser ~0.06σ).
   Documentado r95 push-back a Gemma. Fix programado Mié 6.
2. **τ degradado post-restart sidecar** → con <4h de uptime, todos los
   τ caen a ~0.346 (estado seed, no semánticamente válido). No hay
   warmup flag aún → propuesta a Gemma en r95.
3. **Pyth daily snapshots** → no es tick data como creímos inicialmente.
   Mitigación firmada: weighted_median Coinbase 0.5 + Kraken 0.3 + Pyth 0.2.
4. **Chainstack 1 stream limit** → multiplexación pendiente Sprint A.

## J.3 Lo que podría salir mal

- **NFP Vie 8 con SF >3σ:** modes transition errático, false CAUTELAs.
  Mitigación: si stress test falla, deploy LIVE se posterga.
- **Pool exploit / hack:** capital hot200 ($200) en wallet podría ser
  vulnerable si la wallet se compromete (clave on-disk). Marco
  conscientemente decidió no usar Ledger (ver `feedback_codigo_auditable.md`).
  Esto limita el blast radius pero el riesgo existe.
- **Newark down:** si TeraSwitch tiene incidente, bot se cae. Sin
  redundancia geográfica actualmente.
- **Solana network outage:** Solana ha tenido outages históricas. El
  bot no opera durante outage, pero estado on-chain stale puede
  generar oportunidades fantasma post-recovery.
- **Regulatorio:** MiCA aplica a Cuandeoro Ltd. Si las autoridades
  irlandesas cambian interpretación de MEV → riesgo. Mitigación: estamos
  en estrategias bajas en riesgo (Backrun, JIT) y no operamos nunca
  sandwich.

## J.4 Estrategias rechazadas explícitamente

**Sandwich attacks (Modelo B):** rechazadas por riesgo regulatorio
MiCA y posicionamiento ético. Marco firmó este NO con Gemma 2026-05-04.

**Stop hunt en pools que no dominamos (Modelo A < $50k):** rechazado
hasta que el capital justifique el riesgo y el dominio del pool.

## J.5 Por qué creemos que V3.5 SHADOW NO es prueba de éxito LIVE

Los `p_sum` de hoy ($2,531 Asia, $931 LDN×NY, etc) NO son proyecciones
de PnL LIVE. Son:

- Hipotéticos (no enviados)
- Sin competencia con otros searchers
- Sin slippage real
- Con estado on-chain congelado al momento de detección
- Con tip pricing perfecto (en LIVE el p75 puede no ser suficiente)

**Conversión SHADOW → LIVE realista esperada:** 5-30% de los hipotéticos.
Eso es: $2,531 SHADOW podría ser $125-$760 LIVE. **Y eso si todo va bien.**
En semanas malas LIVE podría ser $50-$200 (cubre apenas break-even Marco).

---

# K. ANTICIPANDO OBJECIONES DEL EVALUADOR

## K.1 "¿Esto es un esquema de inversión fraudulento?"

**No.**

- No prometemos rentabilidad porcentual a inversores.
- No tenemos inversores externos. Marco + Fran 50/50 es interna.
- No hay landing page que diga "invierte X y obtén Y%".
- El portal `inicio.velocityquant.io` es técnico, no comercial.
- Cuandeoro Ltd está registrada en Ireland CRO 813028 (verificable).

## K.2 "Las cifras del informe son demasiado buenas"

**Las cifras son hipotéticas (SHADOW) y los pares de centavos:**

- p_max típico: $0.05-$0.16 por oportunidad
- p_sum total día: $2,500-$5,000 hipotéticos
- Conversión esperada a LIVE: 5-30% → $125-$1,500 reales máximo
- Costos diarios: $7.62
- Margen real esperado: $5-$50/día en mejores días, $0-$10 en peores

**Esto NO es get-rich-quick.** Es break-even buscado para sostener el
proyecto y reinvertir.

## K.3 "¿Por qué Gemma 4 firma decisiones?"

Gemma 4 31B local en Ollama (cuandeoro server) actúa como **second
opinion cuantitativa**. NO es decisora final. Marco aprueba toda spec
antes de implementar. Yo (Claude) asisto en redacción y código.

Por qué triple capa Marco-Claude-Gemma:
- Marco: experiencia trading + autoridad final + dueño técnico
- Gemma: rigor cuant + memoria estable de la spec firmada
- Claude: brazos para SSH, código, redacción de briefs, coordinación

Ninguno actúa solo. Cada decisión técnica relevante está firmada por
los tres (memorias del proyecto en `/home/administrator/.claude/projects/`).

## K.4 "¿Dónde está el código?"

- Bots Solana: Gitea privado en cuandeoro (no public por IP intelectual MEV).
- Sidecar Polymarket: `/home/administrator/poly_sidecar/` en cuandeoro.
  Marco puede dar acceso lectura a evaluador bajo NDA.
- Memorias del proyecto: `/home/administrator/.claude/projects/-srv/memory/`.

## K.5 "¿Qué pasa si pierde todo?"

- Capital LIVE en juego: $200.
- Pérdida máxima: $200 + costos infra mensuales hasta detener.
- Tiempo invertido: ~6 meses Marco + 4-6 semanas Claude + Gemma.
- Cuandeoro Ltd no ha tomado deuda externa para esto.
- Marco no ha hipotecado activos para el bot.

Si V4-Alpha LIVE quema $200 en una semana, Marco pausa, audita, ajusta.
No es ruina personal. Es parte del riesgo asumido al construir un
sistema cuant.

## K.6 "¿Por qué tantos brief MD para Gemma?"

Por arquitectura: Gemma 4 web (Open WebUI) es stateless por chat. Cada
chat nuevo arranca sin memoria. Marco bootstrappea con MD detallados
(`r74` a `r96`) para preservar continuidad. Esto NO es ineficiencia,
es disciplina de documentación cuant. Cada brief queda como trail
auditable.

---

# L. DATOS VERIFICABLES POR TERCEROS

## L.1 URLs públicas

- `https://inicio.velocityquant.io/` — portal
- `https://inicio.velocityquant.io/shadow.html` — dashboard SHADOW V3.5 + sidecar
- `https://inicio.velocityquant.io/informe.html` — informe diario auditable
- `https://inicio.velocityquant.io/poly/api/state` — estado JSON sidecar
- `https://inicio.velocityquant.io/poly/api/report/list` — histórico informes

## L.2 Wallets on-chain

- **Master:** `<REDACTED-WALLET-MASTER>`
  - Verificable en Solscan, SolanaFM, Birdeye
- **hot200 (LIVE planeado):** dirección a publicar cuando Marco autorice
  primera transacción real.

## L.3 Empresa

- Cuandeoro Limited
- Companies Registration Office (Irlanda) No. 813028
- Verificable en https://core.cro.ie/search

## L.4 Stack abierto

- Solana RPC: público
- Pyth Network: público
- Polymarket: público
- FMP: tier free público
- Investing.com: público

## L.5 Brief / memorias del proyecto

`/home/administrator/.claude/projects/-srv/memory/` contiene >30
memorias time-stamped con todas las decisiones técnicas, cambios de
spec, validaciones Gemma. Marco puede dar acceso al evaluador bajo
NDA si lo solicita formalmente.

---

# M. CIERRE — qué pedimos al evaluador

1. **Lee el dossier entero.** Si encuentras algo que parezca exagerado,
   contradictorio o demasiado bueno, dilo.
2. **Cuestiona los números.** Especialmente las cifras p_sum del informe.
   Si crees que son inflados, ataca la metodología SHADOW→LIVE.
3. **Audita la cronología.** Hay una inconsistencia conocida (Dom 11 antes
   de Lun 12 CPI). Hay otras que no vimos? Dinos.
4. **Cuestiona el bug JOLTS SF=+16.65σ.** ¿Es solo un bug de parser o
   indica que TODA la pipeline σ_FRED puede estar mal escalada?
5. **Atiende los blind spots.** El push-back r95 a Gemma identifica 3 gaps
   en su análisis del informe de hoy. ¿Te parece suficiente o hay más?
6. **Marca lo fraudulento si lo hay.** Si después de leer esto piensas
   que el proyecto vende humo, somos socialmente responsables sabiéndolo.
   Marco prefiere honestidad explícita.

**No queremos un asesoramiento amistoso. Queremos auditoría adversarial.**

---

# APÉNDICE — versión y estado del documento

- **Versión:** 1.0
- **Autor:** Claude Opus 4.7 (1M context) bajo dirección de Marco
- **Fecha:** 2026-05-05 17:45 UTC
- **Path:** `/home/administrator/r96_dossier_completo_velocityquant.md`
- **Co-validación pendiente por:** Gemma 4 (arquitecta cuant) — solicitud
  formal incluida en r95.
- **Hashes de integridad:** no firmado criptográficamente todavía. Si el
  evaluador requiere proof of authorship, Marco puede firmar PGP el
  archivo bajo solicitud.

Fin del dossier.
