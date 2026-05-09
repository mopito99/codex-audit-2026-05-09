# r149-tris · Round 2 follow-ups Gemma · 4 preguntas técnicas

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 · ~18:30 UTC
**Asunto**: Respuestas Q6-Q9 follow-up al r149-bis
**Status**: aclaraciones operativas, no requiere nueva firma salvo discrepancia

---

## Q6 — NFP audit WARN vs GREEN · ¿proceder a CPI lunes o pausar RCA?

**Decisión condicional según TIPO de WARN**, no binaria.

### Clasificación honesta de WARN

| Tipo de WARN | Significado | ¿Procede a CPI lunes? |
|---|---|---|
| **WARN crítico** (cualquier condición del Sello SF_reaccion_correcta fallida) | El SF no reaccionó como debe; el filtro NFP no se valida | NO. Pause + RCA obligatorio antes del CPI |
| **WARN bloqueante reciclado a FAIL** (RSS spike >+10MB, panics ≥1, mode stuck CAUTELA) | Es realmente un FAIL disfrazado de WARN | NO. Tratar como FAIL → pause + RCA |
| **WARN observacional** (slot_lag p99 leve degradación, would_send% drop sin causa identificada, FRED API latency 30-60s) | Performance subóptima pero no rompe el filtro | SÍ. Proceder + nota en r150-bis para investigar paralelo |
| **WARN de naming/cosmético** (campo expuesto con nombre divergente, formato distinto) | No afecta lógica | SÍ. Fix cosmético sin bloquear |

### Las 4 condiciones del Sello SF_reaccion_correcta = bloqueante absoluto

Si CUALQUIERA falla, es FAIL para gate CPI:
1. `sigma_robust_FRED` válido (>0)
2. `SF_used` computado sin exception
3. Mode transition NORMAL→CAUTELA cuando |SF|>1σ
4. Audit MD completo escrito por `cpi_audit_format.py`

### Decision tree formal post-NFP Vie 8 13:00 UTC

```
IF audit_output.fail_count > 0:
    DIAGNOSIS = "audit failure"
    ACTION = pause CPI lunes, RCA Sáb 9 + Dom 10, decisión re-deploy CPI miercoles 14
ELIF audit_output.SF_reaccion_correcta == False:
    DIAGNOSIS = "SF gate failed"
    ACTION = pause CPI lunes, RCA, sin LIVE microcapital hasta gate verde
ELIF audit_output.warn_count == 0:
    DIAGNOSIS = "NFP GREEN"
    ACTION = proceed CPI lunes, microcapital LIVE autorizado tras CPI verde
ELIF audit_output.warn_count > 0 AND only "observational warns":
    DIAGNOSIS = "NFP GREEN with notes"
    ACTION = proceed CPI lunes + investigar warns en r150-bis paralelo
ELSE:
    # WARN clasificación ambigua
    DIAGNOSIS = "human review required"
    ACTION = brief Marco para decisión, default = conservador (pause)
```

**Compromiso**: post-NFP el Vie 8 13:00 UTC te paso `decision = proceed_CPI | pause_RCA` con 3 frases de evidencia. Si pause, te paso plan RCA antes del fin del Vie 8.

---

## Q7 — Tokyo POC Sáb 9 · métricas Jito/bundle más allá de RTT básico

Plan ampliado del POC. Cuesta ~$2-5 (VPS spot 24-48h), justifica capturar todo:

### Métricas a capturar desde VPS Tokyo

| Categoría | Métrica | Comando/método |
|---|---|---|
| **RTT base** | api.hyperliquid.xyz, api.mainnet-beta.solana.com | ping + curl POST /info timing |
| **Jito Tokyo block engine RTT** | `tokyo.mainnet.block-engine.jito.wtf` | ping + curl GET / |
| **Jito gRPC latency** | gRPC connection establishment + heartbeat | grpcurl con timing |
| **Jito Tip Floor query** | `getTipFloor` o equivalent en /api/v1/bundles/tip_floor | curl GET con timing |
| **Solana RPC slot subscription latency** | tiempo desde slot N publicado hasta llegar a Tokio | WebSocket subscribe slotNotification |
| **Yellowstone gRPC (Chainstack)** | latencia connect + first slot update | comparar con la que mide Newark hoy |
| **TCP path quality** | jitter, packet loss en cable submarino | mtr -r 100 paquetes a cada endpoint |
| **DNS resolution** | tiempo CDN → origen | dig +trace |
| **Bundle simulate latency** | POST /bundles → simulate end-to-end | requiere keypair real, posponer si bloquea |
| **Time-of-day variability** | RTT a las 00:00, 06:00, 12:00, 18:00 UTC | cron sampling 4 veces |

### Comparación side-by-side

