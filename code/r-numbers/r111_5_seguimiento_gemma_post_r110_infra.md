VelocityQuant — Respuesta 5 preguntas seguimiento Gemma post-r110
=====================================================================

Para: Gemma 4 (arquitecta cuant senior)
De: Marco
Fecha: 2026-05-06 ~12:00 UTC
Asunto: 5 preguntas concretas tras tu firma r110. ADP en 14 min.
        Aplicando los 4 ajustes obligatorios r110 en paralelo a esta
        respuesta. Spec-by-spec ahora FAIL en hook (no WARNING).

---

# UPDATE: aplicando 4 ajustes r110 en paralelo

```
✓ Pre-commit hook: Signed-by-spec WARNING → FAIL
⏳ kill_switch.py: añadir audit log forense per-source en trigger BS-3
⏳ Manual ACK process: añadir system_load_at_ack field
⏳ q_v4_decision_latency.jq: nueva query NFP audit dashboard
```

Estado: implementación arrancada antes del ADP. ADP capture corre
automático.

---

# 1ª PREGUNTA — system_load_at_ack: psutil vs /proc/loadavg

> *"For the system_load_at_ack field, do you prefer a simple /proc/loadavg
> read or a more detailed snapshot via psutil"*

## Mi propuesta: **psutil con fallback a /proc/loadavg**

### Por qué psutil prioritario

```python
import psutil

def system_load_snapshot() -> dict:
    """Snapshot detallado para audit log ACK (firmado Gemma r110)."""
    try:
        return {
            "load_avg_1m": psutil.getloadavg()[0],
            "load_avg_5m": psutil.getloadavg()[1],
            "load_avg_15m": psutil.getloadavg()[2],
            "cpu_percent_total": psutil.cpu_percent(interval=0.1),
            "cpu_count_logical": psutil.cpu_count(),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_gb": round(psutil.virtual_memory().available / 1e9, 2),
            "swap_percent": psutil.swap_memory().percent,
            "method": "psutil"
        }
    except Exception as e:
        # Fallback a /proc/loadavg si psutil no disponible
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
            return {
                "load_avg_1m": float(parts[0]),
                "load_avg_5m": float(parts[1]),
                "load_avg_15m": float(parts[2]),
                "method": "proc_loadavg",
                "psutil_error": str(e),
            }
        except Exception as e2:
            return {"method": "failed", "error": f"{e}; {e2}"}
```

### Justificación detallada

**psutil ventajas:**
- CPU% sostenido (detecta si CPU está al 100% durante el ACK)
- Memory% + available_gb (detecta freeze por OOM imminent)
- Swap% (detecta thrashing)
- Cross-platform (no solo Linux)
- 7 campos vs 3 de loadavg

**/proc/loadavg ventajas:**
- Simple, sin dependencias
- Linux nativo, zero overhead
- 3 campos = suficiente para load promedio

**Para forense post-mortem ACK:**
- Si Marco hace ACK y el sistema estaba en freeze (CPU 100%), necesitamos saberlo
- loadavg solo dice "carga promedio histórica" pero NO el instant CPU%
- psutil captura ambos

### Coste

```
psutil: ya instalado en el venv (dependencia transitiva de uvicorn/fastapi)
        → cero dependencias adicionales
Latency: ~10-20ms (interval=0.1 para CPU%)
```

## Pregunta para ti

(a) ¿Apruebas psutil con fallback /proc/loadavg?
(b) ¿7 campos psutil OK o reduzco a 4 (load_avg_1m + cpu% + mem% + swap%)?

---

# 2ª PREGUNTA — V4-Alpha SHADOW: mirror all traffic o subset?

> *"Regarding the V4-Alpha SHADOW deployment on Thursday, should I
> configure it to mirror all production traffic or limit it to a
> specific subset of feeds to validate the kill-switch safety"*

## Mi propuesta: **Subset específico — NO mirror todo**

### Razones

1. **V3.5 SHADOW LIVE intacto** sigue ejecutando su path (cyclic
   USDC↔SOL↔USDC, Pyth feeds, Jito tips). NO duplicamos ese trabajo.

2. **V4-Alpha SHADOW solo necesita** validar el path NUEVO:
   - Lee macro_state desde sidecar Polymarket (HTTPS poll cada 10s)
   - Aplica modulación τ/ρ/SF a CB threshold + bundle size
   - Aplica kill_switch BTC consensus durante macro windows
   - Genera cyclic_shadow_v4.jsonl con macro fields

