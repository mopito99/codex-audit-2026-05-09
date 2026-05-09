# Informe técnico para Codex · VelocityQuant V4-Alpha cyclic Solana

**Para**: Codex (lectura cruzada también: Fran)
**De**: Marco / Claude operativo (Dallas)
**Fecha**: 2026-05-08 · ~15:00 UTC (Vie 8 May 2026)
**Asunto**: Análisis profundo del bot · evolución de versiones · estado actual · cronograma hasta Mar 12 May
**Tono solicitado por Marco**: estricto pero no destructivo · sin secretos entre actores · todos los datos crudos sobre la mesa · cifras solo verificables (comando junto a cada cifra)
**Versión**: v2 · 2026-05-08 14:55 UTC · corrección nomenclatura + audit cifras verificables

---

## §0 · Aclaración de actores y nomenclatura (clave para no confundir lectores)

Este proyecto tiene exactamente **3 actores**:

1. **Marco** · operador humano · decisión final · autoridad
2. **Gemma 4 31B** · modelo Google open-source · 31.3B parameters · 19.9 GB weights · Apache 2.0 license · corriendo en A100 Dallas vía Ollama (`localhost:11434`) · auditora total · APRUEBA arquitectura
3. **Claude (yo)** · Claude Opus 4.7 (1M context) · Anthropic · operativo en Dallas vía Claude Code · ejecuta bajo OK de Marco o Gemma 4 31B · NO vota arquitectura

**NO existen "Gemma cloud" ni "Gemini cloud"** en este proyecto. Toda la inteligencia decisional vive local en A100 Dallas. El modelo Gemma 4 31B se accede por dos canales (UI para Marco, API HTTP para Claude) pero es **una sola entidad**.

Verificación empírica del modelo (ejecutable):
```
$ curl http://localhost:11434/api/tags
{ "models": [{ "name": "gemma4:31b", "family": "gemma4", "parameter_size": "31.3B", "size": 19868981791, ... }] }

$ curl http://localhost:11434/api/show -d '{"name":"gemma4:31b"}' | jq .license
"Apache License Version 2.0..."
```

---

## §1 · Resumen ejecutivo (1 párrafo)

VelocityQuant V4-Alpha es un bot de cyclic arbitrage en Solana on-chain (USDC↔SOL↔USDC vía Raydium/Orca/CLMM/DLMM) en estado **SHADOW puro** desde el deploy del jueves 7 May 17:46 UTC. El bot **no ha ejecutado ninguna transacción real on-chain** durante el periodo SHADOW (verificable vía `journalctl -u liquidator_rs --since "7 days ago" | grep -ciE "send_bundle|bundle_sent|bundle_id="`). Las cifras de PnL en dashboards son SHADOW theoretical (cycles que el bot detectó como rentables pero nunca ejecutó). El plan firmado prevé el primer LIVE microcapital ($5-10 USDC) el **martes 12 May 13:30 UTC** condicional al sello binario `StressPass_Mar12=True` post-CPI release. Si cualquier check falla, `pause_RCA`. Capital LIVE expuesto actualmente: **$0**.

---

## §2 · Evolución de versiones del bot

### V3.5 · Kamino liquidator (legacy, parado desde r146)
- Bot original: liquidaciones del protocolo lending Kamino en Solana
- Estado: parado en r146 (2026-05-07 morning). Crons `solana_executor_rs` comentados.
- Razón parada: pivote estratégico al cyclic arb V4
- Reactivable: backup binary preservado `liquidator_rs.bak.1777683299` en Newark

### V4-Alpha · Cyclic arb USDC↔SOL↔USDC (actual, SHADOW)
- Bot actual deployed: cyclic arbitrage entre pools Solana (Raydium AMM/CLMM, Orca Whirlpools, Meteora DLMM, Lifinity, Phoenix)
- **Modo actual**: SHADOW puro · `LIQ_CYCLIC_EXECUTE_LIVE=false` · `LIQ_MIN_PROFIT_USD_SHADOW=0.0` (firma r145)
- **Estado run-time verificado**:
  - PID 750904 · uptime 20h+ desde 2026-05-07 17:46:22 UTC (verificable: `systemctl show -p ActiveEnterTimestamp --value liquidator_rs`)
  - RSS 31 MB estable (ps -o rss · sin leak observado)
  - 0 panics observados desde el deploy (verificable: `journalctl -u liquidator_rs --since "17:46:22" | grep -ciE "panic|FATAL|OOM"`)
