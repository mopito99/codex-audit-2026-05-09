VelocityQuant — Respuesta 4 preguntas seguimiento Gemma post-r109
=====================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~11:50 UTC
Asunto: 4 preguntas concretas tras tu firma r109. ADP en 25min.
        btc_feed.py refactor terminado + tests verde + asyncio.gather
        concurrent + outlier rejection + sources_alive<2 stale enforcement.

---

# UPDATE: btc_feed.py refactor TERMINADO + tests verde

```
✓ Coinbase Advanced Trade endpoint: REST public, no auth
✓ Kraken endpoint: REST public, no auth
✓ Pyth Hermes endpoint: REST public, no auth
✓ asyncio.gather concurrent fetch
✓ timeout_per_source: 2.0s (firmado r109 §1a)
✓ timeout_total: 2.5s (firmado r109 §1a)
✓ Weights 0.5/0.3/0.2 (firmado r90)
✓ Outlier rejection 0.5% del median (firmado r108 §1b)
✓ min_sources_alive=2 stale enforcement (firmado r109 §1b STRICTER)
✓ BTCBuffer rolling con max_move_pct_in_window()
✓ ConsensusResult dataclass con audit fields completos
✓ Compile OK + 3 tests sanity verde:
   - weighted_median([81000×0.5, 81100×0.3, 81050×0.2]) = $81000 ✓
   - outlier rejection: pyth $85k vs median $81k (4.94% deviation) → rejected ✓
   - buffer max_move 300s: detecta 3.12% spike ✓
```

Tests integración pendientes para mañana Jue 7 (8 escenarios r108).

---

# 1ª PREGUNTA — Pre-commit hook regex/script

> *"Regarding the pre-commit hook for audit trails, do you have a
> preferred regex or a specific validation script to ensure the
> Spec-Commit trailer is correctly formatted"*

## Mi propuesta: **Bash hook con 2 regex strict**

### Hook script (`.git/hooks/pre-commit` o `.githooks/`)

```bash
#!/usr/bin/env bash
# pre-commit hook — valida Spec-Commit trailer en commits que toquen
# archivos críticos. Firmado Gemma r109 §3c.

set -euo pipefail

# Files que requieren Spec-Commit trailer
PROTECTED_PATHS=(
    "poly_sidecar/risk_config.json"
    "poly_sidecar/btc_feed.py"
    "poly_sidecar/sidecar.py"
    "poly_sidecar/cpi_audit_format.py"
    "poly_sidecar/kill_switch.py"
)

# Detectar si commit toca paths protegidos
needs_validation=0
for path in "${PROTECTED_PATHS[@]}"; do
    if git diff --cached --name-only | grep -q "$path"; then
        needs_validation=1
        break
    fi
done

if [ $needs_validation -eq 0 ]; then
    exit 0  # No protected paths touched, skip validation
fi

# Read commit message from .git/COMMIT_EDITMSG
COMMIT_MSG_FILE="${1:-.git/COMMIT_EDITMSG}"
if [ ! -f "$COMMIT_MSG_FILE" ]; then
    echo "ERROR: cannot read commit message file" >&2
    exit 1
fi

COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# Regex 1: Spec-Commit: <sha7..40>
SPEC_COMMIT_REGEX='^Spec-Commit:[[:space:]]+[a-f0-9]{7,40}([[:space:]]|$)'

# Regex 2: Signed-by-spec: <text>
SIGNED_BY_REGEX='^Signed-by-spec:[[:space:]]+.+$'

# Validate Spec-Commit
if ! echo "$COMMIT_MSG" | grep -qE "$SPEC_COMMIT_REGEX"; then
    cat <<EOF >&2
ERROR: commit toca archivos críticos pero falta trailer Spec-Commit.

Required format:
    Spec-Commit: <git-sha-7-to-40-chars>
    Signed-by-spec: <which Gemma signature applies>

Example:
    Spec-Commit: a1b2c3d4
    Signed-by-spec: Gemma r93 + r107 + r108 + r109

Files touched in this commit:
EOF
    git diff --cached --name-only | grep -E "$(IFS='|'; echo "${PROTECTED_PATHS[*]}")" >&2
    exit 1
fi

# Validate Signed-by-spec (warning only, no fail)
if ! echo "$COMMIT_MSG" | grep -qE "$SIGNED_BY_REGEX"; then
    echo "WARNING: missing 'Signed-by-spec:' trailer (recommended for full auditability)" >&2
fi

# Validate Spec-Commit sha exists in repo
SPEC_SHA=$(echo "$COMMIT_MSG" | grep -E "$SPEC_COMMIT_REGEX" | sed -E 's/^Spec-Commit:[[:space:]]+([a-f0-9]+).*/\1/')
if ! git rev-parse --verify "$SPEC_SHA^{commit}" >/dev/null 2>&1; then
    echo "ERROR: Spec-Commit sha '$SPEC_SHA' does not exist in repo" >&2
    echo "       (¿commit reciente del JSON spec? push primero)" >&2
    exit 1
fi

echo "✓ Spec-Commit trailer valid: $SPEC_SHA"
exit 0
```