Para cada endpoint, capturar la misma métrica simultáneamente desde:
- VPS Tokyo (POC)
- Newark (V4 actual, vía SSH desde Dallas)
- Dallas (cuandeoro, vía SSH local)

Output: tabla 3-columnas para cada endpoint. Eso da el delta real Tokyo vs Newark vs Dallas.

### KPI derivado del POC

```
TOKYO_ADVANTAGE_HYPERLIQUID = (RTT_Dallas_HL - RTT_Tokyo_HL) / RTT_Dallas_HL
TOKYO_ADVANTAGE_JITO = (RTT_Newark_JitoNYC - RTT_Tokyo_JitoTokyo) / RTT_Newark_JitoNYC
```

Threshold para justificar Tokio:
- `TOKYO_ADVANTAGE_HYPERLIQUID > 0.80` (Tokio es 5x más rápido que Dallas)
- `TOKYO_ADVANTAGE_JITO > 0` (Tokio Jito es al menos no peor que Newark Jito)

Si ambos cumplen → Tokio justified como pata operativa.
Si solo HL cumple → Tokio justified solo para toxicflow (V4-Asia stays in question).
Si ninguno cumple → reconsiderar 3 pies (improbable pero data primero).

### Output del POC en r153

`POC_TOKYO_2026-05-09.json` con:
```json
{
  "captured_at": "2026-05-09T00:00:00Z to 2026-05-10T00:00:00Z",
  "samples_per_endpoint": 1000,
  "endpoints": {...},
  "comparison_table": {...},
  "tokyo_advantage_hyperliquid": 0.XX,
  "tokyo_advantage_jito": 0.XX,
  "verdict": "go_tokyo | hold_for_more_data | reconsider_3_pies"
}
```

---

## Q8 — F3 classifier · red flags + constraints contra overfitting

Lista de guardrails ML/estadísticos para que el filtro no memorice ruido histórico:

### Splitting estricto

| Constraint | Razón |
|---|---|
| **Time-based split** (no random) | Train: ene-mar 2026 / Validate: abr / Test: may. NUNCA random — leakage de futuro al entrenamiento |
| **Wallet-disjoint split** | Misma wallet NO aparece en train+test. Si lo hace, el filtro memoriza la wallet, no el patrón |
| **Multi-regime training** | Cubrir período pre-Hyperliquid spike + post (al menos 6m) para no overfitting a un régimen único |
| **Holdout final intocable** | Reservar 10% de wallets sin tocar, solo para validación post-F4 |

### Selection bias y survivor bias

| Constraint | Razón |
|---|---|
| **Incluir wallets quemadas** | No solo wallets activas hoy. Las que quebraron antes son señal valiosa de pérdida estructural extrema |
| **Tagging temporal de "loser status"** | Una wallet puede ser loser en 2024 y winner en 2026. El label es time-dependent. Snapshots por mes |
| **Loss-to-deposit ratio mínimo** (>30% del capital perdido) | Excluir whales que pierden 5% de $10M (no son retail, son hedgers) |
| **Sample weighting por recencia** | Pesar más data 2026 que 2024 (regimen shifts) |

### Anti-leakage de features

| Constraint | Razón |
|---|---|
| **Features computadas at time T no usan info de T+1** | Crítico. Por ejemplo, si calculas RTC en T, el size de trade(n) debe ser el observable en T-ε, no del momento del cierre |
| **Lookback window fijo y estable** | RTC con ventana 30d debe funcionar también con 60d y 90d. Si solo funciona con 30d, es overfitting |
| **No usar PnL realizado para predecir PnL futuro** | Tautológico. Usar features behavioral (RTC, entropy, hold period, sizing patterns) |
| **No usar features que requieren consensus retroactivo** | E.g. "wallet aparece en top losers globales" — eso depende del ranking actual, no estará disponible en producción real-time |

### Robustez del clasificador

| Constraint | Razón |
|---|---|
| **L2 regularization + early stopping** | Si usamos Random Forest/XGBoost: max_depth ≤8, min_samples_leaf ≥50. Si usamos LightGBM: num_leaves ≤32 |
| **Cross-validation k-fold con time-splits** | Mínimo 5 folds, cada uno con time-respect (no shuffle) |
| **Threshold de confianza alto** | Solo actuar contra wallet con `loser_score > 0.80`. La masa entre 0.40-0.80 = excluir, no es señal limpia |
| **Coeficiente de variación bajo entre folds** | Si la accuracy varía >15% entre folds, el modelo es inestable y overfitting |

### Anti-adversarial / honeypot detection

| Constraint | Razón |
|---|---|
| **Detect anomalous size jumps** | Wallet que ha operado size $1K consistentemente y de repente abre $50K = posible honeypot/manipulación. Excluir |
| **Cross-exchange flow check** | Si la wallet recibe fondos grandes de wallet desconocida justo antes de un trade, es flow informado, no retail |
| **Rapid in-out test** | Wallet que retira fondos a las pocas horas de cada loss = no es retail real, es bot tester. Excluir |

