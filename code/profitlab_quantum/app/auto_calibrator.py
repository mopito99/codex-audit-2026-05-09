"""
Auto-Calibrator v2 — Fully Autonomous Gemma4-Driven Bot Brain
=============================================================
The bot analyzes its own performance every 2h and decides:
- Whether to trade at all
- Whether SHORTs are allowed
- Night mode (full/long_only/off)
- Leverage, TP sizes, guard thresholds
- Max concurrent positions

Zero human intervention. Gemma4 decides everything.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

logger = logging.getLogger(__name__)

_PARAMS_PATH = str(Path(__file__).resolve().parent.parent / "data" / "auto_params.json")

DEFAULT_PARAMS = {
    # Operational decisions
    "trading_enabled": True,
    "shorts_enabled": True,
    "night_mode": "full",       # "full" | "long_only" | "off" (22-06 UTC)
    "max_positions": 8,
    # Guard thresholds
    "short_btc_threshold": -0.3,
    "long_btc_block": -1.5,
    # TP management
    "tp0_close_pct": 0.40,
    "tp1_close_pct": 0.50,
    # Metadata
    "calibrated_at": None,
    "data_points": 0,
    "gemma4_reasoning": "",
}

CALIBRATION_PROMPT = """Eres el cerebro autonomo de un bot de trading crypto con 20x leverage en small-caps BingX. Tu trabajo: analizar rendimiento y decidir TODOS los parametros operacionales.

DATOS REALES (ultimos trades):
- Total: {total} trades
- LONG: {long_n} trades, WR={long_wr:.0f}%, AvgPnL=${long_avg:.2f}
- SHORT: {short_n} trades, WR={short_wr:.0f}%, AvgPnL=${short_avg:.2f}
- Runners CLOSE: {close_n} trades, {close_wins} wins, {close_losses} losses (loss ratio {runner_loss_pct:.0f}%)
- PnL sesion dia (06-22UTC): ${day_pnl:.2f}
- PnL sesion noche (22-06UTC): ${night_pnl:.2f}
- Total PnL: ${total_pnl:.2f}
- Drawdown actual: {dd_pct:.1f}%

DECIDE estos parametros:
1. trading_enabled: true/false (false si drawdown>15% o todo pierde)
2. shorts_enabled: true/false (false si SHORT WR<35%)
3. night_mode: "full"/"long_only"/"off" (off si noche pierde, long_only si solo longs funcionan de noche)
4. max_positions: 3-10 (reducir si perdiendo, aumentar si ganando)
5. short_btc_threshold: -2.0 a 0.5 (BTC momentum minimo para shorts)
6. long_btc_block: -3.0 a -0.5 (bloquear longs si BTC cae mas)
7. tp0_close_pct: 0.20 a 0.60 (cuanto cerrar en TP0)
8. tp1_close_pct: 0.30 a 0.70 (cuanto cerrar en TP1)

PRIORIDAD: proteger capital > maximizar ganancias. Si algo no funciona, desactivalo.