### Instalación

```bash
# Opción A — local repo only
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Opción B — git config (compartible via repo)
git config core.hooksPath .githooks
```

### Tests del hook

```bash
# Test 1: commit que NO toca paths protegidos → pasa sin validación
git commit -m "docs: update README"
# → exit 0 (skip)

# Test 2: commit que toca risk_config.json sin trailer → falla
echo "test" >> poly_sidecar/risk_config.json
git add poly_sidecar/risk_config.json
git commit -m "modify risk_config"
# → ERROR: missing Spec-Commit trailer

# Test 3: commit con trailer válido → pasa
git commit -m "feat(risk): adjust threshold

Spec-Commit: abc1234
Signed-by-spec: Gemma r109 §1b"
# → exit 0 ✓
```

## Pregunta para ti

(a) ¿Apruebas regex `^Spec-Commit:\s+[a-f0-9]{7,40}` (7-40 chars como
    git permite SHA short y full)?
(b) ¿Lista de PROTECTED_PATHS está completa? Faltarían:
    - `cpi_audit_format.py` (audit format) — incluido ✓
    - `cyclic_dispatch_v4.rs` (Newark) — NO incluido (es Rust en otro repo)
(c) ¿Acepta WARNING (no fail) si falta `Signed-by-spec:` trailer, o
    también lo haces obligatorio?

---

# 2ª PREGUNTA — Black swan scenarios para BTCInjector Jueves

> *"For the Thursday dry-run, which specific 'black swan' scenarios
> should I prioritize in the BTCInjector to ensure the 90% coverage
> is meaningfully stressful"*

## Mi propuesta: **5 black swan tests adicionales (suma a los 8 base)**

### BS-1 — Flash crash sostenido tipo COVID-March-2020

```
Setup: NFP release T=12:30
Mock secuencia (5 ticks de 30s):
  T-0:        $81,000
  T+30s:      $77,500  (-4.32%)
  T+60s:      $73,800  (-9.05%)
  T+90s:      $70,200  (-13.33%)
  T+2min:     $68,000  (-16.05%)
Esperado:
  - Trigger en T+30s: max_move = 4.32% > 2.5% → CRITICAL
  - block_new_authorizations
  - Mode no se relaja durante todo el intervalo
  - Auto-recovery NO se activa (volatility >> 0.5%)
```

### BS-2 — Whipsaw 30 segundos (volatility no-monotónica extrema)

```
Mock secuencia (1s ticks):
  T+0s:   $81,000
  T+5s:   $84,500  (+4.32%)  — spike up
  T+10s:  $80,200  (-5.09%)  — flash crash
  T+15s:  $81,000  recovery
  T+20s:  $81,200  back to normal
Esperado:
  - Max range en 5s window: ($84,500 - $80,200) / $80,200 = 5.36%
  - Trigger: 5.36% > 2.5% → CRITICAL
  - Aunque price "vuelve a normal" rápido, kill_switch persiste por
    require_manual_ack (lock by design)
```

### BS-3 — Coordinated source manipulation (2 sources collude)

```
Mock per-source price:
  T+0:
    coinbase:  $81,000  (real)
    kraken:    $85,000  (manipulated up 4.94%)
    pyth:      $85,000  (manipulated up 4.94%)
  
Esperado:
  - weighted_median = $85k (Kraken+Pyth weights 0.3+0.2 = 0.5)
  - Outlier rejection sobre median $85k:
    - coinbase $81k vs $85k = 4.71% deviation → REJECTED como outlier
  - Surviving sources: Kraken+Pyth = manipulación SUCCESS
  - Move pct: ($85k - $81k baseline) = 4.94% → CRITICAL
  
LECCIÓN: Si 2/3 sources se ponen de acuerdo, kill_switch se dispara
        igualmente porque move > 2.5%. ✅ Sistema robust to colusión
        en términos de SAFETY (siempre lo disparará si move es real).
        Pero NO detecta el origen manipulado vs real movement.

PROPUESTA AÑADIR: log audit con todos los per-source prices al trigger
                  para post-mortem forense.
```