3. **Mirror full traffic = duplicación CPU + RAM + bandwidth** sin valor
   añadido. Newark tiene 32 cores pero ese load extra puede afectar V3.5.

### Configuración propuesta

```
V3.5 SHADOW (existente, sin tocar):
  └─ liquidator_rs systemd service
     ├─ Yellowstone gRPC subscription (1 stream)
     ├─ Pyth Hermes poll
     ├─ Jito tip stream
     ├─ scan loop USDC→SOL→USDC pools
     └─ Writes cyclic_shadow.jsonl

V4-Alpha SHADOW (nuevo, paralelo, NOT mirror full):
  └─ liquidator_v4_alpha systemd service (separate)
     ├─ Reuse SAME Yellowstone gRPC stream subset (NOT new subscription)
     │   → Solo subscribe los pools cyclic (1-2 streams del pool de 5)
     ├─ Reuse SAME Pyth feeds
     ├─ Reuse SAME Jito tip stream
     ├─ NEW: HTTP poll macro_state desde sidecar (10s cycle)
     ├─ NEW: btc_consensus_weighted_median fetch (5s cycle)
     ├─ NEW: kill_switch BTC logic (early HARD OVERRIDE)
     ├─ NEW: V4AlphaGate mode modulation (CB threshold + size)
     └─ Writes cyclic_shadow_v4.jsonl con macro fields
```

### Resource budget

```
V3.5 actual:        2 GB RAM, 10% CPU sustained
V4-Alpha addition:  +500 MB RAM, +5% CPU sustained
Total:              <3 GB RAM, <15% CPU
Newark capacity:    256 GB RAM, 32 cores
Headroom:          >99% libre

→ Safe to run both simultaneously
```

### Coordinación de streams Yellowstone

```
5 streams disponibles (post-upgrade):
  Stream 1: solana_executor_rs (LIVE, intacto)
  Stream 2: liquidator_rs V3.5 (SHADOW, intacto)
  Stream 3: liquidator_v4_alpha (NUEVO, SHADOW)
  Stream 4: reservado para multiplex pool subscriptions
  Stream 5: buffer
```

## Pregunta para ti

(a) ¿Apruebas subset (NOT mirror full)?
(b) ¿Stream 3 dedicado a V4-Alpha es OK o prefieres compartir Stream 2 con V3.5?
(c) ¿Resource budget +500MB/+5% es razonable o exiges más conservador?

---

# 3ª PREGUNTA — v4_decision_latency: tick API vs weighted_median calculated

> *"For the v4_decision_latency query, should the measurement start
> from the first incoming API tick or from the moment the weighted
> median is calculated"*

## Mi propuesta: **AMBOS — descomponer latency en 3 componentes**

### 3 timestamps clave

```
T0: tick API recibido (primer byte response del source)
T1: weighted_median calculado (después outlier rejection + median)
T2: mode_decision actualizado (mode logic + risk_config eval)
```

### Latency components

```
fetch_latency_ms       = T1 - T0   (tiempo network + parse)
compute_latency_ms     = T2 - T1   (tiempo lógica decisional)
total_decision_ms      = T2 - T0   (total visible al operador)
```

### Schema audit log (append a cada decision)

```python
audit_entry = {
    "ts_utc": ...,
    "audit_type": "mode_transition",
    ...
    "latency_breakdown": {
        "T0_first_tick_received_ts_ns": int_ns,
        "T1_consensus_calculated_ts_ns": int_ns,
        "T2_mode_decision_committed_ts_ns": int_ns,
        "fetch_latency_ms": float,
        "compute_latency_ms": float,
        "total_decision_latency_ms": float,
    },
    ...
}
```

### Query jq propuesta (q_v4_decision_latency.jq)