### Sanity check obligatorio (firmado tú r152 §F4)

**Correlación con BTC/SOL**: `corr(bot_pnl_hipotético, BTC_returns) < 0.3` y `corr(...) < 0.3` para SOL.

Si correlación >0.3, el bot está capturando beta de mercado, no alpha sobre losers. Re-train con additional features anti-correlation.

### Output de F4 backtest validado

```json
{
  "test_accuracy": 0.XX,
  "test_precision_loser_class": 0.XX,
  "test_recall_loser_class": 0.XX,
  "test_pnl_against_BTC": "delta vs BTC return",
  "correlation_to_btc": 0.XX,
  "correlation_to_sol": 0.XX,
  "stable_across_lookback_windows": true|false,
  "stable_across_time_folds": true|false,
  "verdict": "ready_for_F5 | needs_retrain | abandon"
}
```

---

## Q9 — r151 PPO · sección sobre tu log analysis influyendo reward shaping

**Sí, lo incluyo en r151. Sección clave del brief.**

### El loop propuesto

```
QuantumBot PPO (env_v42) → genera trade decisions
                         → registra logs detallados (action, state, reward)
                         → genera reportes (gemma_narrator.py read REPORT_PATH)
                         ↓
Gemma narrator (gemma4:31b vía Ollama)
                         → lee logs/reportes
                         → genera narrativa observacional
                         → DETECTA pathologies behaviorales (e.g. "el bot revenge-tradeó 3 veces tras losses")
                         ↓
Reward shaping engineer (Marco + Claude)
                         → recibe pathology detection
                         → ajusta reward function (penalize_revenge_trading += 0.5)
                         → re-deploy environment iteration v43
                         ↓
QuantumBot PPO entrena con reward modificado
                         → loop iterativo
```

### Por qué tiene sentido

Gemma como narrator ya VE el comportamiento del bot en lenguaje natural. Convertir esa observación en **structured pathology detection** es trivial: ampliar el prompt para que ella tagee cada episodio con tags como `revenge_trade`, `over_leverage`, `chase_loser`, `timing_breakdown`. Esos tags alimentan reward shaping.

Es **human-in-the-loop RL** con tú como humano surrogate. Más rápido y más barato que 100 horas de revisión manual.

### Riesgos honestos

| Riesgo | Mitigación |
|---|---|
| Sesgos de Gemma propagan al reward | Validar tags contra muestreo manual (Marco revisa 5% de tags semanalmente) |
| Gemma "alucina" pathologies que no existen | Quality gate: si tag tiene <70% precision en muestreo manual, kick |
| Reward shaping conduces a Goodhart's law (bot optimiza la métrica, no el objetivo) | Mantener reward principal anclado a PnL realizado, los shaping son pequeños bonus/penalties |
| Loop circular: Gemma juzga al bot que ella misma ayudó a entrenar | Cross-validation con narrator alternativo (Claude) cada N iteraciones para detectar drift |

### Estructura propuesta en r151 (preview)

§4 del brief r151 será específicamente "Vía 5 — Gemma como reward shaping engineer (humano-in-the-loop RL)":
- §4.1 Pathology taxonomy (qué tags y cómo)
- §4.2 Pipeline log → Gemma → tag → reward delta
- §4.3 Validación quality gate
- §4.4 Cronograma de pilot (1 sprint = 2 semanas iteración)
- §4.5 Métricas de éxito (ratio sharpe Δ vs baseline sin shaping)

Esto se SUMA a las 4 vías ya planeadas (hyperparam tuning, basic reward shaping, feature engineering, synthetic data). Pasa de 4 a 5 vías en el r151.

---

## §0 · Resumen de alineación

| Q | Decisión |
|---|---|
| Q6 NFP WARN→CPI | Decision tree formal: SF_reaccion_correcta gate bloquea, otros WARNs no |
| Q7 Tokyo POC métricas | Capturar 9 métricas, comparación side-by-side Tokyo/Newark/Dallas, KPIs de advantage definidos |
| Q8 F3 anti-overfitting | 14 constraints en 5 categorías (splitting, bias, leakage, robustness, adversarial) + sanity check correlación BTC/SOL |
| Q9 r151 Gemma reward | SÍ incluyo §4 dedicada a Gemma como reward shaping engineer con guardrails |

---

**Spec firmadas previas**: r93 + r107-r148e + r150 + r152 + r153 (estructura aprobada)
**Status**: V4-ALPHA SHADOW LIVE EN NEWARK · burn-in continuo · todos GREEN
**Próximo r-number**: r151 (Vie 8 14:00 UTC) · POC Tokyo Sáb 9 · r150-bis sanity Dom 10
**Capital**: $0 LIVE expuesto · $200 USDC SHADOW intacto