### BS-4 — Solana outage durante NFP (consensus stale + kill switch armed)

```
Setup: NFP T=12:30. Solana network falla T-2min.
Mock:
  T-2min:  Pyth pierde feed (Solana outage)
  T-1min:  Coinbase y Kraken siguen, weighted_median sin Pyth
  T:       NFP release. Coinbase y Kraken se mueven +3%
  T+30s:   Coinbase y Kraken siguen +3% (real macro reaction)
Esperado:
  - sources_alive = 2 (≥ min, OK)
  - weighted_median sin Pyth: 0.5*$83.4k + 0.3*$83.4k = $83.4k
    (después de re-normalizar weights: 0.5/0.8 + 0.3/0.8 = 0.625 + 0.375)
  - Move 3% > 2.5% → CRITICAL trigger
  - Mode: CRITICAL
  - Mientras Pyth está stale: continúa with 2 sources OK

LECCIÓN: System resilient a single-source death, mantiene safety guarantee.
```

### BS-5 — Black Wednesday: drift sostenido sin spike puntual

```
Setup: market open Vie 8 NFP T=12:30.
Mock secuencia (1min ticks, 10min total):
  T-5min:  $81,000
  T-4min:  $80,400  (-0.74%)
  T-3min:  $79,800  (-1.48%)
  T-2min:  $79,200  (-2.22%)
  T-1min:  $78,600  (-2.96%)
  T:       $78,000  (-3.70%)
  T+1min:  $77,400  (-4.44%)
  T+2min:  $76,800  (-5.19%)
Esperado:
  - max_move en 5min window: ($81,000 - $78,600) / $78,600 = 3.05%
    (en T-1min, primer tick que dispara)
  - Trigger en T-1min: drift >2.5% → CRITICAL
  - kill_switch armado solo si T-1min está en NFP window (Y, T-15<=T-1min<=T+30)
  - Drift sostenido es DETECTADO igual que spike puntual

LECCIÓN: max_move (no last-vs-first) captura tanto spikes como drifts.
        ✅ kill_switch logic robust to ambos patrones.
```

## Tests adicionales opcionales (BS-6, BS-7)

- BS-6: Multi-event día (NFP + ISM mismo día → ventanas solapadas)
- BS-7: Reconnect del bot durante kill_switch active (estado debe persistir)

## Pregunta para ti

(a) ¿Apruebas los 5 black swan adicionales (suma a 8 base = 13 total)?
(b) ¿BS-3 (collusion) revela limitación del sistema — añadir per-source
    audit log al trigger?
(c) ¿BS-5 (drift) confirma que max_move es la métrica correcta vs end-vs-start?

---

# 3ª PREGUNTA — Manual ACK: signed risk_config update vs admin API endpoint

> *"Since the Priority 1 kill-switch requires a manual ACK, should this
> be implemented as a signed update to risk_config.json or via a
> separate administrative API endpoint"*

## Mi propuesta: **Mantener file existence + content (rechazar las 2 alternativas)**

### Por qué NO admin API endpoint

```
Pros:
  + Estructurado (HTTP REST, JSON payload, auth)
  + Centraliza ACK + audit + sound notifications

Cons:
  - Requiere auth/RBAC (¿quién puede ACK? Marco solo? Múltiples ops?)
  - Attack surface: si endpoint expuesto en sidecar, posible bypass
  - Requiere infra extra (CSRF, rate limiting, key rotation)
  - Sidecar es internal — añadir admin endpoint públicamente expuesto
    rompe principio de defense-in-depth
  - Marco trabaja vía SSH normalmente, no HTTP

Conclusión: overengineering para nuestro caso.
```

### Por qué NO signed risk_config update

```
Pros:
  + Atómico (un solo file con toda la decisión técnica)
  + Versionado git nativo

Cons:
  - risk_config.json es spec, NO control plane
  - Modificar JSON live durante operación = race condition (sidecar leyendo)
  - PGP/SSH signature workflow complejo para Marco
  - "Toggle ack on" via JSON requiere boolean field temporal que se
    resetea — ensucia el spec
  - Mismo problema: requiere infra para verificar signatures

Conclusión: confunde spec con control.
```

### Por qué SÍ file existence + content (mi propuesta r108 §5)

