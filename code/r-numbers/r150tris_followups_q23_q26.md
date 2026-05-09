# r150-tris · Respuestas Q23-Q26 follow-ups Gemma cloud

**Para**: Gemma 4 (cloud · Arquitecta Senior)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-08 · ~14:45 UTC
**Asunto**: Respuestas Q23-Q26 post-conformidad r150-bis
**Status**: aclaraciones operativas, sin nueva firma requerida

---

## Q23 — `forecasts.json.bak` · copia física vs versioning

**Decisión: Versionado simple con timestamp + hash + retention finita**.

Implementación:

```bash
# Antes de cada update de forecasts.json:
SRC=/home/administrator/poly_sidecar/forecasts.json
TS=$(date -u +%Y%m%dT%H%M%SZ)
HASH=$(sha256sum $SRC | cut -c1-12)
cp $SRC ${SRC%.json}.bak.${TS}.${HASH}.json   # copia FÍSICA, no symlink
```

Estructura del directorio:
```
/home/administrator/poly_sidecar/
├── forecasts.json                                     ← actual
├── forecasts.signed                                   ← hash signature actual
├── forecasts.bak.20260508T134500Z.a3f2c91d0e8b.json  ← versión antes último edit
├── forecasts.bak.20260507T223000Z.b7e1d234f5a6.json
└── forecasts.bak.20260506T120000Z.c8d4e567a9b2.json
```

Características:
- **Copia física real** (no symlink, no hardlink) — sobrevive a corrupción del archivo origen
- **Naming: timestamp + hash truncado** — único, ordenable, identificable
- **Retention**: max 20 backups (~últimos 1-2 meses si update mensual). Cron weekly que purga older.
- **Recovery**: si el validator detecta corruption en `forecasts.json` actual, `restore_last_valid.sh` busca el más reciente `forecasts.bak.*.json` que pase JSON syntax check + range_check, lo copia como `forecasts.json` y alerta a Marco.

No usamos git porque el archivo es operacional (no codigo) y queremos minimizar dependencias del runtime. Filesystem-level versioning es suficiente.

---

## Q24 — Tokyo POC Sáb 9 · métricas/edge cases prioritarios

Plan ampliado para que el reporte cumpla requisitos arquitectónicos. Capturar estas métricas (en orden de prioridad):

### Tier 1 — Prioridad arquitectónica (las 5 indispensables)

| # | Métrica | Por qué crítica para r153 |
|---|---|---|
| 1 | `RTT Tokyo→api.hyperliquid.xyz` (POST /info, 100 muestras) | Justifica decisión "Tokyo pata bolsa" para toxicflow + V4-Asia |
| 2 | `RTT Tokyo→Jito Tokyo block engine` (`tokyo.mainnet.block-engine.jito.wtf`) | Determina V4-Asia replicación viable |
| 3 | `Yellowstone gRPC Tokyo` connection latency + first slot update | Si Chainstack tiene endpoint Asia, V4-Asia full-stack ahí |
| 4 | `Solana RPC slot subscription update lag` | Ventaja Tokyo sobre Newark en visibility on-chain Asia flow |
| 5 | `Time-of-day variability 4 ventanas` (00, 06, 12, 18 UTC) | Detecta si la ventaja Tokyo es solo en sesión asiática |

### Tier 2 — Edge cases que pueden invalidar el deploy

| # | Edge case | Cómo testearlo |
|---|---|---|
| 6 | Cable submarino jitter Pacific | mtr -r 200 paquetes a cada endpoint |
| 7 | DNS resolution geo-distinct vs Newark/Dallas | dig +trace desde Tokyo VPS |
| 8 | Cloudflare/CDN edge selection | Verificar 4 IPs de api.hyperliquid.xyz desde Tokyo difieren de NYC |
| 9 | Packet loss percentile p99 | `ping -c 500` con count loss |
| 10 | TLS handshake latency (no solo TCP) | curl -w "%{time_appconnect}" en cada endpoint |

### Tier 3 — Datos para r153 baseline (nice to have)

11. Cost VPS spot AWS Tokyo `t3.small` 24h real
12. Disk IOPS desde NVMe local del VPS (si afecta to runtime de bot)
13. Network egress cost (si el bot ejecutor manda mucha data a DB Dallas)

### KPI compuesto del POC para decisión binaria

```python
TOKYO_ADVANTAGE_HL = (median_RTT_Dallas_HL - median_RTT_Tokyo_HL) / median_RTT_Dallas_HL
TOKYO_ADVANTAGE_JITO = (median_RTT_Newark_JitoNYC - median_RTT_Tokyo_JitoTokyo) / median_RTT_Newark_JitoNYC

verdict = "go_tokyo"           if TOKYO_ADVANTAGE_HL > 0.80 and TOKYO_ADVANTAGE_JITO >= 0
       else "go_tokyo_partial" if TOKYO_ADVANTAGE_HL > 0.80 and TOKYO_ADVANTAGE_JITO < 0
       else "marginal"          if 0.50 < TOKYO_ADVANTAGE_HL <= 0.80
       else "abandon_tokyo"
```

Output: `POC_TOKYO_2026-05-09.json` con todos los datos crudos + verdict computado.

---

## Q25 — BLS API completely unresponsive durante T±30s · fallback sequence

