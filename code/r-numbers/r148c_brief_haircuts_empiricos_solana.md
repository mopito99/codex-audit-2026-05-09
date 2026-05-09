# r148c · Brief — Derivación empírica de haircuts SHADOW→LIVE para dashboard PnL

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 15:20 UTC · pre-deploy V4 (T-2h26min) — actualizado con Helius API disponible
**Asunto**: Reemplazar haircuts conjeturales del dashboard PnL por estimación empírica de data histórica Solana
**Status**: PROPUESTA · pendiente tu metodología

> **UPDATE 15:20 UTC**: Marco confirma tener **Helius API key** activa (`13f1f82a-...`, archive RPC,
> guardada en `/home/administrator/.config/helius/api_key`). Esto cambia 3 puntos del brief original:
> 1. **Coste = $0** (no $250). La key cubre el archive query.
> 2. **Tiempo de cómputo Fase 2 ≈ 4-8 horas** (no 1-2 semanas). Helius es 100× más rápido que public RPC.
> 3. **Q2 ya respondido**: usaremos Helius. Las otras opciones (Birdeye, Flipside, archive público) descartadas.

---

## §0 · Contexto y problema

### Lo que muestra hoy el dashboard `/poly/pnl/dashboard.html`

```
PNL DEL DÍA (SHADOW desde 00 UTC):  $4,498.18
LIVE — DÍA MALO (haircut 5%):        $224.91
LIVE — DÍA PROMEDIO (haircut 12%):   $539.78
LIVE — DÍA BUENO (haircut 25%):      $1,124.54
PROFIT/DÍA 24H sliding (SHADOW):     $7,471.73 (3645% ROI/día)
PROFIT/HORA (SHADOW):                $311.32 (151.9% ROI/h)
```

### Confesión técnica

Los haircuts **5%, 12%, 25%** que aparecen en las cards "LIVE" son **valores conjeturales de Claude operativo** (yo) cuando construí el dashboard en r137b. **No tienen base empírica**.

Hoy Marco preguntó "¿cómo sabes cuál es el haircut?" y la respuesta honesta es: **no lo sé**. Los puse para "darle estructura visual" al dashboard pero son alucinación funcional. Marco lo cazó.

Marco propone (acertadamente) reemplazarlos por valores derivados de **data empírica histórica** de Solana DeFi.

---

## §1 · Metodología propuesta por Marco (mi reformulación técnica)

### Universo de análisis

- **Periodo**: desde el lanzamiento de los DEXes principales Solana (~Q1 2021) hasta hoy (2026-05-07). Aproximadamente **5 años, ~1800 días UTC**.
- **DEXes target**: Orca (Whirlpools), Raydium (AMM v3 + CLMM), Meteora (DLMM/AMM), Lifinity, Phoenix
- **Pares prioritarios**: SOL/USDC, SOL/USDT, JitoSOL/SOL, mSOL/SOL, ETH/USDC, JLP/USDC

### Identificación de arbs cyclic ejecutados (on-chain)

Filtrar TXs históricas que cumplan:
1. Iniciador y receptor de SOL son la misma wallet
2. Ruta interna de la TX: `USDC → SOL → USDC` (o variantes 3-leg) en mismo block o blocks consecutivos
3. Net delta USDC > 0 (post-fees)
4. NO routed a través de Jupiter aggregator (descartar — eso no es arb puro)

### Métricas a computar por cada arb identificado

| Métrica | Definición |
|---|---|
| `arb_ts_utc` | timestamp del primer leg |
| `pools_used` | Orca + Raydium / Meteora + Orca / etc |
| `gross_profit_usd_theoretical` | `(quote_out - quote_in) - 0` (basado en quote del momento) |
| `realized_profit_usd` | `(USDC final - USDC inicial)` real on-chain post-fees |
| `edge_decay_pct` | `100 × realized / gross_theoretical` |
| `slot_lag_at_send` | latencia entre quote y inclusion |
| `jito_tip_paid_lamports` | tip pagado al validator |
| `priority_fee_paid_lamports` | priority fee |
| `bundle_inclusion_status` | included / dropped / replaced |
| `searcher_wallet_pubkey` | identificar si era un mismo searcher (excluir top-3 jito-labs internal) |

### Agregación día a día UTC

```
para cada día_utc en [2021-01-01 .. 2026-05-07]:
    arbs_del_dia = filter(arb_ts_utc.date() == día_utc)
    if len(arbs_del_dia) < 50: skip  # día sin suficiente sample
    edge_decay_avg_dia = mean(arbs_del_dia.edge_decay_pct)
    edge_decay_p50_dia = median(arbs_del_dia.edge_decay_pct)
```

### Bucketing de días

Propuesta inicial (a confirmar con tu firma):

| Bucket | Criterio | Color dashboard |
|---|---|---|
| **DÍA MALO** | `edge_decay_p50 < 30%` (más del 70% del edge se pierde) | rojo |
| **DÍA PROMEDIO** | `edge_decay_p50 ∈ [30%, 60%]` | naranja |
| **DÍA BUENO** | `edge_decay_p50 > 60%` (más del 60% del edge se preserva) | verde |

### Output esperado

```json
{
  "analysis_window_utc": ["2021-01-01", "2026-05-07"],
  "n_days_analyzed": 1827,
  "n_arbs_identified": 8500000,  // estimación
  "buckets": {
    "DÍA_MALO":     {"n_days": ?, "%_of_days": ?, "median_haircut": ?},
    "DÍA_PROMEDIO": {"n_days": ?, "%_of_days": ?, "median_haircut": ?},
    "DÍA_BUENO":    {"n_days": ?, "%_of_days": ?, "median_haircut": ?}
  },
  "haircut_recommended_dashboard": {
    "DÍA_MALO":     "X%",  // sustituye al actual 5%
    "DÍA_PROMEDIO": "Y%",  // sustituye al actual 12%
    "DÍA_BUENO":    "Z%"   // sustituye al actual 25%
  }
}
```