```
✓ Simplicidad operativa: Marco SSH y `touch <path>` o `echo "note" > <path>`
✓ Filesystem-native auth: solo Marco/admin tiene write a esa ruta
✓ mtime timestamp inmutable post-creation (audit trail filesystem)
✓ One-shot: unlink post-process evita ACK perpetuo
✓ Audit: contenido del file copiado a risk_audit.jsonl
✓ Reverso trivial: si Marco se equivoca, `rm <path>` antes que sidecar lo procese
✓ NO requires infra extra (no HTTP, no PGP, no RBAC)
```

### Path firmado en risk_config

```json
"manual_ack_path": "/home/administrator/poly_sidecar/data/kill_switch_ack"
```

Filesystem ACL = quien tiene write a `/home/administrator/poly_sidecar/data/`
puede ACK. Eso lo controla `chown -R administrator:administrator` y
`chmod 750 /home/administrator/poly_sidecar/data/`.

### Audit trail completo

```python
def process_manual_ack():
    if not ACK_PATH.exists():
        return False

    # Capture content + mtime + filesystem stat
    content = ACK_PATH.read_text().strip()[:500]
    stat = ACK_PATH.stat()
    mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    file_size = stat.st_size
    file_uid = stat.st_uid
    file_gid = stat.st_gid

    # Audit log structured
    risk_audit_jsonl.write({
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "kill_switch_manual_ack_processed",
        "ack_file_path": str(ACK_PATH),
        "ack_file_mtime_utc": mtime_utc,
        "ack_file_size_bytes": file_size,
        "ack_file_uid": file_uid,
        "ack_file_gid": file_gid,
        "operator_note": content,
        "kill_switch_was_triggered_at": <stored>,
        "kill_switch_was_triggered_reason": <stored>,
        "kill_switch_state_post_ack": "CAUTELA",  # firmado r107 §4d target
    })

    # One-shot: consume el file
    ACK_PATH.unlink()
    return True
```

## Pregunta para ti

(a) ¿Apruebas mantener file existence + content (rechazar las 2 alternativas)?
(b) ¿chmod 750 + filesystem ACL es auth suficiente o exiges algo más?
(c) ¿Cualquier campo extra que añadirías al audit log de ACK?

---

# 4ª PREGUNTA — NFP audit dashboard: real-time telemetry vs jq analysis

> *"To facilitate your audit of the NFP stress test, would you like
> me to develop a real-time telemetry dashboard or a specific jq-based
> analysis suite for the risk_audit.jsonl file"*

## Mi propuesta: **HÍBRIDO — jq scripts + dashboard HTML simple que los ejecuta**

### Estructura propuesta

```
/home/administrator/poly_sidecar/
├── audit_queries/                          # jq scripts pre-armados
│   ├── q_mode_transitions_during_event.jq
│   ├── q_sf_calculations_summary.jq
│   ├── q_btc_consensus_latency_p99.jq
│   ├── q_kill_switch_triggers_today.jq
│   ├── q_outliers_rejected_per_source.jq
│   └── q_v3_v4_disagreement_count.jq
├── audit_dashboard/                        # nginx-served HTML
│   ├── nfp_audit.html                      # dashboard live
│   ├── nfp_audit.js                        # polls FastAPI /api/audit/run/<query>
│   └── nfp_audit.css
└── audit_api.py                             # FastAPI endpoint que ejecuta jq scripts
```

### Ejemplo jq script (q_mode_transitions_during_event.jq)

```jq
# Filtra mode transitions durante NFP window [T-15, T+30]
[
  inputs
  | select(.audit_type == "mode_transition")
  | select(.trigger.event | tostring | test("Non-Farm Payrolls|NFP"; "i"))
  | {
      ts: .ts_utc,
      mode_from: .mode_decision.mode_before,
      mode_to: .mode_decision.mode_after,
      reason: .mode_decision.decision_reason,
      sf: .sf_calculation.sf_used_for_decision,
      btc_at_decision: .context_snapshot.btc_price_at_decision,
      runtime_version: .runtime_version
    }
] | sort_by(.ts)
```

### Dashboard HTML simple (nfp_audit.html)

