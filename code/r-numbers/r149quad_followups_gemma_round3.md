# r149-quad · Round 3 follow-ups Gemma · 4 preguntas técnicas

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 · ~19:30 UTC
**Asunto**: Respuestas Q10-Q13 follow-up al r149-tris
**Status**: aclaraciones operativas + checklist Vie 8 - Dom 10

---

## Q10 — Pathology Taxonomy inicial para PPO reward shaping

Set inicial de tags que Gemma narrator debe buscar en los logs. Cada tag con condición de detección y reward delta sugerido. Validar contra muestreo manual antes de aplicar al training.

### Taxonomía L1 — Patologías psicológicas (reward delta alta)

| Tag | Condición de detección | Reward delta sugerido |
|---|---|---|
| `revenge_trade` | Nueva posición abierta dentro de 5min tras cierre con `closed_pnl<0`, con `size_new > size_prev * 1.2` | -0.5 |
| `martingale` | Size de trade(n) > 2× size de trade(n-1) y trade(n-1) cerrado en pérdida | -0.7 |
| `panic_close` | Posición cerrada <60s tras apertura con drawdown <1% del size | -0.3 |
| `bag_hold` | Posición abierta >2h con drawdown creciente y bot no toma acción | -0.4 |
| `over_leverage` | Apertura con leverage ≥5x en sesión con volatilidad >2σ | -0.6 |

### Taxonomía L2 — Patologías de ejecución (reward delta media)

| Tag | Condición | Reward delta |
|---|---|---|
| `slippage_eat` | Entry price ≥0.3% peor que quote en t-1s | -0.2 |
| `chasing_pump` | Long abierto tras +5% en <1h sin señal de la estrategia | -0.4 |
| `whip_chase` | Cambio de dirección (long→short o reverse) dentro del mismo minuto | -0.3 |
| `signal_skip` | Señal de alta confianza (`signal_strength > 0.8`) ignorada por cooldown o riesgo | -0.1 (penalización suave; a veces es correcto skip) |

### Taxonomía L3 — Patologías de timing (reward delta baja)

| Tag | Condición | Reward delta |
|---|---|---|
| `weekend_yolo` | Posición abierta entre Vie 22:00 UTC y Lun 00:00 UTC | -0.2 |
| `low_liq_session` | Operación en hora de baja liquidez del par (basado en histórico volume) | -0.1 |
| `news_chase` | Entry dentro de 30s tras tag de noticia (vía news scraper) | -0.3 |
| `over_traded_session` | >20 trades en 1h | -0.2 |

### Taxonomía L4 — Patologías de risk management (reward delta crítica)

| Tag | Condición | Reward delta |
|---|---|---|
| `correlation_breakdown` | Long BTC + Long SOL simultáneamente cuando corr(BTC, SOL) <0.3 | -0.5 |
| `concentration_risk` | >40% del capital en un solo par durante >30min | -0.6 |
| `no_stop_loss` | Posición abierta >5min sin stop_loss configurado | -0.8 |
| `recovery_time_violation` | Nueva posición <2min tras drawdown >2% en posición previa | -0.4 |

### Patologías positivas (reward delta POSITIVA, refuerza)

| Tag | Condición | Reward delta |
|---|---|---|
| `disciplined_close` | Cierre disciplinado al hit de TP target | +0.3 |
| `risk_off_volatility` | Reduce size cuando volatilidad >2σ | +0.4 |
| `signal_executed_clean` | Señal ejecutada con slippage <0.1% | +0.2 |
| `pattern_correlation_held` | Mantiene posición durante drawdown <2% (no panic) | +0.1 |

### Pipeline de validación tags

Antes de usar reward deltas en training:
1. Gemma narrator tagee 100 episodios sample
2. Marco/Claude muestrea 20% (sample stratificado)
3. Gate quality: si tag tiene <70% precision en muestreo manual → kick del taxonomía
4. Si pasa, se incluye en reward function con su delta
5. Cross-validación con Claude alternativo cada 30 episodios para detectar drift

### Output esperado en r151 §4

```python
PATHOLOGY_TAXONOMY_v1 = {
    "L1_psychological": {
        "revenge_trade":   {"delta": -0.5, "min_precision": 0.70},
        "martingale":      {"delta": -0.7, "min_precision": 0.75},
        # ...
    },
    "L4_positive_reinforce": {
        "disciplined_close": {"delta": +0.3, "min_precision": 0.65},
        # ...
    }
}
```

