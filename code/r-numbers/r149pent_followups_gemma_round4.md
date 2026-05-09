# r149-pent · Round 4 follow-ups Gemma · 4 preguntas + código entregable

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 · ~19:45 UTC
**Asunto**: Respuestas Q14-Q17 + 2 archivos Python entregables
**Status**: implementación parcial completada, listo para review

---

## Q14 — F3 classifier · Python para |corr|<0.2 vs BTC returns

**Implementado**. Archivo entregado:

📁 [/srv/toxicflow/filters/btc_correlation_test.py](/srv/toxicflow/filters/btc_correlation_test.py)

### Diseño técnico

```python
# Computa Pearson + Spearman para cada feature vs BTC 30d return
# Aplica gate: max(|pearson|, |spearman|) < threshold (default 0.2)
# Output: JSON con accepted/rejected/errored
```

### Uso esperado en F4 backtest

```bash
python3 /srv/toxicflow/filters/btc_correlation_test.py \
    --features-csv /srv/toxicflow/db/wallet_features_sample.csv \
    --btc-prices-csv /srv/toxicflow/db/btc_daily_close.csv \
    --threshold 0.2 \
    --out /srv/toxicflow/db/feature_corr_report.json
```

### Por qué Pearson + Spearman, no solo Pearson

- Pearson captura correlación lineal
- Spearman captura correlación rank (monotónica no necesariamente lineal)
- Si una feature es no-lineal vs BTC return (ej. solo correlated en bull markets), Spearman lo detecta donde Pearson falla
- Gate aplicado al `max(abs(pearson), abs(spearman))` — ambas deben pasar

### Output esperado

```json
{
  "threshold": 0.2,
  "n_features_tested": 11,
  "n_accepted": 9,
  "n_rejected": 2,
  "correlations": {
    "timestamp_entropy": {"pearson": 0.04, "spearman": -0.02, "max_abs_corr": 0.04, "n": 1873},
    "size_cv": {"pearson": -0.13, "spearman": -0.18, "max_abs_corr": 0.18, "n": 1873},
    "win_loss_asymmetry": {"pearson": 0.31, "spearman": 0.28, "max_abs_corr": 0.31, "n": 1873}
  },
  "gate_result": {
    "accepted": ["timestamp_entropy", "size_cv", "rtc", ...],
    "rejected": ["win_loss_asymmetry"],
    "errored": []
  }
}
```

(Datos hipotéticos — los reales se computarán en F4 backtest sobre la DB poblada).

### Integración en F3 classifier training

```python
# En F4_train_classifier.py
import json
gate_report = json.load(open('/srv/toxicflow/db/feature_corr_report.json'))
features_to_use = gate_report['gate_result']['accepted']

X_train = wallet_metrics[features_to_use]  # solo features que pasan gate
# ... fit Random Forest ...
```

---

## Q15 — Tokio POC marginal · métricas adicionales para break the tie

Si el POC del Sáb 9 cae en `verdict = marginal` (RTT advantage entre 50% y 80%), capturar Phase 1.5 antes de decidir:

### Métricas tie-breaker

| Métrica | Cómo capturarla | Por qué importa para tie-break |
|---|---|---|
| **Bundle simulate latency real** | Setup wallet keypair Solana + Jito client, enviar bundle dummy con simulate=true | Si simulate latency es <50ms desde Tokio vs >150ms desde Newark, va Tokio |
| **Slot subscription update lag** | WebSocket subscribe slotNotification, medir delta entre slot N publicado y received en cliente | Tokio tiene Jito Tokyo más cerca; Newark tiene Jito NYC. Si Tokyo gana >100ms aquí, vale provisión |
| **Jito tip floor freshness** | GET tip_floor cada 30s durante 4h, medir staleness | Si Tokio recibe updates más frescos, su block engine es más prioritario |
| **Bundle inclusion rate (real)** | Enviar 100 bundles dummy con tip mínimo, medir % incluidos | Métrica definitiva: si Tokio incluye 30%+ más, gana |
| **Time-of-day spread** | Capturar 4 ventanas (00, 06, 12, 18 UTC) con N=200 cada una | Si Tokio gana solo en una ventana (e.g. Asian session), considerar dual-server hybrid |
| **Yellowstone Asia endpoint** | Chainstack / Triton tiene endpoints Tokyo; medir latency vs current | Yellowstone en Tokio podría compensar sin necesidad de Jito |

### Decision tree extendido para "marginal"

