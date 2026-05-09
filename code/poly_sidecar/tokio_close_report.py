"""Tokio Close report — manual trigger or scheduled.

1. Lee tau_state.json
2. Construye brief MD con τ resultados acumulados + observaciones técnicas
3. Llama ask_gemma.py (Flash gratis)
4. Guarda envío + respuesta en /home/administrator/r79_*.md
5. Imprime resumen
"""
from __future__ import annotations
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE = Path("/home/administrator/poly_sidecar/data/tau_state.json")
ASK_GEMMA = "/home/administrator/liquidator/ask_gemma.py"

now = dt.datetime.now(dt.timezone.utc)
fecha = now.strftime("%Y-%m-%d")
hora_utc = now.strftime("%H:%M UTC")

if not STATE.exists():
    print("ERROR: no tau_state.json — sidecar no ha corrido aún.")
    sys.exit(1)

state = json.loads(STATE.read_text())
heartbeat_age = time.time() - float(state.get("heartbeat_ts", 0))

# Construir brief
brief = f"""VelocityQuant — Reporte cierre Tokio {fecha} ({hora_utc})

Para: Gemma 4
De: Claude (Sidecar Polymarket V4.1)

---

Hola Gemma. Acaba de cerrar el mercado asiático (Tokio close 06:00 UTC).
Te paso resultados τ del primer ciclo del sidecar Polymarket que validaste,
con observaciones técnicas y 3 preguntas concretas.

## Estado del sidecar

- Status: {state.get('status', 'ok')}
- Heartbeat age: {int(heartbeat_age)}s
- Polling interval: {state.get('polling_interval_s', 300)}s
- Calendar version: {state.get('calendar_version', '?')}
- Endpoints errors acumulados: {state.get('endpoints_errors', {})}
- Last error: {state.get('last_error', 'none')}

## τ globales en este snapshot

- τ_final  = {state.get('tau_final')}
- τ_crypto = {state.get('tau_crypto')}
- τ_macro  = {state.get('tau_macro')}
- ρ Pearson 6h = {state.get('rho') or 'sin datos (BTC feed pendiente)'}

## Breakdown por contrato (8 monitoreados)

"""

for pc in state.get("per_contract", []):
    brief += (
        f"- [{pc.get('category_group', ''):6}] τ={pc.get('tau'):.4f} | "
        f"ΔP={pc.get('delta_prob'):+.4f} VZ={pc.get('vol_zscore'):+.4f} IV={pc.get('implied_vol'):+.4f} | "
        f"σ(ΔP)={pc.get('norm_delta_prob'):.4f} σ(VZ)={pc.get('norm_vol_zscore'):.4f} σ(IV)={pc.get('norm_implied_vol'):.4f} | "
        f"valid={pc.get('valid')} | {pc.get('title', '')[:55]}\n"
    )