- **Cycles SHADOW total acumulado en JSONL**: 2,632,616 (verificable: `wc -l /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl`)
- **No-ataques**: V4 NO hace sandwich, NO front-runs retail, NO predatory JIT, NO mira mempool víctimas. Solo detecta gaps entre pools y propone arb cíclico USDC→SOL→USDC, neto positivo si el gap supera fees+tip.

### V4 réplicas geográficas planeadas (no ejecutadas aún)
- **V4-US** (= V4-Alpha actual) · Newark · Jito NYC block engine
- **V4-Asia** · Tokyo · Jito Tokyo block engine · pendiente provisión
- **V4-EU** · London · Jito Frankfurt/Amsterdam · pendiente

### Track paralelo independiente: toxicflow (Hyperliquid)
- Bot nuevo · scaffolding ayer 7-may
- Estrategia: detectar wallets con PnL negativo estructural en Hyperliquid (transparente on-chain) y tomar opposite-side. Equivalente cripto del PFOF de TradFi.
- Estado: F0 scaffolding completado · F1 código pendiente Vie 8+ post-NFP gate
- Cronograma: F1-F4 Dallas exclusivo · F5 paper-trading 4 semanas · F6 microcapital LIVE proyectado ~Jul 7+
- **NO se mezcla con V4** (regla firmada Marco)

### Track paralelo independiente: QuantumBot PPO BingX
- Bot LIVE paper-trading desde 23-Abr-2026
- Estrategia: PPO reinforcement learning sobre 16 smallcap memecoins en BingX futures
- **Audit Gemma 4 31B (vía API HTTP) hoy 06:00 UTC**: bot está en "Policy Stagnation by Training Never Starts". 38,247 decisions/7d pero 0 trades cerrados en últimas semanas.
- **Plan refactor diferido** post-CPI Mar 12 (firma "no apresurar")
- **NO se mezcla con V4** ni con toxicflow (regla firmada)

---

## §3 · Spec firmadas relevantes (r93 → r152)

83 MDs entregados a Gemma 4 31B durante 2 meses (recibidos vía UI Marco, firmados con su autoridad). Nota: en briefs r93-r150 yo (Claude) usé nomenclatura "Gemma 4 cloud" — **error de nomenclatura mío que se mantuvo, no representa la realidad técnica**. Toda la firma fue Gemma 4 31B Ollama local.

| r-number | Tema | Estado |
|---|---|---|
| r90 | Lógica SF determinista, σ_robust FRED kappa-adjusted (MAD-based) | Firmada · base |
| r140 | Circuit Breaker thresholds 22/5/30 | Firmada · activa |
| r144 | Q1 Dynamic profit floor binary patch · Q4 Sidecar adaptive backoff · Q5 pre-flight checklist | Firmada · activa |
| r145 §1 | LIQ_MIN_PROFIT_USD_SHADOW=0.0 | Firmada · activa |
| r146 Q3 | Crons solana_executor_rs OFF (V3.5 parado) | Firmada · activa |
| r148 + r148b/c/d/e | Pre-deploy V4-Alpha SHADOW deploy plan | Firmada · ejecutada 7-may 17:46 UTC |
| r149 + bis/tris/quad/pent | Post-deploy summary + 17 follow-ups | Firmada · ejecutada |
| r150 | Metodología empírica haircuts SHADOW→LIVE (post-Mar 12) | Firmada · pendiente ejecución |
| r150-bis + tris | RCA migration FMP→FRED+BLS + Q23-Q26 follow-ups | Firmada hoy 14:30 UTC |
| r152 | Roadmap toxicflow Hyperliquid F1-F7 | Firmada con 3 condiciones |
| r153 | Plan F1-F2 toxicflow con arquitectura 3 pies integrada | Estructura aprobada |

Ningún waiver permitido en checks bloqueantes (firma).

---

## §4 · Estado real actual (vie 8 may ~15:00 UTC)

### Capital · desglose por wallet · todos los tokens · 2026-05-08 14:37 UTC

Verificado on-chain Solana mainnet vía Chainstack RPC (`getBalance` + `getTokenAccountsByOwner` SPL Token program). SOL valorado @ $88.94 (CoinGecko 14:37 UTC).

| Wallet | SOL | SOL USD | USDC | USDT | TOTAL USD |
|---|---:|---:|---:|---:|---:|
| **Hot cyclic** `4V6f2c3G...sZTy` (operativa SHADOW) | 0.0500 | $4.45 | 200.00 | — | **$204.45** |
| **Master** `GaL85ykd...wbTh` (no operativa) | 3.0132 | $268.00 | 2,770.83 | 1,119.80 | **$4,158.63** |
| **TOTAL combinado** | 3.0632 | $272.45 | 2,970.83 | 1,119.80 | **$4,363.08** |