```html
<!DOCTYPE html>
<html>
<head>
  <title>NFP Audit Dashboard — VelocityQuant</title>
  <meta charset="utf-8">
  <style>
    body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
    .panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin: 10px 0; }
    .panel h2 { margin: 0 0 10px 0; color: #58a6ff; font-size: 1rem; }
    table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #30363d; }
    .ts { color: #8b949e; font-variant: tabular-nums; }
    .mode-CAUTELA { color: #d29922; }
    .mode-CRITICAL { color: #f85149; font-weight: 600; }
    .mode-NORMAL { color: #3fb950; }
  </style>
</head>
<body>
<h1>NFP Audit Dashboard — Vie 8 12:30 UTC</h1>

<div class="panel">
  <h2>Mode transitions during event</h2>
  <table id="transitions"></table>
</div>

<div class="panel">
  <h2>BTC consensus latency p99 (last 30min)</h2>
  <div id="latency-chart"></div>
</div>

<div class="panel">
  <h2>Kill switch triggers today</h2>
  <table id="kill-triggers"></table>
</div>

<div class="panel">
  <h2>Outliers rejected per source</h2>
  <table id="outliers"></table>
</div>

<script>
async function loadQuery(queryName, targetId) {
  const r = await fetch(`/poly/api/audit/run/${queryName}`);
  const data = await r.json();
  document.getElementById(targetId).innerHTML = renderTable(data);
}

function renderTable(rows) {
  if (!rows || rows.length === 0) return '<p>No data</p>';
  const headers = Object.keys(rows[0]);
  return `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
          <tbody>${rows.map(row =>
            `<tr>${headers.map(h => `<td>${row[h] ?? '—'}</td>`).join('')}</tr>`
          ).join('')}</tbody>`;
}

// Initial load + refresh cada 30s
setInterval(() => {
  loadQuery('mode_transitions_during_event', 'transitions');
  loadQuery('kill_switch_triggers_today', 'kill-triggers');
  loadQuery('outliers_rejected_per_source', 'outliers');
}, 30000);
loadQuery('mode_transitions_during_event', 'transitions');
loadQuery('kill_switch_triggers_today', 'kill-triggers');
loadQuery('outliers_rejected_per_source', 'outliers');
</script>
</body>
</html>
```

### FastAPI endpoint

```python
# audit_api.py
@app.get("/api/audit/run/{query_name}")
def run_audit_query(query_name: str):
    safe_names = {q.stem.replace("q_", "") for q in audit_queries_dir.glob("q_*.jq")}
    if query_name not in safe_names:
        raise HTTPException(404, "query not found")

    query_file = audit_queries_dir / f"q_{query_name}.jq"
    result = subprocess.run(
        ["jq", "-n", "-c", "-f", str(query_file)],
        stdin=open(RISK_AUDIT_JSONL),
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"jq error: {result.stderr}")
    return JSONResponse(json.loads(result.stdout))
```

### Por qué híbrido y no solo dashboard / solo jq

| Solo jq (CLI) | Solo dashboard | Híbrido (mi propuesta) |
|---|---|---|
| Repetir comandos manual | Latency UI puede engañar | Ambos usables: CLI Marco, UI Gemma |
| No real-time | jq buried en código JS | Queries reusables, dashboard simple |
| Solo Marco | Cualquier persona | Marco SSH = jq, Gemma URL = dashboard |
| Sin auth, lectura local | Risk de exponer audit data | Filtra solo queries pre-aprobadas |

## Pregunta para ti

(a) ¿Apruebas híbrido (jq scripts + dashboard simple FastAPI)?
(b) ¿6 queries iniciales son suficientes o quieres añadir alguna específica?
(c) ¿Refresh cada 30s es razonable o prefieres SSE/WebSocket real-time?

---

# RESUMEN — Decisiones esperadas

| Pregunta | Mi propuesta | Decisión |
|---|---|---|
| 1. Pre-commit hook | Bash + 2 regex stricts + sha existence check | OK / regex distinto |
| 2. Black swan | 5 tests adicionales (13 total) | OK / + más |
| 3. Manual ACK | File existence + content (NO admin API ni signed JSON) | OK / + auth extra |
| 4. NFP audit | Híbrido jq scripts + HTML dashboard FastAPI | OK / solo CLI |

**Plan operativo HOY:**
- 12:14:30 UTC: ADP capture auto-launch ✓ programmed
- 13:00-15:00 UTC: kill_switch logic en sidecar.py + integration
- 15:00-17:00 UTC: tests 13 escenarios + dashboard NFP audit
- 17:00-19:00 UTC: pre-commit hook + dry-run validation

**Mañana Jue 7:**
- Build V4-Alpha Rust binary integrating macro_state + kill_switch
- Deploy V4-Alpha SHADOW como nuevo systemd service
- 13 tests pass

**Vie 8 12:30 UTC:** NFP STRESS TEST 1 con dashboard live para tu audit

Si firmas las 4 antes de las 14:00 UTC, deploy completo antes del NFP.

Gracias.
