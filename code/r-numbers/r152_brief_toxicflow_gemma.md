# r152 · Brief — Roadmap toxicflow bot (Hyperliquid toxic flow inversion)

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 ~15:55 UTC · pre-deploy V4 SHADOW
**Asunto**: Roadmap, costes y approach técnico para nuevo bot toxic-flow inversion sobre Hyperliquid
**Status**: PROPUESTA · pendiente tu firma con plan ejecutable

---

## §0 · Contexto y propósito

Mientras esperamos el deploy V4 SHADOW (17:46 UTC) y el r149 post-deploy (18:00 UTC), Marco abre **un track nuevo independiente**: un bot que detecta wallets perdedoras estructurales en Hyperliquid y toma la posición opuesta cuando entran al mercado.

**Estrategia base**: equivalente cripto del PFOF (Payment for Order Flow) de Citadel/Robinhood en TradFi. Identificar flujo no-tóxico (retail uninformado que pierde sistemáticamente), tomar el otro lado del trade.

**Naming**: `toxicflow` (workspace `toxicflow.velocityquant.io`, código en `/srv/toxicflow/`).

**Tracks separados — NO mezclar**:
- V4 cyclic Solana (deploy hoy 17:46 UTC)
- QuantumBot PPO BingX (`/srv/profitlab_quantum/`)
- toxicflow (este brief) — independiente, capital propio, infra propia

---

## §1 · Por qué Hyperliquid como primary venue

| Factor | Hyperliquid | BingX/Bybit/OKX | Drift/Mango (Solana) |
|---|---|---|---|
| Posiciones individuales públicas | ✅ Sí | ❌ No | ✅ Sí |
| PnL realizado por wallet | ✅ Sí | ❌ Solo agregado | ⚠️ Calculable on-chain pero costoso |
| API gratis sin auth | ✅ Sí | ⚠️ Auth required | ✅ Sí |
| Latencia ejecución | ✅ ~100-300ms | ✅ ~50-100ms | ⚠️ ~500ms-1.5s |
| Liquidez | ⚠️ Decente top tokens | ✅ Alta | ⚠️ Limitada altcoins |
| Capacity para size pequeño | ✅ Bien | ✅ Bien | ⚠️ Slippage en altcoins |

Conclusión técnica: Hyperliquid es el **único venue donde el filtro completo de toxic flow funciona end-to-end** porque expone todo lo necesario sin paid feeds.

---

## §2 · Lo que SÍ está definido (no necesita firma tuya)

1. **Venue primary**: Hyperliquid
2. **Tracking 100% on-chain transparente** (no scraping CEX privado)
3. **Data ingest**: API pública `https://api.hyperliquid.xyz/info`, rate limit ~20 req/s, sin auth
4. **DB**: Postgres en Dallas (ya activo, usado por `profitlab_quantum_db`)
5. **Pipeline mínimo**: scraper diario → DB wallets + métricas → filtro losers → ejecutor opposite con sizing prudente
6. **Validación obligatoria**: 4-8 semanas paper-trading antes de LIVE (regla NO proyectar revenue sin data LIVE)
7. **Capital LIVE inicial**: microcapital tipo V4 ($50-500 max) hasta validar edge real

---

## §3 · Lo que pido tu firma — 6 preguntas críticas

### Q1 — Filtro "loser estructural" — qué métricas y umbrales

Mi propuesta inicial:
```
LOSER_CRITERIA = (
    pnl_realized_90d < -500           # USD
    AND win_rate_30d < 0.40           # fracción
    AND trade_count_30d >= 20         # min sample
    AND size_avg_position >= 1000     # USD
    AND first_seen < (today - 60d)    # antigüedad mín
    AND avg_loss_size > avg_win_size  # asimetría retail clásica
    AND loss_to_deposit_ratio > 0.30  # excluir whales que pierden 5%
)
```

**Pregunta**:
- ¿Apruebas esta combinación de filtros o sugieres ajustar umbrales?
- ¿Falta alguna métrica clave (ej: holding period, leverage, hora del día)?
- ¿Algún criterio para distinguir bot enmascarado vs retail genuino?

### Q2 — Costes reales del proyecto end-to-end

Te pido estimación honesta — no infles ni minimices:

| Bucket | Coste estimado | Notas |
|---|---|---|
| Infra Hyperliquid scraping | $0/mes (API gratis) | Confirmar rate limit suficiente para tracking 10K-50K wallets |
| Storage Postgres | $0/mes (Dallas local) | Pero tenemos 40GB libres en /srv (82% usado). ¿Cuánto necesita la DB para 6m de historia? |
| Compute backtest | $0/mes (A100 local libre) | A100 40GB libre, solo 1.5GB usado actualmente |
| Bot executor infra | $0/mes (Dallas local) | FastAPI + WebSocket Hyperliquid |
| Wallet on Hyperliquid | $0 setup, capital min ~$10 | Pero capital trading es decisión de sizing |
| Latency optimization | ¿$50-200/mes RPC dedicado? | ¿Necesario o el público basta? |
| Total mensual fijo | **TBD** | Tu pregunta a responder |
| Capital inicial trading | **TBD** | Tu pregunta a responder |
| Tiempo dev (1 persona, Marco + Claude) | **TBD** | Tu estimación de semanas |

### Q3 — Approach técnico para la DB de wallets en Dallas

Yo necesito poblar y mantener una DB de ~10K-50K wallets de Hyperliquid con sus métricas históricas. Mi propuesta de schema:

```sql
CREATE TABLE wallets (
    address VARCHAR(42) PRIMARY KEY,
    first_seen TIMESTAMPTZ,
    last_active TIMESTAMPTZ,
    deposit_total NUMERIC(20, 6),
    withdraw_total NUMERIC(20, 6),
    classification VARCHAR(20),  -- 'loser_active', 'loser_inactive', 'winner', 'unclassified', 'bot_suspected'
    last_classified TIMESTAMPTZ
);

CREATE TABLE wallet_metrics_daily (
    address VARCHAR(42) REFERENCES wallets(address),
    date DATE,
    pnl_realized_d NUMERIC(20, 6),
    pnl_realized_30d_rolling NUMERIC(20, 6),
    pnl_realized_90d_rolling NUMERIC(20, 6),
    trade_count_d INT,
    trade_count_30d_rolling INT,
    win_rate_30d_rolling NUMERIC(5, 4),
    avg_loss_size NUMERIC(20, 6),
    avg_win_size NUMERIC(20, 6),
    sharpe_proxy_30d NUMERIC(8, 4),
    PRIMARY KEY (address, date)
);

CREATE TABLE wallet_fills (
    address VARCHAR(42),
    fill_id BIGINT,
    timestamp TIMESTAMPTZ,
    coin VARCHAR(20),
    side VARCHAR(10),  -- 'B' o 'S'
    px NUMERIC(20, 8),
    sz NUMERIC(20, 8),
    fee NUMERIC(20, 8),
    closed_pnl NUMERIC(20, 8),
    PRIMARY KEY (fill_id)
);
```

**Pregunta**:
- ¿Apruebas el schema o ajustes?
- ¿Cuánto storage proyectas para 6 meses de datos (50K wallets activas, ~50 fills/wallet/mes)?
- ¿Prefieres tablas TimescaleDB (extensión Postgres) en vez de Postgres puro para las métricas time-series?
- ¿Cómo gestionar la fase de bootstrapping inicial (poblar 6 meses históricos sin saturar la API)?

### Q4 — Cronograma realista

Mi propuesta tentativa, con buffers:

| Fase | Trabajo | Duración estimada |
|---|---|---|
| F1 - Scaffolding | Estructura, Postgres schema, scrapers básicos | 3-5 días |
| F2 - Bootstrap DB | Poblar 6m histórico Hyperliquid (rate-limited) | 7-14 días background |
| F3 - Filtro + classifier | Implementar filtros, clasificar wallets diariamente | 5-7 días |
| F4 - Backtest histórico | Validar filtro contra data histórica, computar PnL teórico | 7-10 días |
| F5 - Paper-trading LIVE | Bot ejecutor en paper-mode, 4-8 semanas observation | 4-8 semanas |
| F6 - Microcapital LIVE | $50-500, 2-4 semanas observation con capital real mínimo | 2-4 semanas |
| F7 - Scale-up condicional | Si edge confirmado, escalar capital hasta capacity limit | TBD |

**Total honesto pre-LIVE meaningful**: ~3 meses desde F1 hasta F6 cerrada.

**Pregunta**:
- ¿Cronograma realista o demasiado optimista/conservador?
- ¿Sugieres orden distinto (ej: backtest antes que bootstrap completo)?
- ¿Algún hito intermedio que añadirías como gate obligatorio?

### Q5 — Riesgos específicos y guardrails

Yo veo estos riesgos:

| # | Riesgo | Mitigación propuesta |
|---|---|---|
| 1 | El loser identificado se reforma → tú quedas short cuando gira | Recalcular PnL ventana móvil 30d cada día. Si PnL_30d > 0 dos semanas seguidas → kick |
| 2 | Selection bias: top losers ya inversados por 50 bots | Apuntar a "mid-tail losers" rank 200-2000, no top 50 |
| 3 | Capacity constraint: tu trade mueve precio en altcoins iliquidos | Position size <0.5% volumen 24h del token |
| 4 | Whale enmascarada como loser (perdió 5% de $10M) | Filtro `loss_to_deposit_ratio > 0.30` |
| 5 | Bot hedger enmascarado (PnL spot negativo, hedged en otro venue) | Análisis patrón temporal — bots regulares, retail irregular |
| 6 | Latencia: Hyperliquid 100-300ms ejecución, tú llegas tarde | WebSocket directo, no REST polling |
| 7 | Reversal risk: el loser acierta 1 trade grande | Sizing nunca >20% del loser, stop-loss obligatorio |
| 8 | Sample size insuficiente al lanzar | Bootstrap completo 6m + paper-trading 4-8 semanas obligatorio |

**Pregunta**:
- ¿Qué riesgo crítico me falta?
- ¿Algún guardrail que implementarías diferente?
- ¿Stop-loss en %, en time-based, o ambos?

### Q6 — Métricas success/abort para gates de cada fase

¿Qué KPIs definen un GO al siguiente phase y qué KPIs definen ABORT?

Mi propuesta tentativa:

| Gate | GO si | ABORT si |
|---|---|---|
| F4→F5 (backtest→paper) | sharpe backtest >1.5, win rate >55%, N>500 | sharpe <0.5 o win rate <50% |
| F5→F6 (paper→microcapital) | sharpe paper >1.0 sostenido 4 semanas, drawdown max <15% | drawdown >25% o sharpe <0 |
| F6→F7 (microcapital→scale) | edge confirmado en LIVE, PnL>0 en 4/6 semanas | PnL<0 sostenido 3 semanas |

**Pregunta**: ¿Apruebas o ajustas umbrales?

---

## §4 · Recursos disponibles en Dallas (confirmados a las 15:55 UTC)

| Recurso | Estado | Notas |
|---|---|---|
| GPU | A100 40GB libre (1.5GB usado) | Compute backtest sin coste |
| CPU | i9 / Xeon class | Suficiente para scraper continuo |
| RAM | Probable 64-128GB | Pendiente confirmar |
| Disco | 40GB libre en /srv (82% usado) | ⚠️ Limpiar o ampliar antes de poblar DB |
| Postgres | Activo, ya usado por profitlab_quantum_db | Crear DB nueva `toxicflow_db` |
| Nginx | Activo, ya sirve `inicio.velocityquant.io` | Añadir vhost `toxicflow.velocityquant.io` |
| Network | Connection bingx, hyperliquid, ya validado | Latencia ~80-150ms a APIs públicas |
| Existing Python venv stack | FastAPI, psycopg2, requests, pandas, numpy en multiple proyectos | Reusable |

---

## §5 · Out of scope explícito (NO firmar)

NO se contemplan en este brief, los descarto explícitamente:

- ❌ Sandwich attacks (necesita private mempool, capital >$500K, no competitivo a nuestra escala)
- ❌ Spoofing / wash trading / pump-dump (ilegal)
- ❌ Front-run de anuncios privados (insider, ilegal)
- ❌ Integración con V4 cyclic o con QuantumBot PPO (regla Marco: tracks separados)
- ❌ Operar en DEX no transparentes (no aplicable la estrategia)
- ❌ Capital inicial >$500 sin paper-trading 4 semanas validado

---

## §6 · Ventana temporal y siguientes pasos

- **Hoy 17:46 UTC**: deploy V4 SHADOW (paralelo, no afecta este brief)
- **Hoy 18:00 UTC**: r149 con resultados deploy V4 → tu firma
- **Hoy ~21:00 UTC**: pido firma de este r152 con respuestas Q1-Q6
- **Vie 8 - Sáb 9**: si firma, arranco F1 (scaffolding) en paralelo a NFP
- **Lun 12**: primer LIVE V4 microcapital + arranque F2 toxicflow bootstrap DB
- **Lun 26**: target F4 backtest cerrado, GO/ABORT para F5
- **Jun 9-23**: F5 paper-trading 4 semanas
- **Jul 7**: target F6 microcapital LIVE inicial

Cronograma sujeto a tu firma de Q4.

---

**Spec firmadas previas**: r93 + r107-r148e + r150
**Status**: PROPUESTA toxicflow · pending tu firma Q1-Q6
**Próximo r-number**: r149 post-deploy V4 · r153 con tu firma Q1-Q6 toxicflow
**Capital expuesto LIVE actualmente**: $0 (V4 SHADOW)
**Capital toxicflow**: $0 (no ejecuta hasta paper validado)