Responde SOLO JSON:
{{"trading_enabled":true,"shorts_enabled":true,"night_mode":"full","max_positions":6,"short_btc_threshold":-0.3,"long_btc_block":-1.5,"tp0_close_pct":0.40,"tp1_close_pct":0.50,"reasoning":"explicacion"}}"""


def calibrate(db: Any) -> dict[str, Any]:
    """Gemma4 analyzes performance and decides ALL operational parameters."""
    params = dict(DEFAULT_PARAMS)

    try:
        rows = db.execute(text("""
            SELECT event, action, pnl_usd,
                   EXTRACT(HOUR FROM timestamp)::int as hour_utc
            FROM paper_trades
            WHERE pnl_usd IS NOT NULL AND pnl_usd != 0
            ORDER BY timestamp DESC LIMIT 200
        """)).fetchall()
    except Exception as e:
        logger.warning(f"Calibrator DB error: {e}")
        _save(params)
        return params

    if len(rows) < 10:
        logger.info(f"Calibrator: {len(rows)} trades, need 10+. Defaults.")
        params["data_points"] = len(rows)
        _save(params)
        return params

    # Build stats
    long_pnls = [float(r.pnl_usd) for r in rows if r.action == "LONG"]
    short_pnls = [float(r.pnl_usd) for r in rows if r.action == "SHORT"]
    close_rows = [r for r in rows if r.event == "CLOSE"]
    close_wins = sum(1 for r in close_rows if float(r.pnl_usd) > 0)
    close_losses = sum(1 for r in close_rows if float(r.pnl_usd) < 0)

    # Day vs Night PnL
    day_pnl = sum(float(r.pnl_usd) for r in rows if 6 <= r.hour_utc < 22)
    night_pnl = sum(float(r.pnl_usd) for r in rows if r.hour_utc >= 22 or r.hour_utc < 6)
    total_pnl = sum(float(r.pnl_usd) for r in rows)

    # Drawdown estimate (based on starting balance, not PnL-from-zero)
    STARTING_BALANCE = 1000.0  # simulated balance
    cumulative = 0.0
    peak_equity = STARTING_BALANCE
    max_dd_pct = 0.0
    for r in reversed(list(rows)):
        cumulative += float(r.pnl_usd)
        equity = STARTING_BALANCE + cumulative
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            dd = ((peak_equity - equity) / peak_equity) * 100
            max_dd_pct = max(max_dd_pct, dd)
    dd_pct = min(max_dd_pct, 100.0)  # cap at 100% max

    stats = {
        "total": len(rows),
        "long_n": len(long_pnls), "long_wr": _wr(long_pnls),
        "long_avg": sum(long_pnls) / max(len(long_pnls), 1),
        "short_n": len(short_pnls), "short_wr": _wr(short_pnls),
        "short_avg": sum(short_pnls) / max(len(short_pnls), 1),
        "close_n": len(close_rows), "close_wins": close_wins, "close_losses": close_losses,
        "runner_loss_pct": (close_losses / max(len(close_rows), 1)) * 100,
        "day_pnl": day_pnl, "night_pnl": night_pnl,
        "total_pnl": total_pnl, "dd_pct": dd_pct,
    }

    prompt = CALIBRATION_PROMPT.format(**stats)

    # Ask Gemma4
    try:
        import re
        resp = requests.post("http://localhost:11434/api/generate", json={
            "model": "gemma4:latest",
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_predict": 800},
        }, timeout=180)

        rdata = resp.json()
        content = rdata.get("response", "") or ""

        json_match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
        if json_match:
            gp = json.loads(json_match.group())
            params["trading_enabled"] = bool(gp.get("trading_enabled", True))
            params["shorts_enabled"] = bool(gp.get("shorts_enabled", True))
            params["night_mode"] = str(gp.get("night_mode", "full"))
            params["max_positions"] = max(2, min(10, int(gp.get("max_positions", 6))))
            params["short_btc_threshold"] = max(-2.0, min(0.5, float(gp.get("short_btc_threshold", -0.3))))
            params["long_btc_block"] = max(-3.0, min(-0.5, float(gp.get("long_btc_block", -1.5))))
            params["tp0_close_pct"] = max(0.20, min(0.60, float(gp.get("tp0_close_pct", 0.40))))
            params["tp1_close_pct"] = max(0.30, min(0.70, float(gp.get("tp1_close_pct", 0.50))))
            params["gemma4_reasoning"] = gp.get("reasoning", "")
            logger.info(f"Gemma4 brain: {gp}")
        else:
            logger.warning(f"Gemma4 no JSON. Raw: {content[:200]}")
    except Exception as e:
        logger.warning(f"Gemma4 brain failed: {e}")

    params["calibrated_at"] = datetime.now(timezone.utc).isoformat()
    params["data_points"] = len(rows)
    params["long_wr"] = round(_wr(long_pnls), 1)
    params["short_wr"] = round(_wr(short_pnls), 1)
    params["day_pnl"] = round(day_pnl, 2)
    params["night_pnl"] = round(night_pnl, 2)

    _save(params)
    return params


def load_params() -> dict[str, Any]:
    try:
        with open(_PARAMS_PATH) as f:
            return json.load(f)
    except Exception:
        return dict(DEFAULT_PARAMS)


def _save(params: dict) -> None:
    try:
        with open(_PARAMS_PATH, "w") as f:
            json.dump(params, f, indent=2)
    except Exception as e:
        logger.warning(f"Save failed: {e}")


def _wr(pnls: list[float]) -> float:
    if not pnls: return 0.0
    return (sum(1 for p in pnls if p > 0) / len(pnls)) * 100