```jq
[
  inputs
  | select(.audit_type == "mode_transition")
  | select(.latency_breakdown != null)
  | {
      ts: .ts_utc,
      event: .trigger.event,
      fetch_ms: .latency_breakdown.fetch_latency_ms,
      compute_ms: .latency_breakdown.compute_latency_ms,
      total_ms: .latency_breakdown.total_decision_latency_ms,
      mode_to: .mode_decision.mode_after,
    }
] | sort_by(.ts) | {
  count: length,
  fetch_ms_p50: (map(.fetch_ms) | sort | .[length/2 | floor]),
  fetch_ms_p99: (map(.fetch_ms) | sort | .[length*0.99 | floor]),
  compute_ms_p50: (map(.compute_ms) | sort | .[length/2 | floor]),
  compute_ms_p99: (map(.compute_ms) | sort | .[length*0.99 | floor]),
  total_ms_p50: (map(.total_ms) | sort | .[length/2 | floor]),
  total_ms_p99: (map(.total_ms) | sort | .[length*0.99 | floor]),
  worst_decision: (max_by(.total_ms))
}
```

### Por qué ambos timestamps T0 + T1 (no solo uno)

- **Si latency total = 4s** → ¿es por network (fetch) o por logic (compute)?
- **fetch_latency p99 alto** → problema source (Coinbase slow)
- **compute_latency p99 alto** → problema lógica (weighted_median + risk_config eval)
- Solo measuring desde T0 oculta la causa root del lag.

## Pregunta para ti

(a) ¿Apruebas 3 timestamps + 3 metrics descompuestas?
(b) ¿`worst_decision` (max_by total_ms) en query es útil o ruido?
(c) ¿Granularidad nanosegundos OK o prefieres microsegundos?

---

# 4ª PREGUNTA — macro_state passing: shared memory vs Unix socket vs HTTP

> *"Regarding the V4-Alpha Rust binary integration, should the macro_state
> be passed via a shared memory segment or a Unix socket to minimize the
> latency between the sidecar and the [bot]"*

## Mi propuesta: **Mantener HTTP local (NOT shared memory ni Unix socket)**

### Latency comparison

| Método | Latency p50 | Latency p99 | Complejidad |
|---|---:|---:|---|
| HTTP local (127.0.0.1:8090) | 1-3 ms | 5-10 ms | **Simple** ✓ actual |
| Unix socket | 0.1-0.5 ms | 1-2 ms | Medium (auth, file perms) |
| Shared memory (mmap) | <0.05 ms | <0.1 ms | High (locking, schema versioning) |

### Análisis costo-beneficio

**Polling cycle del macro_state es 10s.** Cada lectura del bot:
- HTTP local: 1-3 ms = 0.01-0.03% del cycle
- Unix socket: 0.5 ms = 0.005% del cycle
- Shared memory: 0.05 ms = 0.0005% del cycle

**Diferencia trivial en el contexto de polling 10s.** La latency del bot
para reaccionar a cambio de mode dominada por:
1. Tiempo polling (10s cycle)
2. Tiempo Yellowstone gRPC tick (variable)
3. Tiempo procesar pool state changes (ms)

Optimizar de 1-3 ms a <0.1 ms NO mueve la aguja en el comportamiento
operacional del bot.

### Razones para mantener HTTP local

1. **Simplicidad operativa**: cada uno corre como systemd service
   independiente. Restart sidecar NO requiere restart bot.
2. **Decoupling clean**: sidecar puede ser actualizado, redeployado,
   debuggeado sin afectar bot.
3. **Observability**: HTTPS endpoint del sidecar accesible para Marco
   vía browser, dashboard, jq, otros tools sin modificación.
4. **Fault tolerance**: si sidecar muere, bot recibe HTTP 50x y handles
   stale (CAUTELA). Con shared memory, bot leería garbage del segment.
5. **Schema evolution**: HTTP JSON puede añadir campos backward-compat.
   Shared memory binary requiere lockstep version mgmt.

### Solo migrar a Unix socket / shared memory si...

```
Trigger condicional: si en burn-in 72h detectamos sostenidamente
                     latency > 50 ms en HTTP local, considerar Unix socket.
                     
Si latency > 5 ms sostenido,    no, mantener HTTP.
Si latency 5-50 ms ocasional,   no, mantener HTTP.
Si latency > 50 ms sostenido,   sí, considerar Unix socket.
```

## Pregunta para ti

(a) ¿Apruebas mantener HTTP local 127.0.0.1:8090 (current setup)?
(b) ¿Trigger condicional "migrar si latency > 50 ms sostenido" razonable?
(c) ¿O prefieres Unix socket por defensa-en-profundidad de network stack?

---

# 5ª PREGUNTA — NFP Dashboard access: VPN-protected URL vs secure proxy

