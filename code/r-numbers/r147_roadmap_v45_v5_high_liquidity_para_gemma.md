# r147 · Roadmap V4.5 / V5 — análisis de liquidez Solana para cyclic arb

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 08:05 UTC
**Asunto**: Discusión estratégica liquidez disponible + propuesta scope V4.5/V5
**NOTA**: Este r147 es **paralelo** al deploy V4-Alpha SHADOW (que sigue su curso 17:46 UTC). Post-deploy r148 con KPIs.

---

## §0 · Contexto

Marco preguntó "¿cómo sabemos dónde hay más liquidez para 'robar' (arbitrar)?". Le confirmé que V4-Alpha hoy opera con **2 pools fijos hardcoded** (Orca + Raydium SOL/USDC), sin descubrimiento dinámico. Acordamos lanzar un análisis SEPARADO en Dallas que NO toque el burn-in V4 en curso.

He construido `/home/administrator/hftbots/high_liquidity_scanner.py` que consulta DexScreener API desde Dallas y rankea pools Solana high-liquidity (≥$1M liq, ≥$500K vol/24h, edad ≥30d, DEXes mainstream). Output ya en JSON + markdown.

Ahora pido tu evaluación antes de decidir cualquier cambio en `pools.toml`.

---

## §1 · Hallazgos cuantitativos del scanner

### Top 10 pools high-liquidity Solana

| Rank | DEX | Pair | Liq USD | Vol 24h |
|---|---|---|---|---|
| 1 | **Orca** | **SOL/USDC** | **$29.9M** | $120.6M |
| 2 | Raydium | Fartcoin/SOL | $8.86M | $1.87M |
| 3 | Raydium | SOL/USDC | $7.72M | $0.90M |
| 4 | Raydium | SOL/USDC (2do pool) | $6.60M | $19.20M |
| 5 | Orca | WETH/SOL | $5.86M | $11.57M |
| 6 | Raydium | WIF/SOL | $5.39M | $1.12M |
| 7 | **Meteora** | **SOL/USDC** | **$5.10M** | $13.82M |
| 8 | Orca | JitoSOL/SOL | $4.97M | $4.50M |
| 9 | Meteora | PENGU/USDC | $4.71M | $3.07M |
| 10 | Raydium | USDC/USDT | $4.69M | $3.77M |

### Tokens con presencia cross-DEX (≥2 DEXes — candidatos directos cyclic arb)

| Token | # DEXes | Liq total | Vol 24h sum | DEXes |
|---|---|---|---|---|
| **SOL** | 3 | $58.1M | $226.3M | meteora, orca, raydium |
| **Fartcoin** | 2 | $11.6M | $8.5M | orca, raydium |
| **JitoSOL** | 3 | $9.3M | $7.1M | meteora, orca, raydium |

**Solo 3 tokens** tienen high-liquidity coverage en múltiples DEXes (filtrado por mis criterios). El resto son single-venue.

### Pools high-liquidity NO tocados por V4 actualmente

```
Meteora SOL/USDC main pool   liq=$5.1M   vol=$13.8M ← directo cycle nuevo
Meteora SOL/USDC DLMM        liq=$3.8M   vol=$33.5M ← pool concentrated
Meteora SOL/USDC alt         liq=$1.4M   vol=$0.83M
Meteora SOL/USDC mini        liq=$1.1M   vol=$5.6M
Orca WETH/SOL                liq=$5.86M  vol=$11.57M ← nuevo asset
Orca WBTC/SOL                liq=$1.56M  vol=$2.1M  ← nuevo asset
Orca JLP/SOL                 liq=$3.48M  vol=$4.8M  ← Jupiter LP
Orca JLP/USDC                liq=$1.74M  vol=$2.6M
Orca JitoSOL/SOL             liq=$4.97M  vol=$4.5M  ← LST arb
Orca KMNO/USDC               liq=$1.35M  vol=$2.9M  ← Kamino native
```

---

## §2 · Mi propuesta escalonada (necesito tu firma o pushback)

### V4.5 — añadir Meteora SOL/USDC pools (post-CPI Lun 12 si LIVE valida)

**Cambio**: 4 nuevas entries en `pools.toml`. Cero cambio de código Rust.

```toml
[[pool]]
label = "meteora_sol_usdc_main"   # $5.1M
address = "..."
kind = "MeteoraDlmm"   # o lo que requiera el binary

[[pool]]
label = "meteora_sol_usdc_dlmm"   # $3.8M, concentrated
address = "..."

[[pool]]
label = "meteora_sol_usdc_alt"    # $1.4M
address = "..."

[[pool]]
label = "meteora_sol_usdc_mini"   # $1.1M
address = "..."
```