```
IF marginal:
    Phase 1.5 capture additional metrics (~6h work):
        bundle_simulate_latency_delta = newark_simulate - tokyo_simulate
        slot_subscription_delta = newark_slot_lag - tokyo_slot_lag
        bundle_inclusion_rate_delta = tokyo_inclusion - newark_inclusion
    
    IF bundle_inclusion_rate_delta > 0.20 (Tokio incluye 20%+ más bundles):
        VERDICT = "go_tokyo"
    ELIF slot_subscription_delta > 100ms:
        VERDICT = "go_tokyo"
    ELIF time_of_day shows Tokio wins only in Asian session AND we have V4 Asian flow:
        VERDICT = "hybrid_dual_server"  // Newark + Tokyo small for Asia hours
    ELSE:
        VERDICT = "stay_dallas_for_F5"  // No justifica overhead operativo aún
```

### Coste de Phase 1.5

VPS spot adicional 6h ~$1. Wallet Solana funded con 0.01 SOL (~$1.50). Total <$5 para resolver el tie-break.

---

## Q16 — NFP gate · thresholds exactos del SF para `pause_RCA`

Threshold cuantitativos basados en magnitud del SF y respuesta del sistema. **Cualquier condición que falle = pause_RCA**.

### Tabla de decisión SF · NFP gate

| Magnitud `|SF_used|` real | Mode esperado del sidecar | Si mode actual ≠ esperado | Decisión |
|---|---|---|---|
| < 0.5σ | NORMAL (no reaction) | Si activó CAUTELA falsamente | **pause_RCA** (false positive grave) |
| 0.5σ - 1.0σ | NORMAL | tolerancia ±10% | proceed_CPI |
| 1.0σ - 2.0σ | CAUTELA dentro 30s | Si retrasa >60s | **pause_RCA** (latency unacceptable) |
| 1.0σ - 2.0σ | CAUTELA dentro 30s | Si NO activó CAUTELA | **pause_RCA** (false negative crítico) |
| 2.0σ - 4.0σ | CAUTELA + DESARMADO si activado | Si solo CAUTELA pero |SF|>3σ | **pause_RCA** (reacción insuficiente) |
| > 4.0σ | DESARMADO inmediato (<10s) | Si no DESARMADO en 30s | **pause_RCA** (mode trigger fallido) |

### Condiciones complementarias bloqueantes

Independientes de la magnitud SF, cualquiera de estas → **pause_RCA**:

1. **`sigma_robust_FRED` no se cargó**: el SF no se puede computar correctamente
2. **`SF_used` retorna NaN o exception**: pipeline matemático roto
3. **Audit MD no se generó** dentro de T+10min post-release: `cpi_audit_format.py` falló
4. **CB tripped >60s sostenido** durante release window: bot ciego al evento
5. **Sidecar `status` ≠ ok** durante release window: degradado, no confiable
6. **FRED API errors >5** en window T-15min → T+15min: input data inestable

### Condiciones que NO son bloqueantes (proceed_CPI con notas)

| Observación | Acción |
|---|---|
| `would_send%` drop temporal por reacción del bot al spike | proceed (es comportamiento correcto, conservador) |
| `cb_blocked%` spike temporal durante release | proceed (CB protegiendo es ok, mientras retorne a baseline en <5min) |
| `slot_lag p99` jump por congestión Solana coincidente | proceed (no relacionado con SF) |
| `tau_final` divergencia respecto a τ_macro | proceed si `mode_reason` lo justifica |

### Output de la decisión Vie 8 13:00 UTC

Format compromiso:

```
DECISIÓN NFP GATE: <proceed_CPI | pause_RCA>

EVIDENCIA (3 frases):
  1. SF magnitude: |SF_used| = X.XXσ (clasificación: <NORMAL/CAUTELA/DESARMADO>)
  2. Mode transition: <correcto / retrasado / fallido> en T+Yseg
  3. Condiciones complementarias: <todas OK / falló X>

PRÓXIMO PASO:
  - SI proceed_CPI → r151 brief QuantumBot 14:00 UTC + Tokyo POC autorizado Sáb 9
  - SI pause_RCA → RCA window Sáb-Dom, decisión re-deploy CPI miércoles 14
```

### Edge case: SF dentro de range pero sistema reaccionó incorrecto

Si `|SF_used| = 0.3σ` pero el sidecar entró en CAUTELA — eso es false positive. Bloqueante porque:
- Sidecar CAUTELA suprime trades reales en LIVE
- Si false-positivea durante CPI lunes, dejamos dinero en la mesa por nada
- RCA obligatorio: ¿`sigma_robust` mal calibrado? ¿threshold mal? ¿bug en mode logic?

Este es el caso menos visible pero igualmente crítico.

---

## Q17 — Python implementation PATHOLOGY_TAXONOMY_v1 ready for r151

**Implementado**. Archivo entregado:

📁 [/srv/quantum_ppo/pathology_taxonomy_v1.py](/srv/quantum_ppo/pathology_taxonomy_v1.py)

### Estructura del archivo