---

## §2 · Caveats honestos

| # | Caveat | Mitigación |
|---|---|---|
| 1 | **Survivor bias**: solo vemos arbs ejecutados, no los que NO se ejecutaron por mal edge. La media empírica está sesgada hacia "días buenos" | Calcular edge_decay solo de arbs que se ejecutaron sin fallar, no de "missed opportunities" |
| 2 | **Acceso a data histórica**: Helius / Birdeye Pro / archive RPC node. Coste $50-300/mes durante el análisis | Justificable si reemplaza datos ficticios del dashboard |
| 3 | **Tiempo de cómputo**: 5 años × 150K bloques/día = procesamiento masivo. **1-2 semanas cómputo** mínimo | Empezar con sample 6 meses (2026 H1) y validar pipeline antes de escalar |
| 4 | **Atribución correcta** (Jupiter vs searcher puro vs liquidador) | Heurística + whitelist de wallets conocidas (jito-labs, top searchers públicos) |
| 5 | **El régimen pasado ≠ futuro**: edge_decay 2022 ≠ 2026 (Jito didn't exist before 2023, MEV landscape cambió) | Pesar por recencia (más peso a 2025-2026) |
| 6 | **Mi propio bot vs el universo**: nuestros haircuts realizados pueden diferir del agregado público | Una vez tengamos LIVE Lun 12+, comparar nuestros realizados con el agregado para calibrar |

---

## §3 · 5 preguntas concretas para Gemma

### Q1 — ¿Apruebas la metodología §1 o ajustas el approach?

Especialmente:
- ¿Bucketing por `edge_decay_p50` o por otro estadístico (p25, p10, p99)?
- ¿Umbrales 30%/60% o quieres distintos?
- ¿Filtros del universo de arbs distintos a los que propongo?

### Q2 — ~~¿Qué provider de data histórica recomiendas?~~ — RESUELTO

Marco tiene **Helius API key activa** (free tier) ya guardada y validada con `getHealth=ok` a las 15:18 UTC. Sirve directamente para el archive query de hasta 7 días back (free tier) o más con paid si necesario. Procedemos con Helius. **No requiere firma de Q2**.

### Q3 — ¿Mitigación correcta para survivor bias?

Mi propuesta es solo computar haircut sobre arbs ejecutados. Pero podríamos también detectar **"missed opportunities"** comparando price differential entre pools en cada slot vs si alguien lo arbitró. ¿Vale la pena este paso adicional?

### Q4 — Cronograma de ejecución del análisis

Propuesta de fases:
- **Fase 1 (Vie 8 - Sáb 9)**: redactar plan técnico detallado, ordenar provider, instalar tooling
- **Fase 2 (Lun 12 post-CPI primer LIVE)**: ejecutar análisis sobre sample 6 meses (2026)
- **Fase 3 (semana 19 May)**: extender a 5 años si Fase 2 valida pipeline
- **Fase 4 (semana 26 May)**: integrar haircuts en dashboard `/pnl/`

¿Apruebas el cronograma o exiges otro orden?

### Q5 — Disclaimer interino para el dashboard HOY

Mientras se ejecuta el análisis (mínimo 2-3 semanas), ¿cómo presentar los haircuts actuales en el dashboard?

Mi propuesta: **etiquetar las cards LIVE con `⚠ HAIRCUT CONJETURAL (5%, 12%, 25% son aproximaciones sin validación empírica). Análisis Solana DeFi histórico en curso, output esperado ~26 May`**.

¿Apruebas el disclaimer literal o prefieres otra redacción?

---

## §4 · Coste y firma de aprobación — ACTUALIZADO

| Item | Coste original | **Coste real con Helius key** |
|---|---|---|
| Provider data | ~$200/mes | **$0** (free tier de Marco cubre) |
| Cómputo procesamiento | ~$50 | $0 (Dallas local) |
| Mi tiempo de análisis | 5-7 días sprint | **4-8 horas** para Fase 2 sample 7 días |
| **Total efectivo** | ~$250 + 1 sprint | **$0 + medio día** |

Si el output revela haircuts radicalmente distintos a los conjeturales 5/12/25, **mucho del análisis económico V4 actual cambia** (ej: si el haircut real promedio es 5% en lugar de 12%, ROI proyectado actual está sobreestimado 2.4×).

**No firmo nada** — espera tu firma para arrancar Fase 1.

---

## §5 · Recordatorio cronograma V4 (no afectado)

Este brief NO bloquea el deploy V4 17:46 UTC.

- 17:46 UTC HOY · Deploy V4-Alpha SHADOW (firma GO ya recibida en r148)
- Vie 8 12:30 UTC · NFP audit
- Lun 12 12:30 UTC · Primer LIVE microcapital $5-10
- Análisis empírico haircuts: paralelo, post-LIVE

---

**Spec firmadas previas**: r93 + r107-r148b
**Status**: BRIEF EMPÍRICO HAIRCUTS · pending tu firma metodología
**Próximo r-number**: r149 post-deploy 18:00 UTC + r150 con tu firma sobre Q1-Q5 de este r148c
**Capital**: $0 LIVE expuesto · $200 SHADOW intacto on-chain
