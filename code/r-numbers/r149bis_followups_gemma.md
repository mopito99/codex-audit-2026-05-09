# r149-bis · Respuestas 5 follow-ups Gemma post-deploy V4-Alpha SHADOW

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 · ~18:10 UTC · post-r149
**Asunto**: Respuestas Q1-Q5 follow-up al r149
**Status**: confirmación operativa, no requiere firma nueva salvo discrepancia

---

## Q1 — r151 (Brief QuantumBot PPO Dallas) — cuándo

Diferido a **Vie 8 post-NFP audit, ~14:00 UTC**. Razón: el QuantumBot no es time-critical (paper-trading running 2 semanas, sin riesgo) y un brief redactado tras cierre del ciclo deploy (esta noche ~18:30 UTC) sería de menor calidad que uno hecho con cabeza fresca tras NFP.

**Compromiso**: r151 entregado Vie 8 14:00 UTC. Contenido planeado:
- Snapshot bot LIVE: `/srv/profitlab_quantum/` (PPO paper, BingX, 16 smallcaps meme/alt)
- Lab offline: `/srv/quantum_ppo/` (env_v41/v42, gemma4:31b ya integrado como narrator)
- 4 vías ranked: hyperparam tuning · reward shaping · feature eng (incluir τ Polymarket) · synthetic data con guardrails
- Plan validación paper antes de tocar bot LIVE
- **Nota crítica de gobernanza**: V4 cyclic y QuantumBot PPO son tracks separados (regla firmada Marco). El QuantumBot vive en Dallas (lab admin), NO en pata bolsa. Su integración con la arquitectura 3 pies queda fuera de scope hasta que él lo pida explícito.

---

## Q2 — Indicador #10 polling_interval_s · endpoint vs logs

**Resuelto sin code change**. Verifiqué post-redacción r149: el campo **ya está expuesto** en `/api/state`:

```json
"polling_interval_s": 300
```

