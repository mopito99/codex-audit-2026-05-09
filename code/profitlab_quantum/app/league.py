"""
League System — Adaptive Risk Management (Gemma4-designed, reviewed by Antigravity)
==================================================================================
Dynamically adjusts leverage and position sizing based on bot performance.
Better WR + Sharpe = higher league = more aggressive trading permitted.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text


# League definitions: (name, emoji, min_wr, min_sharpe, max_leverage, position_pct)
LEAGUES = [
    ("Leyenda",  "👑", 70, 1.5, 25, 0.35),
    ("Diamante", "💎", 65, 1.0, 20, 0.30),
    ("Oro",      "🥇", 55, 0.5, 15, 0.25),
    ("Plata",    "🥈", 40, 0.0, 10, 0.20),
    ("Bronce",   "🥉",  0, -99, 5,  0.15),
]


def compute_league(db: Any) -> dict[str, Any]:
    """Compute current league from last 50 realized trades.
    
    Returns dict with: league, emoji, win_rate, sharpe, max_leverage, position_pct
    """
    try:
        rows = db.execute(text("""
            SELECT pnl_usd FROM paper_trades
            WHERE pnl_usd IS NOT NULL AND pnl_usd != 0
            ORDER BY timestamp DESC
            LIMIT 50
        """)).fetchall()
    except Exception:
        rows = []

    if len(rows) < 5:
        # Not enough data — default to Plata
        return {
            "league": "Plata", "emoji": "🥈",
            "win_rate": 0.0, "sharpe": 0.0,
            "max_leverage": 10, "position_pct": 0.20,
            "trades_counted": len(rows),
        }

    pnls = [float(r.pnl_usd) for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    win_rate = (wins / total) * 100

    # Sharpe ratio (annualized, assuming ~288 trades/day on 5m candles)
    avg_pnl = sum(pnls) / total
    std_pnl = math.sqrt(sum((p - avg_pnl) ** 2 for p in pnls) / max(total - 1, 1))
    sharpe = (avg_pnl / (std_pnl + 1e-10)) * math.sqrt(252)

    # Determine league (ordered from highest to lowest)
    league_name, emoji, max_lev, pos_pct = "Bronce", "🥉", 5, 0.15
    for name, emj, min_wr, min_sh, lev, pct in LEAGUES:
        if win_rate >= min_wr and sharpe >= min_sh:
            league_name, emoji, max_lev, pos_pct = name, emj, lev, pct
            break

    return {
        "league": league_name,
        "emoji": emoji,
        "win_rate": round(win_rate, 1),
        "sharpe": round(sharpe, 2),
        "max_leverage": max_lev,
        "position_pct": pos_pct,
        "trades_counted": total,
    }