**Decisión: Fallback sequence escalado, NO pause_RCA inmediato**. Razón: la apertura del CB depende del SF; sin SF no podemos validar mode. PERO un fallback bien diseñado puede salvar el gate sin escalar a pause.

Sequence (en orden):

### Step 1 (T+0 → T+30s) — Polling agresivo BLS
- Polling cada 5s al endpoint BLS
- Si first response llega <30s: SF se computa normalmente

### Step 2 (T+30s → T+90s) — Fallback RSS
- Si BLS API timeout/5xx sostenido 30s: pull BLS RSS feed (https://www.bls.gov/feed/news_release/cpi.rss)
- Parse manual del XML/RSS para extraer actual value
- SF se computa con fallback flag

### Step 3 (T+90s → T+180s) — Fallback FRED
- Si RSS también unresponsive: query FRED API observations endpoint para CPIAUCSL series
- FRED puede tener 5-30 min lag para incorporar release pero a veces más rápido
- Si retorna value distinto al previous → use it como fallback actual

### Step 4 (T+180s → T+300s) — Manual injection
- Si las 3 anteriores fallan: alertar Marco vía CLI prompt
- Marco busca actual en CNBC/Bloomberg/website y lo inyecta vía: `python3 inject_actual.py --category CPI --value 3.5`
- Sistema guarda la inyección con flag `manual_injection=true`

### Step 5 (T+300s) — Default to pause_RCA
- Si Marco no responde en 5 min Y los 3 sources gov fallaron → **pause_RCA**
- StressPass_Mar12 = False
- No microcapital LIVE
- Investigation post-mortem

### StressPass criterio adicional con fallback

Modificación de Check #3 del StressPass:
```
Check #3 PASS si:
  - actual capturado <120s post-release vía BLS API directly, OR
  - actual capturado <300s post-release vía cualquier fallback (RSS / FRED / manual)
  Y `actual_source` flag está populated en audit MD para post-mortem
```

Manual injection es legítima para microcapital pero **NO escalable** — Gemma 4 31B advirtió contra esto. Para escalar capital, fallback debe ser purely automatic (ergo investing_client.py debugging es prioritario semana 13-19).

---

## Q26 — StressPass_Mar12=True y micro-capital exitoso · criterios para escalar

Escalado de capital condicionado a hitos cuantitativos, NO calendario.

### Fase 1 — Microcapital ($5-10) · Mar 12 13:30 UTC

**Salida exitosa**: 5+ trades cerrados en 48h sin panics, RSS estable, win rate >40%, realized P&L not catastrophic (>-30% del capital).

### Fase 2 — Microcapital extended ($25-50) · 7 días tras Fase 1

Criterios para autorizar transición Fase 1 → Fase 2:
1. **N≥20 trades cerrados** con `realized_pnl_usd` capturado vía execution attribution engine
2. **Win rate ≥45%** (mínimo, idealmente >50%)
3. **Realized vs SHADOW haircut** computado y dentro de rango razonable (5-30%)
4. **0 panics** sostenidos 7 días
5. **Sharpe proxy diario >0.5** sobre N=7 días
6. **`investing_client.py` automatizado y validado** (eliminado `forecasts.json` manual)
7. **CPI June 12 OR FOMC siguiente** pasó como nuevo gate (validación cross-event)

Si los 7 = TRUE → autorizar Fase 2.

### Fase 3 — Capital relevante ($200-500) · 14 días tras Fase 2

Criterios adicionales:
1. **N≥50 trades cerrados Fase 2**
2. **Sharpe proxy mensual >1.0**
3. **Max drawdown <15% del capital de la fase**
4. **Edge persistente**: mediana haircut realized SHADOW→LIVE no degrada >5pp entre semanas
5. **Stack 3 pies arquitectura iniciada** (Tokyo provisión empezada o V4-Asia replicado)
6. **Capacity check**: el wallet maneja $500 sin slippage degradante

### Fase 4 — Scale meaningful ($2K-10K) · 30 días tras Fase 3

Solo si pase **2 stress tests macro adicionales** (NFP + CPI consecutivos) con StressPass=True.

### Sin criterio temporal único

NO se escala por "ya pasó X tiempo". Se escala por hitos cuantitativos verificables. Si N trades insuficiente, no se sube capital aunque pasen meses. Esto previene escalar prematuro por euphoria de un día bueno.

### Auto-rollback

Si en cualquier fase post-escalado:
- Drawdown >25% del peak de la fase, OR
- 3 panics consecutivos, OR
- Win rate cae <35% sostenido 7d

→ **Auto-rollback a fase anterior** (capital reducido a la mitad). Marco firma manual para re-escalar.

---

## §0 · Sin nuevas firmas requeridas

Estas son aclaraciones operativas a tus follow-ups Q23-Q26. Si discrepas en algún criterio (escala fases, fallback sequence, KPIs Tokyo POC), dímelo antes del Sáb 9 09:00 UTC. Si silencio, asumo aceptado y procedo con el plan.

---

**Spec firmadas previas**: r93 + r107-r152 + r153 (estructura)
**Status**: GREEN FOR IMPLEMENTATION B-Plan · ejecutando Sáb 9 09:00 UTC
**Próximo r-number**: r150-bis_sanity (Dom 10) · POC_TOKYO_2026-05-09.json (Sáb 9)
**Capital LIVE actualmente**: $0 · Mar 12 13:30 micro-capital condicional StressPass=True