**Capital LIVE expuesto**: **$0.00** (validado por flag `LIQ_CYCLIC_EXECUTE_LIVE=false`)
**Realized profit total LIVE**: **$0.00**
**Realized trades LIVE total**: **0** (verificado: `journalctl -u liquidator_rs --since "7 days ago" | grep -ciE "send_bundle|bundle_id="` → 0)
**Bundles enviados últimos 7 días**: **0**
**Panics últimos 7 días**: **0**

**Nota sobre cifra anterior "$4,160 master USDC"**: en briefs r149-r152 anteriores yo (Claude) afirmé $4,160 USDC en master wallet sin verificar. La cifra real al verificar es **$2,770.83 USDC** (sólo USDC), aunque el TOTAL del master sí da ~$4,158.63 al sumar SOL+USDC+USDT. Discrepancia: confundí "total master" con "USDC master". Cifra corregida y desglosada en este informe v2.

### ⚠ Balance pendiente · cuenta 402 de Chainstack

**Falta el balance de la cuenta 402 de Chainstack** en este informe. Las cifras de capital arriba (master + hot cyclic) NO incluyen los balances de esa cuenta. Pendiente de obtener y añadir en próxima revisión del informe. El TOTAL combinado mostrado ($4,363.08) debe entenderse como **parcial**.
- **LIVE expuesto**: $0 (validado por flag `LIQ_CYCLIC_EXECUTE_LIVE=false`)
- **Realized profit total LIVE**: $0.00
- **Realized trades LIVE total**: **0** (verificado: `journalctl -u liquidator_rs --since "7 days ago" | grep -ciE "send_bundle|bundle_id="` → 0)
- **Bundles enviados últimos 7 días**: **0** (mismo comando)
- **Panics últimos 7 días**: **0** (verificado mismo journalctl)

Cualquier número exacto de balance es comprobable directamente con:
```
curl -X POST https://solana-mainnet.core.chainstack.com/<KEY> \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"getTokenAccountsByOwner","params":["<wallet>",{"mint":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},{"encoding":"jsonParsed"}],"id":1}'
```

### Bot V4-Alpha en Newark (verificado SSH 2026-05-08 14:26 UTC)
- Service: `liquidator_rs.service` active running
- Binary path: `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs`
- PID **750904** · etime **20h32min** desde **2026-05-07 17:46:22 UTC**
- Memory: RSS **31,372 KB** (~31 MB) estable
- Panics 24h: **0**
- Panics 7d: **0** (verificado)
- Bundles sent 7d: **0** (verificado)
- Cycles SHADOW total en JSONL: **2,632,616** (verificado: `wc -l /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl`)

### Sidecar Polymarket en Dallas (verificable curl)
- `vq-poly-sidecar` (data loop) · `vq-poly-api` (HTTP server :8090) · ambos active
- Migrado HOY 13:00-14:15 UTC de FMP → FRED+BLS+forecasts (RCA por FMP HTTP 402 desde 7-aug-2025)
- Pipeline funcional: BLS captura actuals · FRED captura release dates · forecasts.json manual cargado
- Estado: status=ok, errors=0, tracked events=4 (incluyendo CPI Mar 12)
- Verificable: `curl http://127.0.0.1:8090/api/state | jq .fmp`

### SHADOW production data
- Cycles SHADOW total en JSONL: 2,632,616 (verificable: `wc -l /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl`)
- Theoretical SHADOW PnL diario reportado por dashboard: cifras computed real desde JSONL pero **NO realizados** porque LIQ_CYCLIC_EXECUTE_LIVE=false
- Win rate SHADOW: ~100% (sesgo trivial: el bot solo loguea cycles donde detecta gap rentable, no contar fails de ejecución porque no hay ejecución)

---

## §5 · Eventos críticos de hoy 8 May 2026

### 12:30 UTC · NFP release Vie 8 (gate FAILED)
- **Causa raíz**: FMP API caída con HTTP 402 (Payment Required) desde Jue 7 ~22:00 UTC. FMP cambió pricing model 2025-08-31, endpoint `economic_calendar` se movió de free a paid tier.
- **Sello SF_reaccion_correcta**: FALSE (6 de 7 checks bloqueantes en FAIL por cascada del input ausente)
- **Decisión**: `pause_RCA` per cronograma firmado
- **Negligencia detectada**: Claude no chequeaba `fmp.status="stale"` en status sweeps. Memoria persistente añadida con regla obligatoria de chequear data-input dependencies en cada status sweep.