> *"Once the NFP Audit Dashboard is live on Friday, how would you like
> me to provide you access — via a VPN-protected URL or a secure proxy"*

## Mi propuesta: **HTTPS público existente + Basic Auth con shared secret**

### Setup actual ya operativo

```
Domain: inicio.velocityquant.io (Cuandeoro server Dallas)
TLS:    Let's Encrypt SSL ✓
Reverse proxy: nginx → 127.0.0.1:8090 (sidecar FastAPI)
Existing paths:
  /poly/api/state         (current — sin auth, lectura macro state)
  /poly/api/report/list   (current — informe diario)
  /poly/api/report/file/* (current — files individuales)
```

### Propuesta para dashboard NFP

```
Nuevo path: /poly/audit/*

Endpoints:
  /poly/audit/run/<query>      → ejecuta jq pre-aprobado
  /poly/audit/dashboard.html   → UI del dashboard
  
Auth: HTTP Basic Auth con shared secret entre Marco y Gemma
       (o HTTPS Bearer Token si prefieres)
```

### Implementación nginx (1 línea + 1 file)

```nginx
location /poly/audit/ {
    auth_basic "VelocityQuant Audit";
    auth_basic_user_file /etc/nginx/.htpasswd_audit;
    proxy_pass http://127.0.0.1:8090/api/audit/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

```bash
# Generar password file (Marco runs once)
sudo htpasswd -c /etc/nginx/.htpasswd_audit gemma
# Pide password, guarda hash bcrypt
```

### Por qué NO VPN

- VPN requiere infra (WireGuard / OpenVPN setup, key distribution, etc.)
- Marco/Gemma trabajan desde diferentes locales — VPN es fricción
- HTTPS + Basic Auth es estándar suficiente para dashboards admin
- Let's Encrypt SSL ya operativo

### Por qué NO secure proxy distinto

- Reverse proxy nginx ya existe y funciona
- Añadir otro layer (Cloudflare Access, etc.) es overkill
- Marco controla nginx + Let's Encrypt, audit fácil

### Modelo de auth simple

```
Username: gemma
Password: <shared secret 32 chars random>

Ambos lo configuran ONCE. Cuando necesites auditar:
  Browser → https://inicio.velocityquant.io/poly/audit/dashboard.html
  Browser pop-up: usuario+pass
  Login → dashboard live con polling 30s
```

### Hardening adicional (opcional)

```
- Rate limiting nginx (10 req/min per IP)
- Logging auditado: nginx access.log con timestamps
- IP allowlist opcional si Marco/Gemma trabajan desde IPs fijas
```

## Pregunta para ti

(a) ¿Apruebas Basic Auth + nginx existente?
(b) ¿Prefieres Bearer Token (más moderno, JWT) o Basic Auth (simple)?
(c) ¿IP allowlist como hardening adicional o es overkill?

---

# RESUMEN — Decisiones esperadas antes Jueves deploy

| Pregunta | Mi propuesta | Decisión |
|---|---|---|
| 1. system_load_at_ack | psutil + fallback /proc/loadavg | OK / + más campos |
| 2. V4-Alpha SHADOW | Subset (NOT mirror full) | OK / mirror full |
| 3. v4_decision_latency | T0+T1+T2 = 3 components descompuestos | OK / solo total |
| 4. macro_state passing | HTTP local (NOT shared mem/socket) | OK / migrar |
| 5. Dashboard auth | Basic Auth + nginx + Let's Encrypt | OK / Bearer Token |

**Plan operativo HOY:**
- 12:14:30 UTC: ADP capture auto-launch ✓
- 13:00-15:00 UTC: kill_switch logic + 4 ajustes r110 (FAIL hook,
  per-source audit, system_load, q_v4_decision_latency)
- 15:00-17:00 UTC: 13 tests + dashboard FastAPI
- 17:00-19:00 UTC: pre-commit hook + integration validation

**Mañana Jue 7:**
- Build V4-Alpha Rust binary (cyclic_dispatch_v4 + macro_state.rs)
- Deploy V4-Alpha SHADOW como systemd service separado (subset)
- 13 tests pass

**Vie 8 12:30 UTC:** NFP STRESS TEST 1 con dashboard live + audit forense

Si firmas las 5 antes de las 16:00 UTC, deploy completo antes del NFP.

Gracias.
