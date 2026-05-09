# r148e · Respuestas 4 follow-ups pre-deploy Gemma

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 15:42 UTC · T-2h04min al deploy
**Asunto**: Respuestas Q1-Q4 follow-up post-r148d
**Status**: confirmación operativa, no requiere nueva firma de tu parte salvo si discrepas

---

## Q1 — Indicadores prioritarios post-deploy validation

**Ventana de observación**: T+0 → T+15min (17:46 → 18:01 UTC).

### Indicadores BLOQUEANTES (cualquiera FAIL → rollback inmediato)

| # | Indicador | Threshold OK | Threshold FAIL | Source |
|---|---|---|---|---|
| 1 | Boot log r144 Q1 marker | `effective_min_profit_usd=0.0` literal | string ausente o ≠ 0.0 | journalctl |
| 2 | Boot log Q4 backoff init | `polling_interval=60s` | en backoff (>60s) o crash | sidecar log |
| 3 | Process running | PID activo, etime > 30s | crash loop o exit 1 | systemd |
| 4 | Panics en T+0→T+10min | 0 | ≥1 | journalctl |
| 5 | RSS post-load | < 60 MB (era 31 al boot pre-deploy) | > 80 MB (= leak en código nuevo) | ps |
| 6 | CB endpoint :9091 alive | retorna JSON con TRIP=22, RESET=5 | timeout o 500 | curl |
| 7 | Yellowstone gRPC connected | "Yellowstone gRPC connected" en log | gap >30s sin updates | log |

### Indicadores QUALITATIVOS (degradación, no abort)

| # | Indicador | Esperado | Investigar si |
|---|---|---|---|
| 8 | `would_send%` rolling 5min | rebote a >40% | <30% sostenido 5min → ver Q4 |
| 9 | `cb_blocked%` rolling 5min | similar a pre-deploy (~0-5%) | >20% sostenido 5min |
| 10 | Sidecar `current_polling_interval_s` | == 60 | en backoff sin causa |
| 11 | `min_profit_usd_applied` en JSONL | == 0.0 (audit field Q1) | ≠ 0.0 |

**Mi orden de chequeo a T+5min**: 6 → 1 → 4 → 8 → 9 → 11. Los primeros 4 detectan rollbacks bloqueantes en <30s. Los últimos 3 detectan degradación.

---

## Q2 — Tiempo máximo permitido para quick fix

**Propuesta firme**: **5 minutos absolutos**.

Cronograma operativo:
```
17:41:00 UTC  Lanzo pre_deploy_check.sh
17:41:30 UTC  Resultado disponible (script tarda ~30s)
17:42:00 UTC  Si GREEN → procedo a las 17:46 UTC
              Si FAIL Check 8/13 → ABORT 24h, no quick fix
              Si FAIL Check 4/5/6/7/12 → arranco quick fix
17:42:00 → 17:46:00 UTC  Ventana quick fix (4 min reales útiles)
17:46:00 UTC  Hard cutoff:
              Si quick fix ya GREEN → deploy
              Si NO GREEN → ABORT 24h, comunico decisión
```

**Justificación de 5 min** (NO más):
- Los Check 4-7/12 son transient (process restart, sidecar resucitar, backup creation)
- Si en 5 min no se resuelven, el problema NO es transient
- Más tiempo significa intentar fixes en deploy window — riesgo de half-state
- Mejor postpone 24h limpio que deploy a medias

---

## Q3 — Helius API queries para Fase 1.5 Sanity Check (haircuts)

Plan ejecutable Vie 8 - Sáb 9 con 3 queries:

### Query 1 — Pull signatures de pool Orca SOL/USDC (últimas 1000)

```
POST https://mainnet.helius-rpc.com/?api-key=$HELIUS_KEY
Content-Type: application/json

{
  "jsonrpc": "2.0", "id": 1,
  "method": "getSignaturesForAddress",
  "params": [
    "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
    {"limit": 1000}
  ]
}
```

→ Devuelve array de `{signature, slot, blockTime, err}`.

### Query 2 — Para cada signature, full transaction detail

```
{
  "jsonrpc": "2.0", "id": N,
  "method": "getTransaction",
  "params": [
    "<signature>",
    {"encoding": "json", "maxSupportedTransactionVersion": 0}
  ]
}
```

→ Devuelve `meta.preTokenBalances`, `meta.postTokenBalances`, `meta.fee`, `transaction.message.instructions[]`, `transaction.message.accountKeys[]`.

### Query 3 — Filtro arb cyclic (heurística cliente, sin RPC adicional)

Cliente Python aplica criterios:
```python
def is_cyclic_arb(tx):
    # 1. Excluir TXs failed
    if tx['meta']['err']: return False
    # 2. Excluir Jupiter aggregator
    JUPITER_PROG = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    if JUPITER_PROG in tx['transaction']['message']['accountKeys']: return False
    # 3. Mismo wallet origen y destino USDC
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    pre  = [b for b in tx['meta']['preTokenBalances']  if b['mint'] == USDC_MINT]
    post = [b for b in tx['meta']['postTokenBalances'] if b['mint'] == USDC_MINT]
    # signer = índice 0 de accountKeys
    signer = tx['transaction']['message']['accountKeys'][0]
    pre_signer  = next((b for b in pre  if pre_account_owner(b) == signer), None)
    post_signer = next((b for b in post if post_account_owner(b) == signer), None)
    if not pre_signer or not post_signer: return False
    # 4. Net delta USDC > 0
    delta = post_signer['uiTokenAmount']['uiAmount'] - pre_signer['uiTokenAmount']['uiAmount']
    if delta <= 0: return False
    # 5. Al menos 2 DEX programs invocados (cyclic, no single-leg)
    DEX_PROGRAMS = {
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Orca
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
        "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",  # Meteora DLMM
    }
    invoked_dexes = set(tx['transaction']['message']['accountKeys']) & DEX_PROGRAMS
    if len(invoked_dexes) < 2: return False
    return True
```

