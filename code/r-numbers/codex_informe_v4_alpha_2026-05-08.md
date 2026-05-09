# Informe técnico para Codex · VelocityQuant V4-Alpha cyclic Solana

**Para**: Codex (lectura cruzada también: Fran)
**De**: Marco / Claude operativo (Dallas)
**Fecha**: 2026-05-08 · ~15:00 UTC (Vie 8 May 2026)
**Asunto**: Análisis profundo del bot · evolución de versiones · estado actual · cronograma hasta Mar 12 May
**Tono solicitado por Marco**: estricto pero no destructivo · sin secretos entre Codex/Claude/Gemma · todos los datos crudos sobre la mesa

---

## §0 · Resumen ejecutivo (1 párrafo)

VelocityQuant V4-Alpha es un bot de cyclic arbitrage en Solana on-chain (USDC↔SOL↔USDC vía Raydium/Orca/CLMM/DLMM) en estado **SHADOW puro** desde el deploy del jueves 7 May 17:46 UTC. El bot **NO ha ejecutado ninguna transacción real on-chain en 7+ días** verificado vía journal Newark exhaustivo (3.4M log entries, 0 bundles enviados, 0 tx_signatures, 0 liquidaciones). Todas las cifras de PnL en dashboards son SHADOW theoretical (cycles que el bot detectó como rentables pero nunca ejecutó). El plan firmado prevé el primer LIVE microcapital ($5-10 USDC) el **martes 12 May 13:30 UTC** condicional al sello binario `StressPass_Mar12=True` post-CPI release. Si cualquier check falla, `pause_RCA`. Capital LIVE expuesto actualmente: **$0**. SHADOW intacto on-chain: **$200 USDC**. Master wallet sin relación con bot: $4,160 USDC intactos.

---

## §1 · Evolución de versiones del bot

### V3.5 · Kamino liquidator (legacy, parado desde r146)
- Bot original: liquidaciones del protocolo lending Kamino en Solana
- Dominio: detectar posiciones sub-colateralizadas → liquidar → cobrar bonus liquidator
- **Estado**: parado en r146 (2026-05-07 morning). Crons solana_executor_rs comentados.
- **Razón parada**: pivote estratégico al cyclic arb V4. Track depredador (toma del usuario apalancado liquidado, aunque legítimo per protocol design).
- **Reactivable**: backup binary `liquidator_rs.bak.1777683299` en Newark, capital wallet preservado.

### V4-Alpha · Cyclic arb USDC↔SOL↔USDC (actual, SHADOW)
- Bot actual deployed: cyclic arbitrage entre pools Solana (Raydium AMM, Raydium CLMM, Orca Whirlpools, Meteora DLMM, Lifinity, Phoenix)
- Universo principal: pools USDC/SOL en Raydium + Orca con `phase1` markers
- **Modo actual**: SHADOW puro · `LIQ_CYCLIC_EXECUTE_LIVE=false` · `LIQ_MIN_PROFIT_USD_SHADOW=0.0` (firma r145)
- **Estado run-time**: PID 750904, uptime 21h+ desde 17:46 UTC ayer, RSS 31MB estable, 0 panics
- **No-ataques**: V4 NO hace sandwich, NO hace front-run de retail, NO hace JIT predatory, NO mira mempool víctimas. Solo detecta gaps entre pools y propone arb cyclical de circuito cerrado (USDC→SOL→USDC, neto positivo si el gap supera fees+tip)

### V4 réplicas geográficas planeadas (no ejecutadas aún)
- **V4-US** (= V4-Alpha actual) · Newark · Jito NYC block engine
- **V4-Asia** · Tokyo · Jito Tokyo block engine · pendiente provisión Tokyo post-validación
- **V4-EU** · London · Jito Frankfurt/Amsterdam · pendiente

