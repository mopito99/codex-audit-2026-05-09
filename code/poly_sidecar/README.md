# Polymarket Sentiment Sidecar

VelocityQuant V4.1 — calcula τ (tensión de mercado) cada 5 min desde
Polymarket REST API y lo escribe en atomic store para que el bot Rust
(V4-Alpha SHADOW desde 2026-05-08, V4 LIVE desde 2026-05-11) lo lea
sin bloquear su hot path.

## Componentes

| Archivo | Función |
|---|---|
| `macro_calendar.json` | Config estática validada por Gemma 4: contratos + token_ids + sigmoide params + ventanas + distribución BTC 12y |
| `poly_client.py` | HTTP client async (httpx). Endpoints: gamma-api/markets/{id}, clob/midpoint, clob/spread, clob/prices-history |
| `tau_calc.py` | Fórmulas exactas: ΔProb, VolZScore, ImpliedVol, sigmoid, τ_per_contract, τ_macro, τ_crypto, τ_final, ρ Pearson |
| `store.py` | Atomic file-based store (write tmp + rename). Backend Redis cuando se instale. |
| `sidecar.py` | Loop principal cada 300s |
| `health_api.py` | FastAPI endpoint /health (puerto 8090) |

## Fórmula final (validada por Gemma 4 2026-05-05)

```
τ_per_contract = 0.5·sig(ΔProb) + 0.3·sig(VolZScore) + 0.2·sig(ImpliedVol)

ΔProb       = (P_now − P_avg_4h_history) / P_avg_4h_history
VolZScore   = (V_24h − μ_rolling288) / σ_rolling288     (24h × 5min = 288 pts)
ImpliedVol  = spread / midpoint

Sigmoid params:
  ΔProb        : k=10  x0=0.10
  VolZScore    : k=2   x0=1.0
  ImpliedVol   : k=50  x0=0.02

τ_macro  = max(τ_per_contract for c in macro)
τ_crypto = max(τ_per_contract for c in crypto)
τ_final  = 0.7·τ_crypto + 0.3·τ_macro

Aplicación al CB y bundle size (en V4-Alpha Rust):
  Th_adj   = max(2, Th_after_macro − floor(τ_final × 6))
  Size_adj = Size_after_macro × (1 − τ_final)

ρ Pearson rolling 6h × fidelity 5 (72 pts) entre ΔBTC y ΔP_evento_bajista.
ρ < −0.7 → Modo Defensivo (Th −2, Size −30%) independiente de τ.
```

## Test de un ciclo manual

```
cd /home/administrator/poly_sidecar
./venv/bin/python sidecar.py     # Ctrl-C para parar
```

Output esperado en `data/tau_state.json` con τ_final, τ_macro, τ_crypto,
heartbeat_ts, errores por endpoint, breakdown por contrato.

## Ejecutar como servicio systemd (pendiente autorización Marco)

```ini
# /etc/systemd/system/poly_sidecar.service
[Unit]
Description=VelocityQuant Polymarket Sentiment Sidecar
After=network.target

[Service]
Type=simple
User=administrator
WorkingDirectory=/home/administrator/poly_sidecar
ExecStart=/home/administrator/poly_sidecar/venv/bin/python sidecar.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Y otro para health API:

```ini
# /etc/systemd/system/poly_sidecar_health.service
[Unit]
After=poly_sidecar.service
[Service]
Type=simple
User=administrator
WorkingDirectory=/home/administrator/poly_sidecar
ExecStart=/home/administrator/poly_sidecar/venv/bin/uvicorn health_api:app --host 127.0.0.1 --port 8090
Restart=always
[Install]
WantedBy=multi-user.target
```

## Decisión pendiente: Newark vs Dallas

Actualmente el sidecar está en **Dallas (administrator)**. El bot V3.5/V4
corre en **Newark (ubuntu)**. Dos opciones:

1. **Sidecar en Newark también** (recomendado): copy del directorio a
   `ubuntu@64.130.34.38:/home/ubuntu/poly_sidecar/` + venv + systemd unit.
   El bot Rust lee el `tau_state.json` local — latencia µs, sin dependencia red.

2. **Sidecar en Dallas + Rust hace HTTP**: bot Rust pega a
   `http://dallas-ip:8090/health` cada slot. Más simple en infra pero añade
   ~1-5ms RTT y dependencia de la red entre servers.

Marco decide. Recomendación: opción 1 (en Newark, junto al bot).

## Estado actual

- ✅ Todos los componentes Python implementados y testeados
- ✅ Test end-to-end con 8 contratos LIVE de Polymarket
- ✅ Atomic write funciona (write tmp + rename)
- ⬜ systemd units NO instaladas todavía (esperando OK Marco)
- ⬜ Modificación Rust V3.5 / V4-Alpha para leer `tau_state.json` (plan en r77)