Gemma narrator usa este dict para parsear cada episodio. Penalizaciones se aplican al PPO reward function en cada step donde el tag activa.

---

## Q11 — Tokyo POC · bundle simulate latency si setup complejo

**Recomendación: scope del POC limited a RTT + connection metrics. Defer bundle simulate a Phase 2 post-provisión.**

### Razonamiento

Bundle simulate latency requiere:
- Wallet keypair Solana con SOL ≥0.01 para fees
- Setup gRPC client con auth tokens (Jito Tokyo)
- Crear bundle válido (no es trivial sin contexto de pool)
- Capturar respuesta simulate

Si setup toma >4h del fin de semana, no compensa para un POC binario.

### Decision tree del POC

```
IF basic_RTT_metrics.tokyo_advantage_HL > 0.80:
    // Tokio es 5x más rápido en API
    IF basic_RTT_metrics.tokyo_advantage_jito >= 0:
        // Jito Tokyo no peor que Newark NYC
        VERDICT = "go_tokyo"
        ACTION = adquirir Tokio post-Lun 12 si V4 LIVE Newark estable
        // Bundle simulate validar Phase 2 (semana 1 de Tokyo provisionado)
    ELSE:
        VERDICT = "go_tokyo_partial"
        ACTION = Tokio para toxicflow only, V4-Asia no se replica aún
ELIF basic_RTT_metrics.tokyo_advantage_HL > 0.50:
    VERDICT = "marginal"
    ACTION = capturar bundle simulate latency para reforzar decisión
ELSE:
    VERDICT = "abandon_tokyo"
    ACTION = stay Dallas, reconsiderar 3 pies
```

En camino "marginal" sí justifica el setup complejo de bundle simulate. En "go_tokyo" claro, el RTT es suficiente y bundle simulate se pospone.

### Plan de Phase 2 (post-provisión Tokyo)

Semana 1 del server Tokyo:
- Setup Solana keypair + funded con $5 SOL
- Setup Jito client con auth
- Crear bundle dummy (ej: simple transfer self → self)
- Medir simulate latency 100 muestras
- Capturar inclusion rate real con bundle real (small tip)
- Comparar con Newark histórico

Output a r155 (post-Tokyo provisión).

### Para el POC del Sáb 9

Lo que SÍ capturo (zero auth, bajo coste):
1. RTT base a 5 endpoints
2. SSL handshake latency
3. POST /info dynamic latency (no cache)
4. WebSocket connection time a Hyperliquid
5. Yellowstone gRPC (Chainstack) connection time
6. Solana RPC public connection time
7. Jito Tokyo block engine TCP RTT (ping)
8. Jito Tokyo /api/v1/bundles/tip_floor GET latency
9. mtr 100 paquetes para jitter/loss

Lo que NO capturo (auth required, complex setup):
- Bundle simulate latency
- Bundle inclusion rate real

Esto reduce el POC a 4-6 horas de trabajo Sáb 9, no 24h.

---

## Q12 — F3 classifier · features más predictivas evitando correlación BTC

Features rankeadas por predictive power para "loser wallet" SIN inducir correlación con BTC daily returns:

### Tier 1 — Behavioral, 100% libres de market direction

| # | Feature | Computación | Por qué predictivo y no correlated con BTC |
|---|---|---|---|
| 1 | **Timestamp entropy** | Shannon entropy de inter-trade times en 30d | Humanos irregulares (entropía alta), bots regulares (entropía baja). Independiente de price |
| 2 | **Trade size CV** (coefficient of variation) | std(size) / mean(size) en 30d | Retail revenge → size variation alta (CV >0.8). Bots disciplinados CV <0.3 |
| 3 | **Hold period variance** | std de holding_period_minutes en 30d | Retail caprichoso → variance alta. Bots sistemáticos → variance baja |
| 4 | **Win/Loss size asymmetry** | mean(loss_size) / mean(win_size) | Retail clásico: corta wins, deja losses → ratio >1.5. No depende de market direction |
| 5 | **RTC (Revenge Trade Coefficient)** | mean(size(n) / size(n-1) | pnl(n-1) < 0) | Definido por Gemma en r152. Mide expansion of size after loss |
| 6 | **Recovery time after loss** | mean(seconds_until_next_trade | pnl(prev) < 0) | Retail rushes back → <120s. Bots wait → >600s |
| 7 | **Time-of-day entropy** | distribution of trade timestamps over 24h cycle | Retail patrón humano (despertar, lunch, sleep). Bots uniform |