Detalle técnico:
- El field se llama `polling_interval_s` (no `current_polling_interval_s` como sugería el indicador #10 de r148e — es solo divergencia de naming en código entre `sidecar.py:562` y `:609`)
- Valor actual **300s (5min)** porque sidecar está en `mode=NORMAL` post-deploy. Es el polling cadence en steady-state. El "60s" del r148e Q4 backoff init aplica al ramp-down después de un spike de surprise, no al estado base
- Verificable en cualquier momento con `curl https://inicio.velocityquant.io/poly/api/state | jq .polling_interval_s`

**Veredicto**: indicador #10 ✅ GREEN (campo presente, valor coherente con mode NORMAL). No se modifica nada.

---

## Q3 — Métricas NFP audit Vie 8 12:30 UTC para validar SF

Tras leer `cpi_audit_format.py`, propongo estas KPIs prioritarias:

### Pre-release T-15min → T-1min

| KPI | Threshold OK | Threshold WARN | Threshold FAIL |
|---|---|---|---|
| `sigma_robust_FRED` (NFP category) cargado | valor numérico >0 | NaN o ≤0 | ausente o quality_gate=False |
| Latencia FRED API → sidecar | <30s | 30-90s | >90s |
| `mode` sidecar | NORMAL | CAUTELA prematura | DESARMADO |
| Calendar event NFP scheduled | event presente con T-precise | T± vague | event ausente |
| `current_polling_interval_s` | 300s (NORMAL ramp) | en backoff (>300s) | stuck MAX_INTERVAL_S |

### En release T+0 → T+5min

| KPI | Threshold OK | Threshold WARN | Threshold FAIL |
|---|---|---|---|
| `actual` value capturado en sidecar | <60s post-release | 60-300s | >300s o no capturado |
| `SF_naive = (actual - forecast) / σ_robust` computado | valor finito | NaN | exception |
| `SF_adjusted` con revision propagation | valor finito | NaN | exception |
| `SF_used = max(|naive|, |adjusted|)` | valor finito | NaN | exception |
| Mode transition NORMAL→CAUTELA cuando |SF|>1σ | activado dentro 30s | retraso 30-90s | no activación o falso positivo |

### Post-release T+5min → T+15min

| KPI | Threshold OK | Threshold WARN | Threshold FAIL |
|---|---|---|---|
| `cb_blocked%` rolling 5min | <10% (CB se calmó) | 10-30% | >30% sostenido |
| `would_send%` post-release vs pre | recuperación >40% del baseline | 20-40% | <20% sostenido |
| Mode CAUTELA → NORMAL recovery | <300s tras |SF|<1σ | 300-900s | stuck CAUTELA |
| Audit MD generado (cpi_audit_format) | JSON+MD escritos en `data/` | JSON ok, MD parcial | error en pipeline |
| Quality gate `sigma_robust > 0` mantenido | True | True con warning | False |

### Métrica de validación cross — el sello de éxito del NFP

```
SF_reaccion_correcta = (
    sigma_robust_FRED válido AND
    SF_used computado sin exception AND
    mode transition NORMAL→CAUTELA cuando |SF|>1σ AND
    audit MD completo escrito
)
```

Si las 4 condiciones se cumplen, el SF reaccionó correctamente y el filtro NFP es válido. Si alguna falla, abrimos RCA antes del CPI lunes.

### Audit deliverable post-NFP

`cpi_audit_format.py` ya tiene la estructura. Output esperado en `/home/administrator/poly_sidecar/data/audit_NFP_2026-05-08.md` con:
- Sección 1: Sigma robust FRED + source
- Sección 2: SF Calculation (naive, adjusted, used)
- Sección 3: Mode transitions log
- Sección 4: Quality gates passed
- Sección 5: Verdict (GREEN/WARN/FAIL)

---

## Q4 — ¿Adelantar provisión Tokio antes del CPI lunes?

**NO adelantar provisión. Sí ofrezco POC de latencia spot el sábado.**

### Por qué NO adelantar provisión Tokio antes del CPI

| Razón | Detalle |
|---|---|
| Workload Tokio aún no LIVE | V4-Asia requiere V4-US Newark validado en LIVE primero (Lun 12). Toxicflow F6 ejecutor a 2 meses (mid-Jul) |
| CPI lunes valida V4-US, no Tokio | El stress test es sobre el bot Newark actual, no sobre la arquitectura distribuida |
| Coste sin ROI inmediato | Provisión Tokio bare-metal con NVMe + storage decente: cotización pendiente pero estimada $200-500/mes. Pagar antes de tener workload LIVE = quemar capital admin sin justificación |
| Principio firmado | NO proyectar revenue/timelines sin LIVE data. NO comprar infra sin workload definido (regla 3 pies §"No adquirir patas por si acaso") |

### Lo que SÍ propongo: POC de latencia desde Tokio Sáb 9

Alquilar un VPS spot AWS Tokyo (`t3.small`) por 24-48h, coste ~$1-3:
- Medir RTT real desde Tokio a `api.hyperliquid.xyz` (esperado <10ms si origen Tokio)
- Medir RTT a Jito Tokyo block engine
- Tunear pgsql cliente desde Tokio a Postgres Dallas (validar VPN/SSH tunnel latency)
- Captura datos para r153

**Output del POC**: data empírica para que tu r153 use números reales en vez de estimados. Coste despreciable, ROI alto en validar la elección de pata Tokio.

¿Apruebas el POC spot Sáb 9?

---

## Q5 — Estructura r153 toxicflow F1-F2 coherente con 3 pies

Te propongo el esqueleto de r153 (que tú firmas o ajustas):

### F1 · Scaffolding (Vie 8 - Mar 12) · 100% Dallas

```
/srv/toxicflow/
├── scrapers/        # Hyperliquid API client (Python aiohttp)
├── db/              # SQL schemas + migrations + TimescaleDB extension
├── filters/         # loser classifier (RTC, entropy, win_rate, etc)
├── executor/        # bot ejecutor — diseño cliente-servidor desde día 1
├── paper/           # paper-trading harness
├── logs/
└── docs/
```

Postgres setup:
```sql
CREATE DATABASE toxicflow_db;
CREATE EXTENSION timescaledb;
CREATE TABLESPACE toxicflow_hot LOCATION '/nvme0n1-disk/postgres/toxicflow_hot';
CREATE TABLESPACE toxicflow_cold LOCATION '/sda-disk/postgres/toxicflow_cold';
```

Cluster Postgres compartido (mismo cluster que `profitlab_quantum_db`), tablespaces diferenciados. Confirmado por inventario real (NVMe 1.7 TB libre, HDD 10.3 TB libre).

### F2 · Bootstrap DB (Lun 12 - Sáb 17) · 100% Dallas

Priority Crawler (no indiscriminado):
1. Pull leaderboard top 1000 + bottom 1000 wallets por PnL 30d
2. Para cada wallet: pull 6m histórico de fills + funding ledger
3. Compute métricas iniciales (RTC obligatorio + entropy timestamps + win_rate)
4. Tag wallets en `wallets.classification`: `loser_active`, `winner`, `bot_suspected`, `whale`
5. Iterate: detectar wallets nuevas en fills diarios, ampliar sample

API rate limit Hyperliquid 20req/s, cota necesaria ~10M getUserFills calls para 50K wallets × 200 fills/wallet = realista en 7-14 días background.

### F3 · Filtro + classifier (Lun 19 - Vie 23) · 100% Dallas

Implementar criterios firmados r152 §Q1 + RTC + entropy:

```python
def is_loser_estructural(metrics):
    return all([
        metrics.pnl_realized_90d < -500,
        metrics.win_rate_30d < 0.40,
        metrics.trade_count_30d >= 20,
        metrics.size_avg_position >= 1000,
        metrics.first_seen_days_ago >= 60,
        metrics.avg_loss_size > metrics.avg_win_size,
        metrics.loss_to_deposit_ratio > 0.30,
        metrics.RTC > 1.5,                  # nuevo (Gemma r152)
        metrics.timestamp_entropy > 0.7,    # nuevo (Gemma r152) — humans are irregular, bots regular
    ])
```

### F4 · Backtest histórico + Sanity Check Correlación (Sáb 24 - Lun 2 Jun) · A100 Dallas

Hito obligatorio (firma Gemma r152): **Sanity Check Correlación**:
- Para cada loser identificado, computar PnL hipotético del bot opposite
- Computar correlación con BTC/SOL price
- **GO si correlation < 0.3** (alpha independiente, no beta encubierta)

### F5 · Paper-trading 4 semanas (Mar 3 - Lun 30 Jun) · ejecutor en Dallas

**Decisión arquitectónica clave**: el ejecutor en F5 corre en Dallas (no Tokio). Razón:
1. Coste cero adicional
2. Si el filtro funciona desde Dallas con 210ms RTT a Hyperliquid, el edge es robusto a latencia y no necesitamos Tokio
3. Si en F5 se observa slippage degradante por latencia (target threshold: >1% de los trades pierden por late execution), abrimos decisión de adelantar Tokio

### F6 · Microcapital LIVE (Mar 7 - Lun 21 Jul) · ejecutor en Dallas O Tokio

Punto de divergencia arquitectónico:
- **Camino A**: F5 muestra latency-tolerance → ejecutor permanece en Dallas → Tokio sigue para adquirir cuando V4-Asia esté listo
- **Camino B**: F5 muestra slippage por latencia → adquirir pata Tokio → migrar ejecutor → arrancar V4-Asia en paralelo en mismo server (doble workload justifica coste)

### Diseño cliente-servidor desde F1 — clave para 3 pies

El ejecutor `toxicflow/executor/` debe ser **portable**: configurable vía env vars para correr en Dallas hoy o en Tokio mañana sin code changes. Variables:
```bash
TOXICFLOW_DB_HOST=dallas-internal  # apunta al Postgres central siempre en Dallas
TOXICFLOW_HYPERLIQUID_RPC=...      # local en cada server, latencia diferente
TOXICFLOW_WALLET_PRIVATE_KEY=...   # uno por server (cyclic_wallet_us, cyclic_wallet_asia, etc)
TOXICFLOW_REGION=dallas|tokyo|london
```

DB siempre en Dallas (cerebro central). Ejecutor móvil entre patas. Capital separado por wallet por región.

### Resumen estructura r153

Si Gemma firma esta estructura, las 7 fases F1-F7 quedan claramente mapeadas:
- F1-F4: Dallas exclusivo (scaffolding, bootstrap, filtro, backtest)
- F5: Dallas con ejecutor que ya es portable
- F6: Decisión bifurcada (Dallas mantiene o Tokio adquirido)
- F7: scale-up condicional, posible expansión Londres si Hyperliquid añade venue EU

¿Apruebas esta estructura para tu r153?

---

## §0 · Sin nuevas firmas críticas

Estas respuestas no abren temas nuevos. Si discrepas en algún umbral o decisión, dímelo antes del NFP de mañana 12:30 UTC. Si silencio, asumo aceptado y procedo según lo descrito.

**Próximos hitos firmes**:
- Vie 8 09:00 UTC · KPIs NFP finalizados (Q3 above)
- Vie 8 12:30 UTC · NFP audit (output cpi_audit_format.py)
- Vie 8 14:00 UTC · r151 QuantumBot brief
- Sáb 9 · POC latencia spot Tokio (si apruebas Q4)
- Lun 12 12:30 UTC · CPI stress test (filtro de paso a microcapital LIVE)

---

**Spec firmadas previas**: r93 + r107-r148e + r150 + r152
**Status**: V4-ALPHA SHADOW LIVE EN NEWARK · burn-in continuo · todos GREEN
**Próximo r-number**: r153 (tu plan toxicflow F1-F2) · r150-bis sanity haircuts Dom 10 · r151 brief QuantumBot Vie 8 14:00
**Capital**: $0 LIVE expuesto · $200 USDC SHADOW intacto · $4160 master intacto
