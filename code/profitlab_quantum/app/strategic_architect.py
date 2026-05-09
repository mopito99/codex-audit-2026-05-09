"""
Strategic Architect v1 — El Arquitecto Ejecutivo (Gemma4:latest)
===================================================
Modelo de ruteo cognitivo para Quantum Bot.

Funciona ejecutándose 1-2 veces al día para evaluar "the big picture".
Aplica la filosofía de "Knowledge Distillation":
El modelo pesado genera la estrategia diaria, el bot ágil la ejecuta a 5 minutos.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

from app.db import engine as db_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StrategicArchitect")

_PARAMS_PATH = str(Path(__file__).resolve().parent.parent / "data" / "auto_params.json")

ARCHITECT_PROMPT = """Eres el DIRECTOR DE ESTRATEGIA (El Arquitecto) de un Hedge Fund Cuantitativo (ProfitLab Quantum).
Operas mediante la filosofía algorítmica "Liquidez Inteligente". 

DATOS REALES DE LAS OPERACIONES RECIENTES EN BINGX (Small-Caps, 5min timeframe):
- Total Trades Recientes: {total}
- Rendimiento Global PnL: ${total_pnl:.2f}
- Drawdown Máximo del portfolio: {dd_pct:.1f}%

Desglose de Operaciones:
- LONG: {long_n} trades, WR={long_wr:.0f}%, AvgPnL=${long_avg:.2f}
- SHORT: {short_n} trades, WR={short_wr:.0f}%, AvgPnL=${short_avg:.2f}
- Cierres Proyectados (Runners): {close_n} trades, {close_wins} wins, {close_losses} losses
- Ganancia Diurna (06-22 UTC): ${day_pnl:.2f}
- Pérdida/Ganancia Nocturna (22-06 UTC): ${night_pnl:.2f}

Evalúa esta data de forma estructurada.

PASO 1: Analiza la data. Escribe un diagnóstico profesional (max 3-4 párrafos), objetivo y neutral. "Liquidez Inteligente" y el "Spread Guardian" están funcionando bien. ¿El Drawdown es muy alto? ¿Cerrar los shorts fue buena idea?

PASO 2: Emite la estructura de JSON con los parámetros de la sesión para el modelo ágil ("El Soldado").
Los parámetros son los que el bot de ejecución usará a ciegas. Sé extremadamente conservador si el drawdown supera el 10%.

Debes responder exactamente con este formato y nada más:
### ANALISIS
(tu diagnóstico profundo aquí escrito en español técnico y experto)