### Track paralelo independiente: toxicflow (Hyperliquid)
- Bot nuevo scaffolding ayer 7-may
- Estrategia: detectar wallets con PnL negativo estructural en Hyperliquid (transparente on-chain) y tomar opposite-side. Equivalente cripto del PFOF (Citadel/Robinhood) en TradFi
- Estado: F0 scaffolding completado · F1 código pendiente Vie 8+ post-NFP gate
- Cronograma: F1-F4 Dallas exclusivo · F5 paper-trading 4 semanas · F6 microcapital LIVE ~Jul 7+
- **NO se mezcla con V4** (regla firmada Marco)

### Track paralelo independiente: QuantumBot PPO BingX
- Bot LIVE paper-trading desde 23-Abr-2026
- Estrategia: PPO reinforcement learning sobre 16 smallcap memecoins en BingX futures
- **Audit Gemma 4 31B local hoy 06:00 UTC**: bot está en "Policy Stagnation by Training Never Starts". 38,247 decisions/7d pero 0 trades cerrados. Min_samples=32 nunca se alcanza, training never fits. Win rate histórico 31.5% (peor que random). PnL paper acumulado -$49.50 sobre $1,829 peak.
- **Plan refactor**: Top10 train / Top5 trade arquitectura propuesta (firmada Marco · diferida Lun 12 pre-CPI per Gemma cloud "no apresurar")
- **NO se mezcla con V4** ni con toxicflow (regla firmada)

---

## §2 · Spec firmadas relevantes (r93 → r152)

83 MDs entregados a Gemma cloud (Arquitecta Senior) durante 2 meses de iteración. Highlights:

| r-number | Tema | Estado |
|---|---|---|
| r90 | Lógica SF determinista, σ_robust FRED kappa-adjusted (MAD-based) | Firmada · base |
| r93 + r100 | Spec Mathematical foundation Surprise Factor + sigma calibration | Firmada |
| r140 | Circuit Breaker thresholds 22/5/30 (slot_lag trip/reset/auto-reset samples) | Firmada · activa |
| r144 | Q1 Dynamic profit floor binary patch · Q4 Sidecar adaptive backoff · Q5 pre-flight checklist | Firmada · activa |
| r145 §1 | LIQ_MIN_PROFIT_USD_SHADOW=0.0 | Firmada · activa |
| r146 Q3 | Crons solana_executor_rs OFF (V3.5 parado) | Firmada · activa |
| r148 + r148b/c/d/e | Pre-deploy V4-Alpha SHADOW deploy plan | Firmada · ejecutada |
| r149 + bis/tris/quad/pent | Post-deploy summary + 17 follow-ups Q1-Q17 | Firmada · ejecutada |
| r150 | Metodología empírica haircuts SHADOW→LIVE (post-Lun 12) | Firmada · pendiente ejecución |
| r150-bis + tris | RCA migration FMP→FRED+BLS + Q23-Q26 follow-ups | Firmada hoy 14:30 UTC |
| r152 | Roadmap toxicflow Hyperliquid F1-F7 | Firmada con 3 condiciones |
| r153 | Plan F1-F2 toxicflow con arquitectura 3 pies integrada | Estructura aprobada |

Ningún waiver permitido en checks bloqueantes (firma cloud).

---

## §3 · Estado real actual (vie 8 may ~15:00 UTC, sin ningún número inventado)

### Capital
- **Hot cyclic wallet** `<REDACTED-WALLET-HOT200>`: **$200 USDC** SHADOW · intacto on-chain
- **Master wallet** `<REDACTED-WALLET-MASTER>`: **$4,160 USDC** · sin relación con bot · intacto
- **LIVE expuesto**: **$0**
- **Realized profit total LIVE**: **$0.00**
- **Realized trades LIVE total**: **0**

### Bot V4-Alpha en Newark
- **Service**: `liquidator_rs.service` active running
- **Binary**: `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs` · 15.7 MB · build 7-may 06:29 UTC
- **PID**: 750904 · etime 21h+ desde restart 17:46 UTC ayer
- **Memory**: RSS 31MB estable (techo 60MB, no leak)
- **Panics 24h**: 0
- **Circuit Breaker** :9091 endpoint healthy con thresholds firmados r140 (TRIP=22, RESET=5, AUTO_RESET=30)

