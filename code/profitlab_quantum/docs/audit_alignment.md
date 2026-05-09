# Audit Alignment Checklist (Informe ↔ Implementación)

Objetivo: facilitar una auditoría 1:1 contra el informe "arquitectura_cuantitativa_smc_drl_generativo".

## 1) Market Data (BingX) + Event Loop
- **WS para detectar nuevo candle (baja latencia)**
  - Implementación: `main.py` usa `BingXSwapWebSocket` y cae a REST si falla.
  - Archivos: `app/data/bingx_ws.py`, `main.py`
- **REST como fuente de verdad para construir DataFrames (evitar drift)**
  - Implementación: `BingXReader.get_klines()` y reconstrucción completa de features por vela.
  - Archivos: `app/data/bingx.py`, `main.py`

## 2) Microestructura institucional (Orderbook)
- **Orderbook depth snapshot (read-only)**
  - Implementación: `BingXReader.get_depth()` usando `/openApi/swap/v2/quote/depth`.
  - Features derivadas: `mid`, `spread_bps`, `imbalance`, `bid_depth_usd`, `ask_depth_usd`.
  - Archivos: `app/data/bingx.py`, `main.py`, `app/engine.py`

## 3) SMC Features (OB/FVG/Sweeps) + Gating
- **FVG/OB con niveles activos, edad, tests y mitigación**
  - Implementación: forward-fill de niveles, cálculo de `*_age`, `*_tests`, `*_mitigated`.
  - Archivos: `app/features/smc_features.py`
- **Gating institucional (decisor sí/no)**
  - Implementación: scores de confluencia + umbral; fuerza HOLD si no hay setup.
  - Archivos: `app/engine.py`

## 4) Agentes (2 cerebros)
- **PPO + TransformerEncoder (per-symbol, chunked)**
  - Implementación: un `QuantumEngine` por símbolo; pesos PPO aislados por símbolo; buffer rolling (default 72h) con updates cada 12h.
  - Config: `PPO_PER_SYMBOL`, `PPO_WEIGHTS_DIR`, `PPO_LEARNING_MODE`, `PPO_CHUNK_*`.
  - Archivos: `app/models/agent.py`, `app/engine.py`, `main.py`, `app/config.py`
- **Decision Transformer (offline)**
  - Implementación: `DecisionTransformerAgent` (sin aprendizaje en vivo) y selección por `AGENT_TYPE`.
  - Archivos: `app/models/decision_transformer.py`, `app/engine.py`, `app/config.py`

## 5) Pegamento de producción (weights, watchdogs, audit)
- **Carga automática de pesos (PPO/DT) si existen**
  - Config: PPO global `PPO_WEIGHTS_PATH` (bootstrap) o por símbolo `PPO_WEIGHTS_DIR` + `PPO_PER_SYMBOL`; DT `DT_WEIGHTS_PATH`, `DT_META_PATH`.
  - Archivos: `app/config.py`, `app/engine.py`
- **Autosave PPO (auditable)**
  - Config: `PPO_AUTOSAVE_PATH`, `PPO_AUTOSAVE_EVERY_UPDATES`.
  - Archivo: `app/models/agent.py`
- **Heartbeat para watchdog externo**
  - Archivo: `/tmp/profitlab_quantum/heartbeat.json` (actualizado periódicamente, independiente de eventos WS o nuevo candle).
  - Señales: `ts_utc` (liveness) + `ws_last_event_age_s` / `last_processed_at_utc` (frescura funcional por símbolo).
  - Archivo: `main.py`
- **Health endpoint**
  - Endpoint: `GET /api/health` expone estado + heartbeat.
  - Archivo: `web/main.py`
- **Watchdog CLI**
  - Script: `tools/watchdog_check.py` valida staleness del heartbeat.

## 6) Costes realistas (fees + slippage)
- **Fees (maker/taker) y slippage bps configurables**
  - Config: `BINGX_FEE_MAKER`, `BINGX_FEE_TAKER`, `BINGX_SLIPPAGE_BPS`.
  - Aplicación: slippage en fills y fees descontadas de PnL en CLOSE.
  - Archivos: `app/config.py`, `main.py`

## 7) TimeGAN (generativo)
- **Modelo TimeGAN entrenable + sampling**
  - Archivos: `app/models/timegan.py`, `tools/train_timegan.py`

## 8) Scripts de auditoría / smoke
- **Audit smoke probe**
  - Script: `tools/run_audit_smoke.py` (depth OK + existencia de artifacts + env snapshot)

---

### Comandos útiles (auditoría rápida)
- Smoke report: `venv/bin/python tools/run_audit_smoke.py --symbol BTC-USDT --limit 20 --out artifacts/audit_smoke.json`
- Watchdog: `venv/bin/python tools/watchdog_check.py` (usa `/tmp/profitlab_quantum/heartbeat.json`)