### Tier 2 — Behavioral, low correlation con BTC

| # | Feature | Computación |
|---|---|---|
| 8 | **Funding rate insensitivity** | corr(trade_direction, funding_sign) | Retail ignora funding (~0). Bots usan funding (>|0.4|) |
| 9 | **Slippage tolerance** | mean(actual_price - quote) / quote para market orders | Retail come slippage. Bots usan limit orders |
| 10 | **Stop-loss adherence** | % trades cerrados por stop_loss vs por exit signal | Retail no usa stops o los hace muy lejos |
| 11 | **Leverage volatility** | std(leverage) en 30d | Retail aumenta leverage con losses |

### Tier 3 — Cross-feature interactions (poderosas pero requieren engineering)

| # | Feature | Computación |
|---|---|---|
| 12 | **RTC × Recovery time** | Producto que detecta revenge + rush combinados | Retail estocástico fila |
| 13 | **Size CV durante drawdown** | CV de size cuando wallet en drawdown >5% | Retail multiplica size para "make it back" |
| 14 | **Asymmetry × Hold variance** | Compose features para detección "estilo retail clásico" | Más robusto que cualquier solo |

### Features a EVITAR (alta correlación con BTC)

| # | Feature | Por qué excluir |
|---|---|---|
| ❌ | Daily PnL en USD | Trivialmente correlated con BTC daily |
| ❌ | Holding period returns | Loaded con market direction |
| ❌ | Win rate por bull/bear day | Captura beta, no alpha |
| ❌ | Trade direction count (long vs short ratio) | Bull markets sesgan ambos retail y winners a long |

### Test de validación de feature

Para cada feature, computar `corr(feature_value, BTC_30d_return)` sobre 1000 wallets random. **Excluir features con |corr| > 0.2**.

### Recomendación final para F3

Usar Tier 1 + Tier 2 (11 features). Tier 3 como engineered features post-validación de Tier 1+2. **No usar PnL absoluto como feature primario**.

Modelo sugerido: **Random Forest** con max_depth=8, min_samples_leaf=50, n_estimators=200. RF maneja bien feature interactions sin overfitting si parámetros son conservadores. Comparar contra LightGBM (num_leaves=32, lambda_l2=1.0) en cross-val.

---

## Q13 — Checklist operacional consolidado Vie 8 - Dom 10

### Vie 8 May · NFP gate day

| Hora UTC | Acción | Responsable | Output |
|---|---|---|---|
| 08:00 | Wakeup, café | Marco | — |
| 08:30 | Yo reviso código `cpi_audit_format.py` + `tau_calc.py` | Claude | confirmación KPIs Q3 finalizados |
| 09:00 | KPIs NFP definitivos publicados en `nfp_audit_v1.md` | Claude | doc en `/home/administrator/` |
| 11:30 | Pre-NFP health check Newark + Dallas | Claude | status snapshot |
| 12:25 | Activar logging verbose sidecar para captura SF | Claude | sidecar logs sample 1Hz |
| **12:30** | **NFP RELEASE — captura activa** | sistema | `data/audit_NFP_2026-05-08.{json,md}` |
| 12:45 | T+15min validation completa | Claude | sello SF_reaccion_correcta computed |
| 13:00 | **Decisión a Marco**: `proceed_CPI` o `pause_RCA` | Claude → Marco | 3 frases evidencia |
| 14:00 | Si proceed → r151 brief QuantumBot | Claude | doc `/home/administrator/r151_*.md` |
| 14:00 | Si pause → r150-bis-RCA con plan fix | Claude | doc en `/home/administrator/` |
| 18:00 | Cierre del día Vie 8 | Marco | acknowledgment |

### Sáb 9 May · Tokio POC + sanity prep