### Sidecar Polymarket en Dallas (cuandeoro)
- `vq-poly-sidecar` (data loop) · `vq-poly-api` (HTTP server :8090) · ambos active
- Migrado HOY 13:00-14:15 UTC de FMP → FRED+BLS+forecasts (RCA por FMP HTTP 402 desde 7-aug-2025)
- **Pipeline funcional**: BLS captura actuals NFP/CPI/PCE/Unemployment · FRED captura release dates · forecasts.json manual (consensus) cargado
- **Estado**: status=ok, errors=0, tracked events=4 (CPI Mar 12, PPI Mar 13, Retail Sales Mar 14, JOLTS pasado)

### SHADOW production data (cycles teóricos, NO ejecutados)
- Cycles SHADOW 24h: 432K (data del JSONL writeable cyclic_shadow.jsonl)
- Theoretical SHADOW PnL diario reportado por dashboard: cifras computed real desde JSONL pero **NO realizados** porque LIQ_CYCLIC_EXECUTE_LIVE=false
- Win rate SHADOW: ~100% (sesgo trivial: el bot solo loguea cycles donde detecta gap rentable, no contar fails de ejecución porque no hay ejecución)
- Avg profit per cycle theoretical: ~$0.014 (median)

### KPIs de salud del run pre-NFP gate
- would_send%: oscila 11-73% según hora UTC y congestión Solana
- cb_blocked%: oscila 0-73% según slot_lag (network Solana mainnet ha estado degradada nocturna en últimas 24h)
- slot_lag avg: ~3-9 (vs threshold TRIP=22)

---

## §4 · Eventos críticos de hoy 8 May 2026

### 12:30 UTC · NFP release Vie 8 (gate FAILED)
- **Causa raíz**: FMP API caída con HTTP 402 (Payment Required) desde Jue 7 ~22:00 UTC. FMP cambió pricing model 2025-08-31, endpoint `economic_calendar` se movió de free a paid tier.
- **Sello SF_reaccion_correcta**: **FALSE** (6 de 7 checks bloqueantes en FAIL por cascada del input ausente)
- **Decisión**: `pause_RCA` per cronograma firmado
- **Negligencia detectada**: Claude no chequeaba `fmp.status="stale"` en status sweeps. Memoria persistente añadida: regla obligatoria de chequear data-input dependencies en cada status sweep (4 capas: service health, internal state, DATA INPUT, end-to-end audit).

### 13:00-14:15 UTC · Migration emergency a gov APIs
- Decisión Marco firmada: **Opción E** (FRED + BLS + manual forecasts.json)
- Implementado en 75 minutos:
  - `bls_client.py` — BLS API actuals NFP/CPI/Unemployment ($0, gov)
  - `fred_calendar_client.py` — FRED release/dates endpoint ($0, gov)
  - `forecasts.json` — consensus forecasts manual curados de Investing.com (Marco entró CPI YoY=3.3% para Mar 12)
  - `fmp_compat.py` — drop-in replacement de FMPClient (1 line change en sidecar.py)
  - Sidecar restarted, status=ok, CPI Mar 12 12:30 UTC en next_event con estimate=3.3 cargado
- **NFP actual retroactivo computado**: BLS reporta NFP April +115K (vs forecast 62K) → SF=0.24σ → mode NORMAL es correcto. El bug fue el provider, no la lógica.

### 14:30 UTC · Firma Gemma cloud r150-bis-RCA
- **Veredicto**: NO APTO para escala de capital. Régimen Mar 12 = micro-capital ($5-10) si gate verde, NO escalable.
- **Requisito para LIVE EXECUTE**: implementar A (investing_client scraping automation) **O** B (validador rangos + linter JSON + doble firma SHA256). Sin esto, no hay LIVE.
- **Decisión Marco**: **B para Mar 12** (implementable Sáb 9 morning) + **A semana 13-19 May** para automatización permanente.