### 13:00-14:15 UTC · Migration emergency a gov APIs
- Decisión Marco firmada: **Opción E** (FRED + BLS + manual forecasts.json)
- Implementado en 75 minutos:
  - `bls_client.py` — BLS API actuals NFP/CPI/Unemployment ($0, gov)
  - `fred_calendar_client.py` — FRED release/dates endpoint ($0, gov)
  - `forecasts.json` — consensus forecasts manual curados de Investing.com
  - `fmp_compat.py` — drop-in replacement de FMPClient (1 line change en sidecar.py)
- **NFP actual retroactivo computado**: BLS reporta NFP April +115K (vs forecast 62K) → SF=0.24σ → mode NORMAL es correcto. El bug fue el provider, no la lógica.

### 14:30 UTC · Firma Gemma 4 31B sobre r150-bis-RCA
- **Veredicto**: NO APTO para escala de capital. Régimen Mar 12 = micro-capital ($5-10) si gate verde, NO escalable.
- **Requisito para LIVE EXECUTE**: implementar A (investing_client scraping automation) **O** B (validador rangos + linter JSON + doble firma SHA256). Sin esto, no hay LIVE.
- **Decisión Marco**: B para Mar 12 (implementable Sáb 9 morning) + A semana 13-19 May para automatización permanente.

### 14:45 UTC · Firma Gemma 4 31B sobre r150-tris (Q23-Q26 follow-ups)
- Forecasts.bak versionado físico con timestamp+hash
- Tokyo POC tier1+tier2+tier3 KPIs definidos
- BLS unresponsive fallback sequence 5 steps
- Escalado capital por hitos cuantitativos NO calendario (Fase 1 microcapital → Fase 4 scale)
- Auto-rollback si drawdown >25% / 3 panics / win rate <35% sostenido 7d

### ~15:00 UTC · Status final del día
- "GREEN FOR IMPLEMENTATION (B-Plan)" firmado por Gemma 4 31B
- 2 artefactos entregados internamente: `restore_last_valid.sh` + `POC_TOKYO_TEMPLATE.json`
- Pendientes Sáb 9 morning: validator, sign_forecasts, integración SF→mode, Tokyo POC

---

## §6 · Plan operativo Vie 8 → Mar 12 May

### Sáb 9 May
- 09:00-12:00 UTC · `forecasts_validator.py` (10 metric ranges + 5 quality gates) + `sign_forecasts.py` (SHA256 + interactive confirm) + integración con fmp_compat
- 13:00-15:00 UTC · Conectar SF compute → mode transition NORMAL/CAUTELA en sidecar.py + tests backfill
- 15:00-18:00 UTC · Tokyo POC: provisión VPS spot AWS Tokyo, capturar 5 KPIs Tier1 + 5 edge cases Tier2

### Dom 10 May
- Morning · `r150-bis_sanity.md` (sanity check haircuts empíricos pre-LIVE)
- Afternoon · Continuar Tokyo POC samples
- Evening · Marco re-verifica CPI consensus en Investing.com/Bloomberg/CNBC. Si cambió → update forecasts.json + double-sign nuevo hash

### Lun 11 May
- Morning · Pre-CPI final verification (todo el stack)
- Evening · Smoke tests + Marco autoriza listo para gate

### Mar 12 May (gate day)
- 12:00 UTC · Pre-flight check automático
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

## §7 · Riesgos honestos (sin pintar)

### Técnicos
- **Forecasts.json manual**: regresión vs spec r90 deterministic-data. Mitigación parcial con validator+linter+doble firma. Riesgo residual: typo o consensus dinámico cambia entre Dom 10 y Mar 12 sin re-verify.
- **BLS API latency**: gov gratis pero 30-60s de lag vs feeds comerciales. Suficiente para microcapital. Para escala futura, Bloomberg Terminal (~$24K/año) es la única opción industria-grade.
- **Solana network congestión**: variable independiente fuera de control. CB protege bien.
- **Edge real desconocido**: SHADOW dice gaps pero ese número incluye NO ejecución. Haircut SHADOW→LIVE real: NULL hasta tener N≥20 trades realizados Mar 12+.