- 21 patologías totales: 17 negativas (L1-L4) + 4 positivas (L_POS)
- Dataclass `Pathology` con `name, level, delta, min_precision, description, detection`
- Cada `detection` es callable `(step, episode_log) → bool`
- API pública: `apply_taxonomy(step, log, enabled_tags)` → `{name: delta}`
- API pública: `reward_delta_for_step(step, log, enabled_tags)` → `float` (suma deltas)

### Detection helpers

Funciones auxiliares para parsing de episode log:
- `_seconds_since(step, ref_step)` — delta temporal
- `_last_closed_loss_step(log, before_idx)` — buscar último cierre con pérdida

### Distribución de deltas

| Level | Count | Sum delta range |
|---|---|---|
| L1 (psychological) | 5 | -2.5 |
| L2 (execution) | 4 | -1.0 |
| L3 (timing) | 4 | -0.8 |
| L4 (risk_mgmt) | 4 | -2.3 |
| L_POS (positive) | 4 | +1.0 |
| **TOTAL** | **21** | **-5.6 worst / +1.0 best per step** |

### Validación pipeline (codificado en min_precision por tag)

| Tag | min_precision required |
|---|---|
| `revenge_trade` | 70% |
| `martingale` | 75% |
| `over_leverage` | 75% |
| `concentration_risk` | 80% |
| `no_stop_loss` | 90% |
| `weekend_yolo` | 85% |
| ... |

Tags con menor confianza esperada (`signal_skip`, `chasing_pump`) tienen min_precision=60-65% porque son edge cases ambiguos.

### Ejemplo de uso en PPO env_v43 (post-r151)

```python
from pathology_taxonomy_v1 import reward_delta_for_step

class EnvV43(EnvV42):
    def step(self, action):
        obs, base_reward, done, info = super().step(action)
        
        # Apply pathology taxonomy reward shaping
        episode_log = self._build_episode_log()
        current_step = self._build_current_step(action, info)
        
        delta = reward_delta_for_step(
            current_step, episode_log, 
            enabled_tags=self.cfg.enabled_pathology_tags
        )
        
        return obs, base_reward + delta, done, info
```

### Integración con Gemma narrator

```python
# Gemma narrator extends — instead of just narrating, also tags
def gemma_narrator_with_tags(episode_log):
    fired_tags_per_step = []
    for i, step in enumerate(episode_log):
        log_so_far = episode_log[:i+1]
        fired = apply_taxonomy(step, log_so_far)
        fired_tags_per_step.append(fired)
    
    # Gemma genera narrativa basada en tags fired + raw log
    narrative_prompt = build_prompt(episode_log, fired_tags_per_step)
    return ollama_generate("gemma4:31b", narrative_prompt)
```

### Cross-validation con Claude

Para detectar drift de tags:
- Cada 30 episodios, sample 5 episodios random
- Pasar por taxonomy de Claude (mismo código, modelo distinto)
- Si discrepancia >15% en tag firing → alerta de drift
- Si Gemma se desvía >25% del consenso humano → re-prompt con ejemplos correctores

---

## §0 · Resumen de la cadena de firmas

Cinco briefs entregados hoy:
- r149 (post-deploy summary)
- r149-bis (Q1-Q5 follow-ups)
- r149-tris (Q6-Q9 follow-ups)
- r149-quad (Q10-Q13 follow-ups + checklist Vie-Dom)
- r149-pent (Q14-Q17 follow-ups + 2 archivos Python entregables) ← este

Total: **17 preguntas resueltas**, **2 archivos código entregables**, **1 checklist consolidado de 4 días**.

**Recomendación honesta**: las próximas preguntas que surjan deberían diferirse al post-NFP (Vie 8 14:00+) o post-CPI (Lun 12 14:00+) para no expandir la cadena de hoy. El sistema está blindado en lo arquitectónico; lo que queda es ejecución mañana.

---

**Spec firmadas previas**: r93 + r107-r148e + r150 + r152 + r153 (estructura)
**Status**: V4-ALPHA SHADOW LIVE EN NEWARK · all GREEN · cadena de firmas saturada
**Próximo r-number**: r151 (Vie 8 14:00 UTC post-NFP gate decision)
**Capital**: $0 LIVE expuesto · $200 USDC SHADOW intacto

📁 Archivos entregables hoy:
- [r149_post_deploy_v4_shadow.md](r149_post_deploy_v4_shadow.md)
- [r149bis_followups_gemma.md](r149bis_followups_gemma.md)
- [r149tris_followups_gemma_round2.md](r149tris_followups_gemma_round2.md)
- [r149quad_followups_gemma_round3.md](r149quad_followups_gemma_round3.md)
- [r149pent_followups_gemma_round4.md](r149pent_followups_gemma_round4.md)
- [/srv/toxicflow/filters/btc_correlation_test.py](/srv/toxicflow/filters/btc_correlation_test.py)
- [/srv/quantum_ppo/pathology_taxonomy_v1.py](/srv/quantum_ppo/pathology_taxonomy_v1.py)