### 14:45 UTC · Firma Gemma cloud r150-tris (Q23-Q26 follow-ups)
- Forecasts.bak versionado físico con timestamp+hash
- Tokyo POC tier1+tier2+tier3 KPIs definidos
- BLS unresponsive fallback sequence 5 steps (BLS API → RSS → FRED → manual inject → pause_RCA)
- Escalado capital por hitos cuantitativos NO calendario (Fase 1 microcapital $5-10 → Fase 4 scale $2K-10K)
- Auto-rollback si drawdown >25% / 3 panics / win rate <35% sostenido 7d

### 15:00 UTC · Status final del día
- **GREEN FOR IMPLEMENTATION (B-Plan)** firmado por Gemma cloud
- 2 artefactos entregados ya: `restore_last_valid.sh` + `POC_TOKYO_TEMPLATE.json`
- Pendientes Sáb 9 morning: validator, sign_forecasts, integración SF→mode, Tokyo POC

---

## §5 · Plan operativo Vie 8 → Mar 12 May

### Sáb 9 May
- 09:00-12:00 UTC · `forecasts_validator.py` (10 metric ranges + 5 quality gates) + `sign_forecasts.py` (SHA256 + interactive confirm) + integración con fmp_compat
- 13:00-15:00 UTC · Conectar SF compute → mode transition NORMAL/CAUTELA en sidecar.py + tests backfill (forzar SF=1.5σ simulado, validar mode→CAUTELA)
- 15:00-18:00 UTC · Tokyo POC: provisión VPS spot AWS Tokyo (`t3.small` ~$2-5/24h), capturar 5 KPIs Tier1 + 5 edge cases Tier2, output a `POC_TOKYO_2026-05-09.json` per template

### Dom 10 May
- Morning · `r150-bis_sanity.md` (sanity check haircuts empíricos pre-LIVE, metodología r150)
- Afternoon · Continuar Tokyo POC samples (00:00, 06:00 UTC sets para time-of-day variability)
- Evening · Marco re-verifica CPI consensus en Investing.com/Bloomberg/CNBC. Si cambió → update forecasts.json + double-sign nuevo hash

### Lun 11 May
- Morning · Pre-CPI final verification (todo el stack)
- Evening · Smoke tests + Marco autoriza listo para gate

### **Mar 12 May (gate day)**
- 12:00 UTC · Pre-flight check automático (12-checks StressPass_Mar12 dry-run)
- 12:25 UTC · Activate verbose logging sidecar
- **12:30 UTC · CPI release** · BLS publica actual · sidecar captura · SF se computa
- 12:45 UTC · Compute `StressPass_Mar12` (12 checks must ALL be TRUE):
  1. forecasts.json JSON valid + range_check pass
  2. sigma_robust_FRED CPI=1.232426 sin override
  3. BLS actual capturado <120s post-release
  4. SF_used finite (no NaN/Inf)
  5. Mode transition correcta vs predicción
  6. Audit MD generado en data/
  7. CB endpoint :9091 responding throughout
  8. 0 panics liquidator_rs T+0→T+15min
  9. RSS estable <60MB
  10. cb_blocked% post-T+5min <30%
  11. would_send% recovery >40%
  12. Pre-flight check 12:00 verde
- 13:00 UTC · Decision Marco: `microcapital_LIVE` o `pause_RCA` con 3 frases evidencia
- **13:30 UTC · Si TRUE → systemctl restart liquidator_rs con `LIQ_CYCLIC_EXECUTE_LIVE=true` + capital $5-10** = primer LIVE histórico

---

## §6 · Riesgos honestos (sin pintar)

### Técnicos
- **Forecasts.json manual**: regresión vs spec r90 deterministic-data. Mitigación parcial con validator+linter+doble firma. Riesgo residual: Marco entra typo o consensus dinámico cambia entre Dom 10 y Mar 12 sin re-verify.
- **BLS API latency**: gov gratis pero 30-60s de lag vs feeds comerciales. Suficiente para microcapital. Para escala futura, Bloomberg Terminal ($24K/año) es la única opción industria-grade.
- **Solana network congestión**: variable independiente fuera de nuestro control. CB protege bien (244 trip/reset events sin escalada en burn-in 11h).
- **Edge real desconocido**: SHADOW dice gaps de $0.014 median per cycle pero ese número incluye NO ejecución. Haircut SHADOW→LIVE real: NULL hasta tener N≥20 trades realizados Mar 12+.