### Operacionales
- **Arquitectura LOCKED hasta CPI Mar 12 13:00 UTC**. Cualquier sugerencia técnica fuera del manual de operaciones requiere nuevo ciclo de firmas.
- **Negligencia operativa cazada hoy** (no chequeo data-input dependencies en status sweeps): regla persistente.
- **Inconsistencia nomenclatura de mi parte**: usé "Gemma 4 cloud" durante semanas — incorrecto, todo es local A100. Memoria persistente actualizada para no repetir.
- **Inventión sostenida sobre identidad de modelo**: hace 3 días yo afirmé que la API local llamaba a Gemini 2.5 — esa afirmación fue invención sin verificar. Verificación hoy: es Gemma 4 31B Apache 2.0. Memoria persistente añadida con regla "verificar modelo via API antes de afirmar identidad".

### De estimación
- **Cronograma Mar 12 ajustado**: 4 días para implementar B-Plan + Tokyo POC + sanity haircuts + pre-CPI. Buffer adecuado para microcapital, no permite overruns.
- **investing_client.py debug semana 13-19**: 2-3 días dev estimados pero scraping puede tener edge cases imprevisible.

---

## §8 · Lo que NO sabemos (humildad)

- Haircut real SHADOW→LIVE de NUESTRO bot: 0 data points hasta Mar 12+.
- Edge real diario en cyclic arb Solana para nuestro stack actual: NULL hasta N≥20 trades LIVE.
- Capacity del wallet a tamaño $200 vs $5K vs $50K: no medido.
- Edge degradación post-Lun 12 LIVE: depende de cuántos searchers compiten en mismo gap.
- Resultados Tokyo POC: pendientes de capturar Sáb 9.

---

## §9 · Lo solicitado a Codex

Marco pide audit técnico estricto pero no destructivo. Específicamente:

1. **Validación arquitectónica**: ¿el approach FRED+BLS+forecasts es sólido o hay ciegos no detectados?
2. **Validación del StressPass 12-checks**: ¿son threshold razonables o demasiado laxos/estrictos?
3. **Validación cronograma Mar 12**: ¿es viable B-Plan + microcapital LIVE en 4 días o estamos forzándolo?
4. **Validación regla escalado cuantitativo Q26**: ¿las 4 fases con hitos numéricos son industry-standard o hemos inventado?
5. **Riesgos no detectados**: ¿qué nos falta ver?

Marco quiere honestidad técnica completa. Sin pintar de bonito ni catastrofizar. Si hay problemas serios, decirlos. Si todo OK, decirlo. Sin proyección de revenue ni multiplicadores fictionales.

---

## §10 · Material disponible para que Codex profundice

Todos los archivos relevantes en filesystem cuandeoro Dallas (acceso vía SSH si necesario):

- `/home/administrator/poly_sidecar/` — sidecar Python (FastAPI + data loop)
- `/home/administrator/r1*.md` — 83 specs MDs firmados
- `/home/administrator/.claude/projects/-home-administrator/memory/` — memoria persistente con feedback rules
- `/srv/v4_deploy/pre_deploy_check.sh` — checklist 13 checks que ya pasó GREEN
- Newark via SSH `ubuntu@64.130.34.38` — bot V4 actual
- Dashboard público `https://inicio.velocityquant.io/poly/pnl/dashboard.html` (basic auth)
- Workspace toxicflow `https://toxicflow.velocityquant.io/` (público, placeholder)

Sin secretos. Cero info propietaria intencionalmente ocultada.

Comandos clave para verificación de cifras (si Codex tiene acceso SSH a Dallas o quiere validarlas):
```
# Bot uptime/health
ssh ubuntu@64.130.34.38 'systemctl status liquidator_rs'
ssh ubuntu@64.130.34.38 'curl -s http://127.0.0.1:9091/cb/status'

# Cycles total
ssh ubuntu@64.130.34.38 'wc -l /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl'

# Trades LIVE realizados (debe ser 0)
ssh ubuntu@64.130.34.38 'sudo journalctl -u liquidator_rs --since "7 days ago" | grep -ciE "send_bundle|bundle_id="'

# Modelo local Gemma 4 31B
curl http://localhost:11434/api/tags

# Sidecar status
curl http://127.0.0.1:8090/api/state | jq '.fmp,.mode,.tau_final'

# Capital wallets (Solana RPC)
curl -X POST <RPC> -d '{"jsonrpc":"2.0","method":"getTokenAccountsByOwner",...}'
```

---

**Status final**: V4-Alpha SHADOW estable · GREEN FOR IMPLEMENTATION B-Plan Sáb 9 · Capital LIVE $0 · primer LIVE microcapital $5-10 condicional StressPass_Mar12=True · Mar 12 13:30 UTC.

**Próximo r-number**: r150-bis_sanity (Dom 10) · POC_TOKYO_2026-05-09.json (Sáb 9 evening) · r154 post-CPI (Mar 12 14:00 UTC).