### Query 4 — Per arb cyclic identificada, computar haircut

```python
def compute_haircut(tx):
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    realized = post_usdc - pre_usdc  # net delta on-chain (REAL)
    fee_lamports = tx['meta']['fee']
    # Detectar Jito tip (transfer 1lamports a accounts conocidas tip-receiver)
    jito_tip = detect_jito_tip(tx)  # heurística sobre instructions[]
    total_paid = fee_lamports + jito_tip
    # Theoretical gross = realized + lo que pagó al validator + tip
    # Esto asume que sin pagar nada, hubiera ganado más
    theoretical_gross_usd = realized + (total_paid / 1e9) * sol_price_usd_at_block
    haircut_pct = 100 * realized / theoretical_gross_usd
    return haircut_pct, realized, theoretical_gross_usd
```

### Output esperado de Fase 1.5 (Dom 10)

```json
{
  "window": "last 7 days",
  "n_pool_signatures": ?,
  "n_arbs_identified": ?,
  "%_arbs_of_total": ?,
  "median_haircut_pct": ?,
  "p25_haircut": ?,
  "p75_haircut": ?,
  "spurious_passes": [],   // sanity check de filter
  "false_negatives_detected": []
}
```

→ Si median_haircut está en rango 30-70%, el filter está bien calibrado y escalamos a Fase 2.

---

## Q4 — `would_send%` drop post-restart: ¿market cooling vs binary regression?

**Decision tree (15 min ventana post-deploy)**:

### Step 1 — Cuantificar el drop

```
ws_pre_15min  = avg would_send% últimos 15min PRE-deploy
ws_post_5min  = avg would_send% T+0 → T+5min post-deploy
delta_ws_pct  = (ws_post - ws_pre) / ws_pre × 100
```

Si `delta_ws_pct > -20%`: no hay drop significativo, ambos casos descartados.

### Step 2 — Si `delta_ws_pct < -20%`, diferenciar:

| Indicador | Market cooling | Binary regression |
|---|---|---|
| `cb_blocked%` post vs pre | ≈ igual (delta < +5pt) | ↑ ≥ +20pt |
| `slot_lag p95` post vs pre | ≈ igual | igual o ↑ |
| `slot_lag p99` post vs pre | igual o ↓ | igual o ↓ |
| `mean profit/cycle` (would_send subset) | ↓ (mercado quieto, profits chicos) | ↓ (errors en quote) |
| Panics en T+0→T+5min | 0 | ≥1 |
| RSS spike T+0→T+5min | 0 ± 2 MB | ≥ +10 MB |
| `min_profit_usd_applied` (audit Q1) | == 0.0 | ≠ 0.0 (= bug en Q1 implementation) |
| `current_polling_interval_s` sidecar | == 60 | == 60 (no diagnostic) |
| Yellowstone slot updates rate | igual a pre | gap >30s o decrease |

### Step 3 — Decisiones

```
IF panics > 0 OR RSS_spike > 10MB OR min_profit_usd_applied != 0.0:
    DIAGNOSIS = "binary regression"
    ACTION = "rollback al backup pre-Q1, ABORT 24h, RCA"

ELSE IF cb_blocked +20pt AND slot_lag stats igual AND panics 0:
    DIAGNOSIS = "binary regression sutil — algo en la lógica del nuevo Q1 hace que CB block más"
    ACTION = "rollback pre-Q1, NO abort 24h pero re-evaluar Q1"

ELSE IF cb_blocked similar AND mean_profit_per_cycle bajó AND slot_lag igual:
    DIAGNOSIS = "market cooling"
    ACTION = "esperar 30 min, NO rollback. Si en 30min sigue degradado y no recupera, escalar a CAUTELA"

ELSE IF slot_lag p99 ↑ y cb_blocked ↑:
    DIAGNOSIS = "network Solana congestion (no nuestro)"
    ACTION = "monitor 30min, capacity normal"
```

### Comunicación con Marco a T+5min

Si entro en cualquier branch ≠ "PROCEED green" → te paso a Marco un MD de 100 palabras:
```
DIAGNOSIS: <market cooling | binary regression | network>
EVIDENCE: 4 KPIs con valores
RECOMMENDATION: <wait 30min | rollback now | abort 24h>
```

Tú firmas o ajustas en <5min.

---

## §0 · Sin nuevas firmas requeridas

Estas son respuestas a tus follow-ups, no abren temas nuevos. Si discrepas en algún umbral o decision tree, dímelo antes de las 17:46 UTC. Si silencio, asumo aceptado y procedo según lo descrito.

---

**Spec firmadas previas**: r93 + r107-r148d + r150
**Status**: READY FOR DEPLOY · 4 follow-ups respondidos
**Próximo r-number**: r149 con post-deploy 18:00 UTC + diagnóstico Q4 si aplica
**Capital**: $0 LIVE expuesto · $200 USDC SHADOW intacto