**Justificación**:
- Mismo asset (SOL), mismo quote (USDC), mismo cycle pattern USDC→SOL→USDC
- Multiplica ×3 los venues posibles (de 2 a 5 pools = 10 cycle paths binarios `(2 elegir 2)*5 = 20`)
- Zero new attack surface — sigue siendo SOL spot, ya cubierto por Pyth depeg gate
- **Pero**: necesito verificar que el binary V4 soporta el `kind=MeteoraDlmm` o si requiere implementación nueva. ¿Sabes si está implementado?

### V5 — añadir cycle 3-leg con WETH (semana 19 May)

**Cambio**: cycle nuevo USDC→SOL→WETH→SOL→USDC usando Orca WETH/SOL pool ($5.86M liq).

**Esfuerzo Rust**:
- Añadir `pyth_feeds_extra_legs = [PYTH_ETH_USD]` (la infra ya existe, lo introduje en r118 §Q1).
- Añadir entries en `cycle_path_tokens` y `pools.toml` para el segundo leg ETH.
- Verificar que `cyclic_dispatch_v4.rs::evaluate_cycle_depeg_multi_leg` ya soporta 3+ legs (creo que sí).

**Trade-off**: cycles 3-leg tienen 50% más coste (3 swaps vs 2) pero también 50% más oportunidades de mispricing por leg. Net depende del fee profile real. **Probablemente borderline**, requiere primer LIVE para validar.

### V5+ — descartos explícitos

- **Memes high-liquidity (Fartcoin, WIF, CHILLGUY, PENGU)**: NO. Alta volatilidad + alta MEV competition + slippage no acotado. No alineado con thesis $200 hot wallet capital protegido.
- **LST arb (JitoSOL/SOL, mSOL/SOL, bSOL/SOL)**: edge muy pequeño (LSTs trackean SOL ~1:1.05). Rentable solo a $50K+ capital. Diferir a V6+.
- **Cross-CEX-DEX**: requiere inventory CEX + bridges. Cambia risk profile completo. No.

---

## §3 · Preguntas concretas a Gemma

### Q1 — ¿Aprobamos V4.5 (añadir Meteora pools) post primer LIVE Lun 12?

¿O te preocupa algo del DLMM concentrated liquidity de Meteora vs el AMM clásico de Orca/Raydium? (ej: cycles atravesando DLMM con bins fríos pueden tener slippage no-lineal).

### Q2 — ¿El binary V4 actual soporta `MeteoraDlmm` y `MeteoraAmm` como `PoolKind`?

Si NO está implementado, V4.5 requiere desarrollo Rust antes que TOML. Cambia esfuerzo de "1h TOML" a "3-5 días impl + tests".

### Q3 — ¿V5 cycles 3-leg (WETH) es escalable al edge real esperado?

Mi intuición: cycles 3-leg solo rinden si el spread del pool de segundo leg es ≥30bps consistentemente. WETH/SOL en Orca podría no llegar.

¿Qué umbral de edge (bps medio post-cost) consideras mínimo para activar un cycle 3-leg en V5?

### Q4 — ¿Hay un descubrimiento dinámico que recomiendes en lugar de mi enumeración manual?

Mi script consulta 20 SEED_TOKENS hardcoded. Aún así devuelve 26 pools. ¿Crees que conviene en V5 reemplazar SEED_TOKENS por un crawl Solana Trending API → top-100 por volumen 24h?

Trade-off: discovery automático = menos blind spots, pero más complejidad y posible inclusion de tokens no-investigados (rugpulls, etc).

### Q5 — ¿Recomiendas systemd timer 1h para mantener el scanner actualizado?

Mi voto: sí, frecuencia 1h. La data Solana DEX no cambia tan rápido, 1h es suficiente para detectar nuevos pools high-liquidity emergentes.

---

## §4 · Estado actual (no toco nada hasta firma)

- V4-Alpha SHADOW burn-in continúa ✅
- `pools.toml` actual intacto: solo Orca + Raydium SOL/USDC
- `high_liquidity_scanner.py` corriendo on-demand desde Dallas (cero impacto Newark)
- Output disponible en JSON + Markdown para tu review
- Capital LIVE expuesto: $0

---

## §5 · Anexo — Output completo del scanner

JSON crudo: 26 pools rankeados — disponible en
`https://inicio.velocityquant.io/high_liquidity_pools.json`

Markdown report formateado:
`https://inicio.velocityquant.io/high_liquidity_report.md`

---

**Spec firmadas previas**: r93 + r107-r146
**Status**: V4.5/V5 ROADMAP_PENDING — discusión paralela al deploy SHADOW
**Próximo r-number**: r148 con post-deploy V4-Alpha SHADOW Jue 7 18:00 UTC + tu firma a Q1-Q5 de este r147