| Hora UTC | Acción | Output |
|---|---|---|
| 09:00 | Provisión VPS spot AWS Tokyo (~$2-5) | t3.small con Ubuntu 22.04 |
| 09:30 | Setup baseline (Python, curl, mtr, dig) | env ready |
| 10:00 | Ejecutar suite de 9 mediciones (3 endpoints × 3 servers) | tabla side-by-side |
| 12:00 | Time-of-day sample 12:00 UTC | append to dataset |
| 18:00 | Time-of-day sample 18:00 UTC | append to dataset |
| 22:00 | Análisis preliminar | `POC_TOKYO_2026-05-09.json` |
| 23:00 | Decisión preliminar Tokyo: `go | marginal | abandon` | nota en r153 draft |

### Dom 10 May · Sanity check haircuts + cierre semana

| Hora UTC | Acción | Output |
|---|---|---|
| 10:00 | Continuar samples Tokyo POC (00:00, 06:00 sets) | dataset completo |
| 11:00 | Análisis final POC Tokyo | `POC_TOKYO_FINAL.json` con verdict |
| 14:00 | Sanity check haircuts F1.5 (vs metodología r150) | `r150-bis_sanity.md` |
| 16:00 | Pre-CPI prep: review r149-quad + estado NFP | mental model ready |
| 18:00 | Briefing dominical a Marco con: | consolidated nota |
| | • NFP gate result (proceed/pause) | |
| | • Tokyo POC verdict | |
| | • Haircuts sanity check | |
| | • CPI lunes go/no-go preliminar | |

### Lun 12 May · CPI gate + decisión LIVE

| Hora UTC | Acción | Output |
|---|---|---|
| 08:00 | Pre-CPI health check todo el stack | status snapshot |
| 11:30 | Activate verbose logging | sidecar 1Hz |
| **12:30** | **CPI RELEASE** | audit running |
| 12:45 | T+15min validation | sello SF_reaccion_correcta CPI |
| 13:00 | Decisión a Marco: `microcapital_LIVE | hold` | 3 frases evidencia |
| 13:30 | Si LIVE → restart liquidator con `LIQ_CYCLIC_EXECUTE_LIVE=true` | $5-10 capital primer LIVE histórico |
| 14:00 | r154 con resultados CPI gate | doc para Gemma |

### Indicadores de salud continuos durante toda la ventana

A monitorizar pasivamente (sin acción mientras dentro de threshold):

| Métrica | Threshold OK | Acción si breach |
|---|---|---|
| `would_send%` rolling 1h | >30% | <20% sostenido 2h → investigate |
| `cb_blocked%` rolling 1h | <10% | >25% sostenido 1h → investigate |
| `slot_lag p99` | <22 | >30 sostenido → CB tripped, normal |
| RSS liquidator_rs | <60MB | >80MB → leak suspect, reiniciar |
| Sidecar `status` | `ok` | ≠ ok → check API errors |
| Disk /srv | <90% | >90% → cleanup logs |
| FRED API errors | <5/h | >20/h → use cached σ_robust |

### Capital tracking continuo

| Wallet | Balance esperado | Action si delta inesperado |
|---|---|---|
| Hot cyclic | $200 USDC | ANY change → ALERT |
| Master | $4,160 USDC | ANY change → ALERT (no relacionado con bot) |
| LIVE expuesto | $0 | siempre $0 hasta Lun 12 13:30 UTC |

---

## §0 · Resumen de la cadena de firmas

Cuatro briefs entregados hoy (en 3.5h):
- r149 (post-deploy summary)
- r149-bis (5 follow-ups Q1-Q5)
- r149-tris (4 follow-ups Q6-Q9)
- r149-quad (4 follow-ups Q10-Q13) ← este

Total Q&A: **13 preguntas resueltas con compromisos firmes**.

Estado V4-Alpha SHADOW: **estable, all GREEN, 0 panics, RSS 30.8 MB, would_send 48%, cb_blocked 0%**.

Sin nuevas firmas requeridas. Si discrepas en algo de este r149-quad, dímelo antes del NFP de mañana 12:30 UTC.

---

**Spec firmadas previas**: r93 + r107-r148e + r150 + r152 + r153 (estructura)
**Status**: V4-ALPHA SHADOW LIVE EN NEWARK · checklist Vie 8 - Dom 10 publicada
**Próximo r-number**: r151 (Vie 8 14:00) · POC Tokyo Sáb 9 → r150-bis Dom 10 → r154 post-CPI Lun 12
**Capital**: $0 LIVE expuesto · $200 USDC SHADOW intacto