### JSON
```json
{{"trading_enabled":true,"shorts_enabled":false,"night_mode":"off","max_positions":4,"short_btc_threshold":-0.5,"long_btc_block":-1.5,"tp0_close_pct":0.50,"tp1_close_pct":0.30}}
```
"""


def _wr(pnls: list[float]) -> float:
    if not pnls: return 0.0
    return (sum(1 for p in pnls if p > 0) / len(pnls)) * 100


def evaluate_and_route() -> None:
    logger.info("Activando a 'El Arquitecto' (Gemma4:latest)... leyendo métricas globales.")
    
    with db_engine.connect() as db:
        rows = db.execute(text("""
            SELECT event, action, pnl_usd,
                   EXTRACT(HOUR FROM timestamp)::int as hour_utc
            FROM paper_trades
            WHERE pnl_usd IS NOT NULL AND pnl_usd != 0
            ORDER BY timestamp DESC LIMIT 400
        """)).fetchall()

        # Get peak vs balance to calculate total drawdown
        equity_rows = db.execute(text("""
            SELECT balance, peak 
            FROM paper_equity 
            WHERE balance > 0 OR peak > 0
        """)).fetchall()

    if not rows:
        logger.error("No hay operaciones suficientes en la BD para generar un diagnóstico.")
        return

    # Métrica de Drawdown Global
    total_balance = sum(float(r.balance) for r in equity_rows)
    total_peak = sum(float(r.peak) for r in equity_rows)
    dd_pct = ((total_peak - total_balance) / max(total_peak, 1)) * 100 if total_peak > 0 else 0

    # Segregación de trades
    long_pnls = [float(r.pnl_usd) for r in rows if r.action == "LONG"]
    short_pnls = [float(r.pnl_usd) for r in rows if r.action == "SHORT"]
    close_rows = [r for r in rows if r.event == "CLOSE"]
    close_wins = sum(1 for r in close_rows if float(r.pnl_usd) > 0)
    close_losses = sum(1 for r in close_rows if float(r.pnl_usd) < 0)

    day_pnl = sum(float(r.pnl_usd) for r in rows if 6 <= r.hour_utc < 22)
    night_pnl = sum(float(r.pnl_usd) for r in rows if r.hour_utc >= 22 or r.hour_utc < 6)
    total_pnl = sum(float(r.pnl_usd) for r in rows)

    stats = {
        "total": len(rows),
        "long_n": len(long_pnls), "long_wr": _wr(long_pnls),
        "long_avg": sum(long_pnls) / max(len(long_pnls), 1),
        "short_n": len(short_pnls), "short_wr": _wr(short_pnls),
        "short_avg": sum(short_pnls) / max(len(short_pnls), 1),
        "close_n": len(close_rows), "close_wins": close_wins, "close_losses": close_losses,
        "day_pnl": day_pnl, "night_pnl": night_pnl,
        "total_pnl": total_pnl, "dd_pct": dd_pct,
    }

    prompt = ARCHITECT_PROMPT.format(**stats)

    logger.info("Solicitando análisis matricial a Gemma4:latest...")
    
    try:
        resp = requests.post("http://localhost:11434/api/generate", json={
            "model": "gemma4:latest",
            "prompt": prompt,
            "stream": False,
            
        }, timeout=240)
        
        resp.raise_for_status()
        content = resp.json().get("response", "")
        
        logger.info("Respuesta de 'El Arquitecto' recibida. Extrayendo dictamen...")
        
        analisis_match = re.search(r'### ANALISIS\s*(.*?)(?=### JSON|$)', content, re.DOTALL | re.IGNORECASE)
        analisis_text = analisis_match.group(1).strip() if analisis_match else "Análisis no provisto por el modelo."
        
        json_str = None
        if '```json' in content:
            try:
                json_str = content.split('```json')[1].split('```')[0].strip()
            except IndexError:
                pass
        
        if not json_str:
            jm = re.search(r'\{[^{}]+\}', content, re.DOTALL)
            if jm: json_str = jm.group()
            
        if not json_str:
            jm2 = re.search(r'\{.*\}', content, re.DOTALL)
            if jm2: json_str = jm2.group()

        logger.info("========== DICTAMEN DE EL ARQUITECTO ==========")
        print(f"\n{analisis_text}\n")
        logger.info("===============================================")
            
        if not json_str:
            logger.error("Raw Output:\n" + content)
            raise ValueError("No se encontró un bloque JSON válido.")
            
        nuevo_json = json.loads(json_str)

        try:
            with open(_PARAMS_PATH, "r") as f:
                params_actuales = json.load(f)
        except Exception:
            params_actuales = {}

        for k, v in nuevo_json.items():
            params_actuales[k] = v

        params_actuales["calibrated_at"] = datetime.now(timezone.utc).isoformat()
        params_actuales["data_points"] = stats["total"]
        params_actuales["architect_analysis"] = analisis_text
        params_actuales["long_wr"] = round(stats["long_wr"], 1)
        params_actuales["short_wr"] = round(stats["short_wr"], 1)

        # Store Gemma4 reasoning for dashboard display
        params_actuales["gemma4_reasoning"] = analisis_text[:500]

        with open(_PARAMS_PATH, "w") as f:
            json.dump(params_actuales, f, indent=2)

        logger.info(f"El Soldado ha sido re-parametrizado correctamente. Archivo guardado en {_PARAMS_PATH}")

        # ── Auto-Rotation: replace dead tokens ──────────────
        try:
            from app.token_rotator import rotate_dead_tokens
            rotation_result = rotate_dead_tokens()
            if rotation_result.get("rotated"):
                logger.info("🔄 Token rotation completed: removed %s, added %s",
                            rotation_result["removed"], rotation_result["added"])
                # Reload tokens in config module
                try:
                    from app import config as _cfg
                    _cfg.TOKENS = _cfg.load_active_tokens()
                    _cfg.TRADING_TOKENS = _cfg.load_trading_tokens()
                    logger.info("📋 Token lists reloaded: %d active, %d trading",
                                len(_cfg.TOKENS), len(_cfg.TRADING_TOKENS))
                except Exception as _reload_err:
                    logger.warning("Could not reload tokens: %s", _reload_err)
        except Exception as rot_err:
            logger.warning("Token rotation failed: %s", rot_err)

    except Exception as e:
        logger.error(f"Falla crítica en el Cerebro Estratégico (Ollama/Gemma4): {e}")


if __name__ == "__main__":
    evaluate_and_route()