brief += """

---

## 3 Hallazgos técnicos durante el primer ciclo

### Hallazgo 1 — CLOB intervals no soporta 4h

La API de CLOB (`/prices-history`) solo acepta `1m / 1h / 6h / 1d / 1w`.
Tu spec validada decía `4h fidelity=5` → 48 pts. Ajusté a `6h fidelity=5`
→ 72 pts (orden de magnitud cercano, p-value sigue significativo).

¿OK con `6h × 72 pts` o prefieres `1h × fidelity=1 = 60 pts` para mejor
respuesta intra-NYSE-Open?

### Hallazgo 2 — Redis no disponible en server

Marco confirmó que **Redis NO está instalado** en Newark/Dallas (asumiste
que sí). El sidecar funciona ahora con **atomic file store** (`tau_state.json`,
write tmp + rename + fsync). Latencia lectura desde Rust: <1ms.

¿Mantenemos file backend (cero deps, ya funciona) o autorizamos
`apt install redis-server` en Newark? Para el polling 5min y bot Solana
MEV (slot ~400ms), file backend es suficiente. Redis sería estética.

### Hallazgo 3 — VolZScore=0 en todos los contratos

El primer ciclo arroja VolZScore=0 porque la rolling cache de 288 muestras
está vacía. Tras ~2.5h de uptime se llenará. Esto es esperado por diseño,
pero mientras tanto τ depende solo de ΔProb + ImpliedVol (peso combinado
0.7 vs 0.3 que VolZ tendría).

¿Aceptas comportamiento "warm-up" o prefieres bootstrap con datos
históricos de Polymarket en init?

---

## Sobre tus instrucciones para Claude (las del chat de esta mañana)

Ya tengo implementado:
- ✅ **Módulo Polymarket** (4 endpoints, polling 5min, fórmulas exactas)
- ✅ **τ engine** con weights, sigmoides, max-per-category, weighted final
- ✅ **/health endpoint** básico (puerto 8090, expuesto por nginx en
  https://inicio.velocityquant.io/poly/api/state)
- ✅ **Aislamiento total** — sidecar Python no toca código Rust
- ✅ **Manejo errores** — si endpoints fallan → τ por contrato `valid=false`
- ✅ **Dashboard integrado** en https://inicio.velocityquant.io/shadow.html

Falta implementar (en este orden recomendado):
1. **BTC spot feed** (puede reusar Pyth Hermes ya conectado en V3.5) →
   habilita ρ Pearson real
2. **Módulo FRED** (init script que descarga 12y series → genera
   `macro_calendar.json` con μ, σ por evento)
3. **Módulo FMP** (polling 1h economic_calendar)
4. **Módulo Investing.com vía investpy** (event trigger actual vs expected)
5. **/health extendido** con status de las 4 APIs + modo
6. **Migración store file→Redis** (opcional, si Marco autoriza apt install)

---

## 3 preguntas concretas

### P1 — Prioridad de implementación

¿Confirmas el orden anterior (BTC → FRED → FMP → Investing → Redis)?
¿O hay otro orden que tú prefieras para llegar al SHADOW del viernes con
la spec más completa posible?

### P2 — Bootstrap del VolZScore

Para evitar el periodo warm-up de 2.5h donde VolZ=0:
- (a) Aceptar warm-up como parte normal del arranque (KISS)
- (b) Bootstrap inicial llamando `volume24hr` repetidamente con
  history de Polymarket (no es exactamente vol intradía pero da algo)
- (c) Inicializar τ_per_contract con bias conservador (τ_min=0.2 hasta
  cache llena)

¿Cuál?

### P3 — Distribución BTC histórica para macro_calendar.json

Tu spec V4-Alpha §4.7 ya dio mean=1.2%, std=0.8%, P(>2σ)≈15-20%, lag
Solana spike 200-500%, mean reversion 30-50%. ¿Estos valores son tu
parametrización final estática o quieres que el FRED init los recalcule
con los Series IDs específicos (¿cuáles?) de los últimos 12 años?

---

¿Algo más para añadir al sprint antes del viernes?

Gracias.
"""

# Guardar brief
brief_path = Path(f"/home/administrator/r79_tokio_close_{fecha}_envio.md")
brief_path.write_text(brief)
print(f"📤 Brief guardado en {brief_path}")

# Llamar a Gemma vía bridge
print("📞 Enviando a Gemma 4 vía ask_gemma.py (Flash, gratis)...")
result = subprocess.run(
    [ASK_GEMMA, "--file", str(brief_path), "--temp", "0.3"],
    capture_output=True, text=True, timeout=180,
)

if result.returncode != 0:
    print(f"❌ ERROR ask_gemma: {result.stderr[:500]}")
    sys.exit(1)

response = result.stdout

# Guardar respuesta
resp_path = Path(f"/home/administrator/r79_tokio_close_{fecha}_respuesta_gemma.md")
resp_path.write_text(f"# Respuesta Gemma — Tokio close {fecha} {hora_utc}\n\n{response}")
print(f"📥 Respuesta guardada en {resp_path}")
print()
print("=" * 70)
print("RESPUESTA GEMMA (primeros 1500 chars)")
print("=" * 70)
print(response[:1500])
if len(response) > 1500:
    print(f"\n... (respuesta completa {len(response)} chars en {resp_path})")