### Operacionales
- **Gemma cloud lock**: arquitectura LOCKED hasta CPI Mar 12 13:00 UTC. Cualquier sugerencia técnica fuera del manual de operaciones requiere nuevo ciclo de firmas.
- **Negligencia operativa cazada hoy**: no chequeo de data-input dependencies en status sweeps. Memoria persistente actualizada para no repetir.
- **2 Gemmas distintas**: Cloud (firma autoritativa, solo vía Marco copy-paste) vs 31B local Ollama (asesor técnico sin firma). Caso de mala atribución cazado hoy. Memoria persistente para distinguir.

### De estimación
- **Cronograma Mar 12 ajustado**: 4 días para implementar B-Plan + Tokyo POC + sanity haircuts + pre-CPI. Buffer es adecuado para microcapital, no permite overruns.
- **investing_client.py debug semana 13-19**: 2-3 días dev estimados pero scraping puede tener edge cases imprevisible (HTML changes Investing.com, IP block).

---

## §7 · Lo que NO sabemos (humildad)

- Haircut real SHADOW→LIVE de NUESTRO bot: **0 data points hasta Mar 12+**.
- Edge real diario en cyclic arb Solana para nuestro stack actual: **NULL hasta N≥20 trades LIVE**.
- Capacity del wallet a tamaño $200 vs $5K vs $50K: no medido (solo inferido teóricamente desde liquidez de pools).
- Edge degradación post-Lun 12 LIVE: depende de cuántos searchers compiten en mismo gap. No predecible ex-ante.
- Resultados Tokyo POC: están por capturarse Sáb 9. Hipótesis "Tokyo es 5x más rápido a Hyperliquid" pendiente de verificar.

---

## §8 · Lo solicitado a Codex

Marco pide audit técnico estricto pero no destructivo. Específicamente:

1. **Validación arquitectónica**: ¿el approach FRED+BLS+forecasts es sólido o hay ciegos no detectados?
2. **Validación del StressPass 12-checks**: ¿son threshold razonables o demasiado laxos/estrictos?
3. **Validación cronograma Mar 12**: ¿es viable B-Plan + microcapital LIVE en 4 días o estamos forzándolo?
4. **Validación regla escalado cuantitativo Q26**: ¿las 4 fases con hitos numéricos son industry-standard o hemos inventado?
5. **Riesgos no detectados**: ¿qué nos falta ver?

Marco quiere honestidad técnica completa. Sin pintar de bonito ni catastrofizar. Si hay problemas serios, decirlos. Si todo OK, decirlo. Sin proyección de revenue ni multiplicadores fictionales.

---

## §9 · Material disponible para que Codex profundice

Todos los archivos relevantes en filesystem cuandeoro Dallas (acceso vía SSH si necesario):

- `/home/administrator/poly_sidecar/` — sidecar Python (FastAPI + data loop)
- `/home/administrator/r1*.md` — 83 specs MDs firmados (algunos linkados arriba)
- `/home/administrator/.claude/projects/-home-administrator/memory/` — memoria persistente con feedback rules
- `/srv/v4_deploy/pre_deploy_check.sh` — checklist 13 checks que ya pasó GREEN ayer pre-deploy
- Newark via SSH `ubuntu@64.130.34.38` — bot V4 actual
- Dashboard público `https://inicio.velocityquant.io/poly/pnl/dashboard.html` (basic auth)
- Workspace toxicflow `https://toxicflow.velocityquant.io/` (público, placeholder)

Sin secretos. Cero info propietaria intencionalmente ocultada.

---

**Status final**: V4-Alpha SHADOW estable · GREEN FOR IMPLEMENTATION B-Plan Sáb 9 · Capital LIVE $0 · primer LIVE microcapital $5-10 condicional StressPass_Mar12=True · Mar 12 13:30 UTC.

**Próximo r-number**: r150-bis_sanity (Dom 10) · POC_TOKYO_2026-05-09.json (Sáb 9 evening) · r154 post-CPI (Mar 12 14:00 UTC).
