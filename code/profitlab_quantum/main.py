from __future__ import annotations

import asyncio
import logging
import pandas as pd
import os
import sys
import fcntl
import time
from typing import Any
from app.config import (
    TOKENS,
    TRADING_TOKENS,
    TIMEFRAME,
    INITIAL_CAPITAL,
    USE_WS_FEED,
    USE_ORDERBOOK,
    ORDERBOOK_LIMIT,
    BINGX_FEE_TAKER,
    BINGX_SLIPPAGE_BPS,
    PPO_CHUNK_UPDATE_EVERY_HOURS,
    get_token_tier,
    get_tier_config,
    get_tier_slippage,
    get_tier_leverage,
)
from app.data.bingx import BingXReader
from app.data.bingx_ws import BingXSwapWebSocket
from app.engine import QuantumEngine
from app.db import get_db, engine as db_engine
from app.symbol_health import get_symbol_health_monitor
from app.smallcap_guards import check_token_killswitch, check_session_filter
from app.auto_calibrator import load_params as load_auto_params
from sqlalchemy import text
import json
from pathlib import Path


def _parse_ob_levels(side_data: list[list[Any]] | None, top_n: int) -> list[tuple[float, float]]:
    """Parse raw orderbook side into [(price, size), ...] tuples."""
    out: list[tuple[float, float]] = []
    for lvl in (side_data or [])[:top_n]:
        try:
            px, sz = float(lvl[0]), float(lvl[1])
            if px > 0 and sz >= 0:
                out.append((px, sz))
        except Exception:
            continue
    return out


def _compute_mid_spread(
    bids: list[tuple[float, float]], asks: list[tuple[float, float]],
) -> tuple[float | None, float | None]:
    """Return (mid, spread_bps) or (None, None)."""
    if not bids or not asks:
        return None, None
    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_bid <= 0 or best_ask <= 0:
        return None, None
    mid = 0.5 * (best_bid + best_ask)
    spread_bps = ((best_ask - best_bid) / mid) * 10000.0 if mid > 0 else None
    return mid, spread_bps


def _compute_microstructure_from_depth(depth: dict[str, Any], *, top_n: int = 10) -> dict[str, Any]:
    """Derive lightweight institutional microstructure features from an orderbook snapshot."""
    bids = _parse_ob_levels(depth.get("bids"), top_n)
    asks = _parse_ob_levels(depth.get("asks"), top_n)
    mid, spread_bps = _compute_mid_spread(bids, asks)

    bid_usd = float(sum(px * sz for px, sz in bids)) if bids else 0.0
    ask_usd = float(sum(px * sz for px, sz in asks)) if asks else 0.0
    denom = bid_usd + ask_usd
    imbalance = float((bid_usd - ask_usd) / denom) if denom > 0 else 0.0

    return {
        "mid": float(mid) if mid is not None else None,
        "spread_bps": float(spread_bps) if spread_bps is not None else None,
        "bid_depth_usd": bid_usd, "ask_depth_usd": ask_usd,
        "imbalance": imbalance, "top_n": top_n,
        "ts": int(depth.get("T") or 0),
    }


def _apply_slippage(price: float, side: str, *, bps: float) -> float:
    """Apply a simple slippage model in bps.

    For entry/exit fills:
    - LONG entry (buy): worse price (up)
    - LONG exit (sell): worse price (down)
    - SHORT entry (sell): worse price (down)
    - SHORT exit (buy): worse price (up)
    """
    if price <= 0:
        return price
    slip = float(bps) / 10000.0
    s = (side or "").upper()
    if s in ("LONG_ENTRY", "SHORT_EXIT"):
        return float(price) * (1.0 + slip)
    if s in ("LONG_EXIT", "SHORT_ENTRY"):
        return float(price) * (1.0 - slip)
    return float(price)


def _write_heartbeat(payload: dict[str, Any]) -> None:
    """Write a small heartbeat file for external watchdogs (systemd/cron/uptime checks)."""
    try:
        hb_dir = Path("/tmp/profitlab_quantum")
        hb_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = hb_dir / "heartbeat.json.tmp"
        final_path = hb_dir / "heartbeat.json"
        tmp_path.write_text(json.dumps(payload, sort_keys=True))
        tmp_path.replace(final_path)
    except Exception:
        pass


def acquire_single_instance_lock(lock_path: str) -> Any:
    """Prevent running multiple bot instances concurrently."""
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another ProfitLab Quantum bot instance is already running (lock: {lock_path}).")
        sys.exit(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("quantum.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Quantum.Main")

# SQL constant for paper_trades INSERT (used by TP1, SL/TP exit, open, BE)
_SQL_INSERT_TRADE = text("""
    INSERT INTO paper_trades (
        timestamp, symbol, action, price, size, margin, leverage, reason,
        event, entry_price, exit_price, pnl_usd, sl, tp
    )
    VALUES (
        :timestamp, :symbol, :action, :price, :size, :margin, :leverage, :reason,
        :event, :entry_price, :exit_price, :pnl_usd, :sl, :tp
    )
""")


# ── Position management helpers (extracted for readability) ────────


def _handle_tp0_partial(
    db: Any, engine_instance: Any, token: str,
    current_price: float, pos_row: Any,
) -> dict[str, Any] | None:
    """Handle TP0 partial close (40% at +1.5%) + move SL to breakeven.

    TP0 is the safety net: locks in a small profit early and protects
    the rest of the position by moving SL to entry price (breakeven).
    The PPO agent receives a positive reward signal for reaching TP0,
    teaching it what a "good entry" looks like.
    """
    side = str(pos_row.side)
    tp0_price = float(pos_row.tp0_price) if hasattr(pos_row, 'tp0_price') and pos_row.tp0_price is not None else None
    tp0_hit = bool(pos_row.tp0_hit) if hasattr(pos_row, 'tp0_hit') and pos_row.tp0_hit is not None else False

    if tp0_hit or tp0_price is None:
        return None

    hit_tp0 = ((side == "LONG" and current_price >= tp0_price) or
               (side == "SHORT" and current_price <= tp0_price))
    if not hit_tp0:
        return None

    entry_price = float(pos_row.entry_price)
    qty = float(pos_row.qty)
    notional_usd = float(pos_row.notional_usd)
    tp = float(pos_row.tp) if pos_row.tp is not None else None

    from app.auto_calibrator import load_params as _load_cal
    _cal = _load_cal()
    close_pct = _cal.get("tp0_close_pct", 0.40)
    close_qty = qty * close_pct
    close_notional = notional_usd * close_pct

    if side == "LONG":
        exit_fill = _apply_slippage(float(tp0_price), "LONG_EXIT", bps=float(BINGX_SLIPPAGE_BPS))
        pnl_partial = (exit_fill - entry_price) * close_qty
    else:
        exit_fill = _apply_slippage(float(tp0_price), "SHORT_EXIT", bps=float(BINGX_SLIPPAGE_BPS))
        pnl_partial = (entry_price - exit_fill) * close_qty

    fee_open = close_notional * float(BINGX_FEE_TAKER)
    fee_close = close_notional * float(BINGX_FEE_TAKER)
    pnl_partial = float(pnl_partial) - float(fee_open) - float(fee_close)

    new_balance = float(engine_instance.portfolio_value) + float(pnl_partial)
    engine_instance.portfolio_value = new_balance

    # Move SL to pure breakeven (entry price)
    new_sl = entry_price
    remaining_qty = qty - close_qty
    remaining_notional = notional_usd - close_notional

    db.execute(
        text("""
            UPDATE paper_positions
            SET qty = :qty, notional_usd = :notional, tp0_hit = TRUE, sl = :sl
            WHERE symbol = :symbol
        """),
        {"qty": float(remaining_qty), "notional": float(remaining_notional),
         "sl": float(new_sl), "symbol": token},
    )

    db.execute(
        _SQL_INSERT_TRADE,
        {
            "timestamp": pd.Timestamp.now(), "symbol": token, "action": side,
            "price": float(tp0_price), "size": float(close_notional),
            "margin": float(pos_row.margin_usd) * close_pct,
            "leverage": float(pos_row.leverage),
            "reason": "TP0 Partial Close (40%) + SL→BE", "event": "TP0",
            "entry_price": float(entry_price), "exit_price": float(exit_fill),
            "pnl_usd": float(pnl_partial), "sl": float(new_sl),
            "tp": float(tp) if tp is not None else None,
        },
    )
    db.commit()

    # PPO reward: reaching TP0 = good entry quality
    _send_trade_ppo_reward(engine_instance, token, "TP0", pnl_partial, float(pos_row.margin_usd) * close_pct)

    logger.info(
        f"TP0 HIT [{token}]: Closed 40% @ {tp0_price:.4f} | "
        f"PnL: ${pnl_partial:.2f} | SL moved to BE: {new_sl:.4f}"
    )

    return {
        "qty": remaining_qty,
        "notional_usd": remaining_notional,
        "sl": new_sl,
        "tp0_hit": True,
    }


def _handle_tp1_partial(
    db: Any, engine_instance: Any, token: str,
    current_price: float, pos_row: Any,
) -> dict[str, Any] | None:
    """Handle TP1 partial close (50% of remaining at 1:1 R:R from SL).

    TP1 fires at 1× the SL distance (1:1 risk:reward ratio), closing 40%
    of the current position and locking in profit by moving SL to +0.5%.
    """
    side = str(pos_row.side)
    tp1_price = float(pos_row.tp1_price) if hasattr(pos_row, 'tp1_price') and pos_row.tp1_price is not None else None
    tp1_hit = bool(pos_row.tp1_hit) if hasattr(pos_row, 'tp1_hit') and pos_row.tp1_hit is not None else False

    if tp1_hit or tp1_price is None:
        return None

    hit_tp1 = ((side == "LONG" and current_price >= tp1_price) or
               (side == "SHORT" and current_price <= tp1_price))
    if not hit_tp1:
        return None

    entry_price = float(pos_row.entry_price)
    qty = float(pos_row.qty)
    notional_usd = float(pos_row.notional_usd)
    tp = float(pos_row.tp) if pos_row.tp is not None else None

    from app.auto_calibrator import load_params as _load_cal
    _cal = _load_cal()
    close_pct = _cal.get("tp1_close_pct", 0.50)  # Gemma4-calibrated
    close_qty = qty * close_pct
    close_notional = notional_usd * close_pct

    if side == "LONG":
        exit_fill = _apply_slippage(float(tp1_price), "LONG_EXIT", bps=float(BINGX_SLIPPAGE_BPS))
        pnl_partial = (exit_fill - entry_price) * close_qty
    else:
        exit_fill = _apply_slippage(float(tp1_price), "SHORT_EXIT", bps=float(BINGX_SLIPPAGE_BPS))
        pnl_partial = (entry_price - exit_fill) * close_qty

    fee_open_partial = close_notional * float(BINGX_FEE_TAKER)
    fee_close_partial = close_notional * float(BINGX_FEE_TAKER)
    pnl_partial = float(pnl_partial) - float(fee_open_partial) - float(fee_close_partial)

    new_balance = float(engine_instance.portfolio_value) + float(pnl_partial)
    engine_instance.portfolio_value = new_balance

    # Lock in 0.5% profit (tighter than TP0's pure BE)
    new_sl = entry_price * 1.005 if side == "LONG" else entry_price * 0.995
    remaining_qty = qty - close_qty
    remaining_notional = notional_usd - close_notional

    db.execute(
        text("""
            UPDATE paper_positions
            SET qty = :qty, notional_usd = :notional, tp1_hit = TRUE, sl = :sl
            WHERE symbol = :symbol
        """),
        {"qty": float(remaining_qty), "notional": float(remaining_notional),
         "sl": float(new_sl), "symbol": token},
    )

    db.execute(
        _SQL_INSERT_TRADE,
        {
            "timestamp": pd.Timestamp.now(), "symbol": token, "action": side,
            "price": float(tp1_price), "size": float(close_notional),
            "margin": float(pos_row.margin_usd) * close_pct,
            "leverage": float(pos_row.leverage),
            "reason": "TP1 Partial Close (50%, 30% runner) 1:1 R:R", "event": "TP1",
            "entry_price": float(entry_price), "exit_price": float(exit_fill),
            "pnl_usd": float(pnl_partial), "sl": float(new_sl),
            "tp": float(tp) if tp is not None else None,
        },
    )
    db.commit()

    # PPO reward: reaching TP1 = solid trade
    _send_trade_ppo_reward(engine_instance, token, "TP1", pnl_partial, float(pos_row.margin_usd) * close_pct)

    logger.info(
        f"TP1 HIT [{token}]: Closed 50% remaining @ {tp1_price:.4f} | "
        f"PnL: ${pnl_partial:.2f} | SL locked at +0.5%: {new_sl:.4f}"
    )

    return {
        "qty": remaining_qty,
        "notional_usd": remaining_notional,
        "sl": new_sl,
        "tp1_hit": True,
    }


def _check_sl_tp_hit(
    side: str, current_price: float, sl: float | None, tp: float | None,
) -> str | None:
    """Return 'TP', 'SL' or None."""
    is_long = (side == "LONG")
    if tp is not None and ((is_long and current_price >= tp) or (not is_long and current_price <= tp)):
        return "TP"
    if sl is not None and ((is_long and current_price <= sl) or (not is_long and current_price >= sl)):
        return "SL"
    return None


def _compute_exit_pnl(
    side: str, entry_price: float, qty: float,
    notional_usd: float, current_price: float,
) -> tuple[float, float]:
    """Calculate exit fill, PnL after fees."""
    slip_tag = "LONG_EXIT" if side == "LONG" else "SHORT_EXIT"
    exit_fill = _apply_slippage(float(current_price), slip_tag, bps=float(BINGX_SLIPPAGE_BPS))
    raw_pnl = (exit_fill - entry_price) * qty if side == "LONG" else (entry_price - exit_fill) * qty
    notional_close = float(qty) * float(exit_fill)
    fees = float(notional_usd) * float(BINGX_FEE_TAKER) + float(notional_close) * float(BINGX_FEE_TAKER)
    return exit_fill, float(raw_pnl) - fees


def _update_equity(db: Any, engine_instance: Any, token: str, pnl_usd: float) -> None:
    """Update portfolio value and paper_equity table."""
    new_balance = float(engine_instance.portfolio_value) + float(pnl_usd)
    engine_instance.portfolio_value = new_balance

    peak_row = db.execute(
        text("SELECT balance, peak FROM paper_equity WHERE symbol = :symbol"),
        {"symbol": token},
    ).fetchone()
    prev_peak = float(peak_row.peak) if peak_row is not None else float(engine_instance.capital)

    db.execute(
        text("""
            INSERT INTO paper_equity (symbol, balance, peak, updated_at)
            VALUES (:symbol, :balance, :peak, :updated_at)
            ON CONFLICT (symbol) DO UPDATE SET
                balance = EXCLUDED.balance, peak = EXCLUDED.peak, updated_at = EXCLUDED.updated_at
        """),
        {"symbol": token, "balance": new_balance,
         "peak": max(prev_peak, new_balance), "updated_at": pd.Timestamp.now()},
    )


def _send_trade_ppo_reward(
    engine_instance: Any, token: str, exit_reason: str,
    pnl_usd: float, margin_usd: float,
) -> None:
    """Send PPO reward for trade events (TP0/TP1/TP2/SL).

    Graduated reward scale teaches the agent what a good entry looks like:
    - TP0 (+1.5%): entry quality signal — 'you picked the right direction'
    - TP1 (1:1 R:R): solid trade — 'momentum continued as expected'
    - TP2 (2:1 R:R): excellent runner — 'you caught a real move'
    - SL at BE: neutral — 'entry was ok but no follow-through'
    - SL with loss: negative — 'bad entry or timing'
    """
    try:
        pnl_pct = float(pnl_usd) / float(margin_usd) if margin_usd else 0

        if exit_reason == "TP0":
            # [ANIMAL MODE] Recompensa justa por lograr evadir la trampa del ruido inicial
            trade_reward = 1.0 + pnl_pct * 15.0
        elif exit_reason == "TP1":
            # [ANIMAL MODE] Fuerte empujón positivo para consolidaciones seguras medias
            trade_reward = 7.0 + pnl_pct * 30.0
        elif exit_reason in ("TP", "TP2"):
            # [v3] Recompensa proporcional por TP2 (buenos trades, no lotería)
            trade_reward = 10.0 + pnl_pct * 50.0
        elif exit_reason == "SL":
            if margin_usd > 0 and abs(pnl_pct) < 0.01:
                # Breakeven no aporta ni quita valor (evita estancamiento)
                trade_reward = 0.0
            else:
                # [v3] SL penalty calibrado: castiga malas entradas sin paralizar
                trade_reward = -5.0 + pnl_pct * 50.0
        else:
            trade_reward = 0.0

        logger.info("PPO REWARD [%s]: %s %+.2f (pnl_pct=%.3f)", exit_reason, token, trade_reward, pnl_pct)

        if (hasattr(engine_instance, "prev_state")
                and engine_instance.prev_state is not None
                and hasattr(engine_instance.agent, "remember")):
            engine_instance.agent.remember(
                engine_instance.prev_state, engine_instance.prev_action or 0,
                float(trade_reward), True, engine_instance.prev_log_prob,
                engine_instance.prev_value, int(time.time() * 1000))
    except Exception as e:
        logger.debug("Failed to send trade reward: %s", e)


def _handle_sl_tp_exit(
    db: Any, engine_instance: Any, token: str, current_price: float,
    pos_row: Any, side: str, entry_price: float, qty: float,
    notional_usd: float, sl: float | None, tp: float | None,
) -> bool:
    """Check and execute SL/TP exit. Returns True if position was closed."""
    exit_reason = _check_sl_tp_hit(side, current_price, sl, tp)
    if exit_reason is None:
        return False

    exit_fill, pnl_usd = _compute_exit_pnl(side, entry_price, qty, notional_usd, current_price)

    db.execute(text("DELETE FROM paper_positions WHERE symbol = :symbol"), {"symbol": token})

    if exit_reason == "SL":
        try:
            engine_instance._cooldown_until_ts_ms = int(time.time() * 1000) + 30 * 60 * 1000
            logger.info("Cooldown activated for %s: 15 min after SL", token)
        except Exception:
            pass

    _update_equity(db, engine_instance, token, pnl_usd)

    db.execute(
        _SQL_INSERT_TRADE,
        {
            "timestamp": pd.Timestamp.now(), "symbol": token, "action": side,
            "price": float(current_price), "size": float(notional_usd),
            "margin": float(pos_row.margin_usd), "leverage": float(pos_row.leverage),
            "reason": f"Auto close ({exit_reason})", "event": "CLOSE",
            "entry_price": float(entry_price), "exit_price": float(exit_fill),
            "pnl_usd": float(pnl_usd),
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
        },
    )
    db.commit()

    _send_trade_ppo_reward(engine_instance, token, exit_reason, pnl_usd, pos_row.margin_usd)
    get_symbol_health_monitor().force_refresh()
    return True


def _compute_be_sl(
    side: str, entry_price: float, current_price: float, sl: float | None,
) -> tuple[float, float | None]:
    """Return (roi, new_sl) if BE should activate, else (roi, None)."""
    if entry_price <= 0:
        return 0.0, None
    is_long = (side == "LONG")
    roi = ((current_price - entry_price) / entry_price) if is_long else ((entry_price - current_price) / entry_price)
    if roi < 0.015:   # [v3] Activar BE temprano para proteger ganancia
        return roi, None
    target = entry_price * (1.003 if is_long else 0.997)  # Lock in +0.3% profit (covers fees)
    sl_ok = (sl is None or (target > sl if is_long else target < sl))
    px_ok = (target < current_price if is_long else target > current_price)
    return roi, (target if sl_ok and px_ok else None)


def _handle_breakeven(
    db: Any, token: str, current_price: float, side: str,
    entry_price: float, sl: float | None, tp: float | None,
    notional_usd: float, margin_usd: float, leverage: float,
) -> None:
    """Check and activate break-even SL move when ROI > 1.0%."""
    roi, new_sl = _compute_be_sl(side, entry_price, current_price, sl)
    if new_sl is None:
        return

    logger.info("BE ACTIVATED [%s]: ROI=%.2f%% | Moved SL to %.4f", token, roi * 100, new_sl)
    db.execute(
        text("UPDATE paper_positions SET sl = :sl WHERE symbol = :symbol"),
        {"sl": float(new_sl), "symbol": token},
    )
    db.execute(
        text("""
            INSERT INTO paper_trades (
                timestamp, symbol, action, price, size, margin, leverage, reason,
                event, entry_price, sl, tp
            ) VALUES (
                :timestamp, :symbol, :action, :price, :size, :margin, :leverage, :reason,
                :event, :entry_price, :sl, :tp
            )
        """),
        {
            "timestamp": pd.Timestamp.now(), "symbol": token, "action": side,
            "price": float(current_price), "size": float(notional_usd),
            "margin": float(margin_usd), "leverage": float(leverage),
            "reason": "Break Even Trigger (ROI > 0.5%)", "event": "BE",
            "entry_price": float(entry_price), "sl": float(new_sl),
            "tp": float(tp) if tp is not None else None,
        },
    )
    db.commit()


def _handle_open_position(
    db: Any, token: str, action_str: str,
    position_size: float, info: dict[str, Any], current_price: float,
) -> None:
    """Open a new paper trading position with TP0/TP1/TP2 setup.

    TP structure:
    - TP0: +1.5% from entry → close 20%, SL→breakeven (safety net)
    - TP1: 1×SL distance from entry (1:1 R:R) → close 50% remaining (30% runner)
    - TP2: Engine structural TP (~2:1 R:R) → close 100% remaining
    """
    original_notional = float(info.get("risk", {}).get("notional_usd", position_size) or position_size)
    size_ratio = (float(position_size) / original_notional) if original_notional > 0 else 1.0
    margin_usd = float(info.get("risk", {}).get("margin_usd", 0.0) or 0.0) * size_ratio
    leverage = float(info.get("risk", {}).get("leverage", 1.0) or 1.0)
    sl = info.get("orders", {}).get("sl")
    tp = info.get("orders", {}).get("tp")  # This is TP2 (structural, ~2:1 R:R)

    if action_str == "LONG":
        entry_fill = _apply_slippage(float(current_price), "LONG_ENTRY", bps=float(BINGX_SLIPPAGE_BPS))
    else:
        entry_fill = _apply_slippage(float(current_price), "SHORT_ENTRY", bps=float(BINGX_SLIPPAGE_BPS))

    qty = (float(position_size) / entry_fill) if entry_fill else 0.0

    # TP0: +1.5% from entry [v3] Safety net realista
    TP0_PCT = 0.015
    if action_str == "LONG":
        tp0_price = entry_fill * (1 + TP0_PCT)
    else:
        tp0_price = entry_fill * (1 - TP0_PCT)

    # TP1: 1:1 R:R from SL distance (intelligent, adapts to market structure)
    if sl is not None and float(sl) > 0:
        sl_distance = abs(entry_fill - float(sl))
        if action_str == "LONG":
            tp1_price = entry_fill + sl_distance  # 1:1 R:R
        else:
            tp1_price = entry_fill - sl_distance  # 1:1 R:R
    else:
        # Fallback: +2% if no SL available
        if action_str == "LONG":
            tp1_price = entry_fill * 1.02
        else:
            tp1_price = entry_fill * 0.98

    logger.info(
        f"OPEN [{token}]: {action_str} | Notional: ${position_size:.2f} | "
        f"Margin: ${margin_usd:.2f} | Lev: {leverage:.2f}x | SL: {sl} | "
        f"TP0: {tp0_price:.4f} (+1.5%) | TP1: {tp1_price:.4f} (1:1 R:R) | "
        f"TP2: {tp} (structural) | Price: {entry_fill} "
        f"(slip_bps={BINGX_SLIPPAGE_BPS}) | Fee(taker)={BINGX_FEE_TAKER}"
    )

    db.execute(
        text("""
            INSERT INTO paper_positions (
                symbol, side, entry_price, notional_usd, margin_usd, leverage,
                qty, sl, tp, tp0_price, tp0_hit, tp1_price, tp1_hit, open_time
            )
            VALUES (
                :symbol, :side, :entry_price, :notional_usd, :margin_usd, :leverage,
                :qty, :sl, :tp, :tp0_price, FALSE, :tp1_price, FALSE, :open_time
            )
            ON CONFLICT (symbol) DO UPDATE SET
                side = EXCLUDED.side,
                entry_price = EXCLUDED.entry_price,
                notional_usd = EXCLUDED.notional_usd,
                margin_usd = EXCLUDED.margin_usd,
                leverage = EXCLUDED.leverage,
                qty = EXCLUDED.qty,
                sl = EXCLUDED.sl,
                tp = EXCLUDED.tp,
                tp0_price = EXCLUDED.tp0_price,
                tp0_hit = FALSE,
                tp1_price = EXCLUDED.tp1_price,
                tp1_hit = FALSE,
                open_time = EXCLUDED.open_time
        """),
        {
            "symbol": token, "side": action_str,
            "entry_price": float(entry_fill),
            "notional_usd": float(position_size),
            "margin_usd": float(margin_usd),
            "leverage": float(leverage),
            "qty": float(qty),
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "tp0_price": float(tp0_price),
            "tp1_price": float(tp1_price),
            "open_time": pd.Timestamp.now(),
        },
    )

    db.execute(
        _SQL_INSERT_TRADE,
        {
            "timestamp": pd.Timestamp.now(), "symbol": token,
            "action": action_str,
            "price": float(entry_fill),
            "size": float(position_size),
            "margin": float(margin_usd),
            "leverage": float(leverage),
            "reason": "Quantum Agent Signal", "event": "OPEN",
            "entry_price": float(entry_fill),
            "exit_price": None, "pnl_usd": None,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
        },
    )
    db.commit()


class _BotState:
    """Shared mutable state for the trading bot event loops."""
    __slots__ = (
        "bingx", "engines", "last_kline_start_ms", "last_processed_at_utc",
        "live_prices", "ws_last_event_monotonic",
    )

    def __init__(self, bingx: BingXReader, engines: dict[str, QuantumEngine]) -> None:
        self.bingx = bingx
        self.engines = engines
        self.last_kline_start_ms: dict[str, int | None] = dict.fromkeys(TOKENS, None)
        self.last_processed_at_utc: dict[str, str | None] = dict.fromkeys(TOKENS, None)
        self.live_prices: dict[str, float] = dict.fromkeys(TOKENS, 0.0)
        self.ws_last_event_monotonic: float | None = None


def _init_engines() -> dict[str, QuantumEngine]:
    """Create one QuantumEngine per token; trading tokens get capital, train-only get $0."""
    capital_per_token = INITIAL_CAPITAL / len(TRADING_TOKENS)
    engines = {
        token: QuantumEngine(
            initial_capital=capital_per_token if token in TRADING_TOKENS else 0.0,
            symbol=token,
        )
        for token in TOKENS
    }
    logger.info("Initialized %d engines with $%.2f each.", len(engines), capital_per_token)
    train_only = [t for t in TOKENS if t not in TRADING_TOKENS]
    logger.info("TRADING (%d): %s", len(TRADING_TOKENS), TRADING_TOKENS)
    logger.info("TRAIN-ONLY (%d): %s", len(train_only), train_only)
    return engines


def _load_equity(engines: dict[str, QuantumEngine]) -> None:
    """Load persisted equity per symbol so CPPI/drawdown survives restarts."""
    db = get_db()
    try:
        rows = db.execute(text("SELECT symbol, balance, peak FROM paper_equity")).fetchall()
        equity_map = {r.symbol: float(r.balance) for r in rows}
        for token, eng in engines.items():
            if token in equity_map:
                eng.portfolio_value = equity_map[token]
    except Exception as e:
        logger.warning("Equity load skipped: %s", e)
    finally:
        db.close()


def _build_training_info(engine_instance: Any) -> dict[str, Any]:
    """Build training_status dict for heartbeat."""
    last_train_ms = getattr(engine_instance, "_last_train_ts_ms", None)
    if not last_train_ms:
        return {"last_training": None, "next_training": pd.Timestamp.utcnow().isoformat(),
                "status": "idle", "phase": "idle"}
    last_dt = pd.Timestamp(last_train_ms, unit='ms', tz='UTC')
    next_dt = last_dt + pd.Timedelta(hours=float(PPO_CHUNK_UPDATE_EVERY_HOURS))
    return {"last_training": last_dt.isoformat(), "next_training": next_dt.isoformat(),
            "status": "idle", "phase": "idle"}


def _heartbeat_payload(state: _BotState) -> dict[str, Any]:
    """Build heartbeat payload from current bot state."""
    age_s = None
    if state.ws_last_event_monotonic is not None:
        age_s = float(time.monotonic() - state.ws_last_event_monotonic)

    ms, training_info = {}, {}
    if state.engines:
        first = next(iter(state.engines.values()))
        try:
            ms = first.market_context.get_status().__dict__
        except Exception:
            pass
        training_info = _build_training_info(first)

    return {
        "pid": os.getpid(), "ts_utc": pd.Timestamp.utcnow().isoformat(),
        "timeframe": str(TIMEFRAME), "use_ws_feed": bool(USE_WS_FEED),
        "use_orderbook": bool(USE_ORDERBOOK), "ws_last_event_age_s": age_s,
        "last_processed_at_utc": dict(state.last_processed_at_utc),
        "live_prices": dict(state.live_prices),
        "market_status": ms, "training_status": training_info,
    }


def _manage_open_position(
    db: Any, engine_instance: Any, token: str,
    current_price: float, pos_row: Any,
) -> None:
    """Run TP0, TP1, SL/TP, and BE checks on an existing position.

    Order: TP0 (safety net) → TP1 (1:1 R:R) → SL/TP2 (final) → BE (trailing).
    Each partial close updates qty/notional/sl for subsequent checks.
    """
    side = str(pos_row.side)
    entry_price = float(pos_row.entry_price)
    qty = float(pos_row.qty)
    notional_usd = float(pos_row.notional_usd)
    sl = float(pos_row.sl) if pos_row.sl is not None else None
    tp = float(pos_row.tp) if pos_row.tp is not None else None

    # TP0: +1.5% safety net → close 20%, SL→BE
    tp0_result = _handle_tp0_partial(db, engine_instance, token, current_price, pos_row)
    if tp0_result is not None:
        qty, notional_usd, sl = tp0_result['qty'], tp0_result['notional_usd'], tp0_result['sl']

    # TP1: 1:1 R:R → close 40% of remaining, SL→+0.5%
    tp1_result = _handle_tp1_partial(db, engine_instance, token, current_price, pos_row)
    if tp1_result is not None:
        qty, notional_usd, sl = tp1_result['qty'], tp1_result['notional_usd'], tp1_result['sl']

    # TP2 (final TP) or SL: close 100% of remaining
    closed = _handle_sl_tp_exit(db, engine_instance, token, current_price, pos_row,
                                side, entry_price, qty, notional_usd, sl, tp)

    # Breakeven trailing (additional SL tightening at +1% ROI)
    if not closed:
        _handle_breakeven(db, token, current_price, side, entry_price, sl, tp,
                          notional_usd, float(pos_row.margin_usd), float(pos_row.leverage))


async def _process_symbol_on_new_candle(state: _BotState, token: str,
                                        current_forming_kline_start_ms: int | None):
    """Process a single token on candle close: position mgmt + signal + open."""
    engine_instance = state.engines[token]
    logger.info("Processing %s (new candle)...", token)

    df = await state.bingx.get_klines(token, interval=TIMEFRAME, limit=3000)
    if df is None or df.empty:
        logger.warning("No data for %s", token)
        return

    if current_forming_kline_start_ms is not None and "time" in df.columns:
        df = df[df["time"] < int(current_forming_kline_start_ms)].copy()
    if df.empty:
        logger.warning("No closed candles for %s after filtering", token)
        return

    htf_df = await state.bingx.get_klines(token, interval="1h", limit=300)
    current_price = float(df["close"].iloc[-1])
    state.live_prices[token] = current_price

    micro = None
    if USE_ORDERBOOK:
        depth = await state.bingx.get_depth(token, limit=int(ORDERBOOK_LIMIT))
        if depth:
            micro = _compute_microstructure_from_depth(depth, top_n=min(10, int(ORDERBOOK_LIMIT)))

    # 1) Position management
    db = get_db()
    try:
        pos_row = db.execute(
            text("SELECT symbol, side, entry_price, notional_usd, margin_usd, leverage, qty, sl, tp, tp0_price, tp0_hit, tp1_price, tp1_hit, open_time FROM paper_positions WHERE symbol = :symbol AND side IS NOT NULL"), {"symbol": token},
        ).fetchone()
        if pos_row is not None:
            _manage_open_position(db, engine_instance, token, current_price, pos_row)
    finally:
        db.close()

    # 2) Engine step
    action, position_size, info = engine_instance.step(df, htf_data=htf_df, symbol=token, microstructure=micro)  # type: ignore[arg-type]

    # 3) Log & open
    db = get_db()
    try:
        db.execute(
            text("INSERT INTO decision_logs (timestamp, symbol, features, agent_probs, risk_metrics) "
                 "VALUES (:timestamp, :symbol, :features, :agent_probs, :risk_metrics)"),
            {"timestamp": pd.Timestamp.utcnow(), "symbol": token,
             "features": json.dumps(info.get("features", {})),
             "agent_probs": json.dumps(info.get("probs", [])),
             "risk_metrics": json.dumps(info.get("risk", {}))},
        )
        db.commit()

        still_open = db.execute(
            text("SELECT 1 FROM paper_positions WHERE symbol = :symbol AND side IS NOT NULL"), {"symbol": token},
        ).fetchone()
        if still_open is not None:
            return

        if token not in TRADING_TOKENS:
            logger.info("TRAIN-ONLY [%s]: Signal=%s -- skipping trade", token, ['HOLD','LONG','SHORT'][action])
            return

        # ══════════════════════════════════════════════════════
        # AUTONOMOUS GATES — Gemma4 + Tier-based decisions
        # ══════════════════════════════════════════════════════
        tier = get_token_tier(token)
        tier_cfg = get_tier_config(token)
        auto_params = load_auto_params()

        # Gate 1: Gemma4 master switch (trading_enabled)
        if not auto_params.get("trading_enabled", True):
            logger.info("🧠 GEMMA4-PAUSED [%s]: trading_enabled=false — %s",
                        token, auto_params.get("gemma4_reasoning", "")[:100])
            return

        # Gate 2: Shorts disabled by Gemma4
        action_str = ["HOLD", "LONG", "SHORT"][action]
        if action_str == "SHORT" and not auto_params.get("shorts_enabled", True):
            logger.info("🧠 GEMMA4-NO-SHORT [%s]: shorts_enabled=false", token)
            return

        # Gate 3: Session filter (tier-aware: majors=24/7, memes=restricted)
        session_mode, session_mult = check_session_filter(tier=tier)
        if session_mode == "PAUSED":
            logger.info("🌙 SESSION-PAUSED [%s] (%s): tier=%s — no trading at night",
                        token, tier_cfg['label'], tier)
            return
        if session_mode == "LONG_ONLY" and action_str == "SHORT":
            logger.info("🌙 SESSION-LONG_ONLY [%s]: blocking SHORT", token)
            return

        # Gate 4: Night mode from Gemma4 auto_params
        night_mode = auto_params.get("night_mode", "full")
        if night_mode == "off" and session_mode != "FULL":
            logger.info("🧠 GEMMA4-NIGHT-OFF [%s]: night_mode=off, session=%s", token, session_mode)
            return
        if night_mode == "long_only" and action_str == "SHORT" and session_mode != "FULL":
            logger.info("🧠 GEMMA4-NIGHT-LONG [%s]: night_mode=long_only", token)
            return

        # Gate 5: Max positions from Gemma4
        max_pos = auto_params.get("max_positions", 8)
        open_count = db.execute(
            text("SELECT COUNT(*) FROM paper_positions WHERE side IS NOT NULL"),
        ).fetchone()[0]
        if open_count >= max_pos:
            logger.info("🧠 GEMMA4-MAX-POS [%s]: %d/%d positions open", token, open_count, max_pos)
            return

        # ── Symbol Health gate: graduated response ──
        health = get_symbol_health_monitor()
        if not health.can_trade(token):
            logger.info("HEALTH-PAUSED [%s]: %s -- skipping trade", token, health.get_pause_reason(token))
            return

        # ── Token Killswitch: tier-aware thresholds ──
        try:
            _ks_rows = db.execute(
                text("SELECT pnl_usd FROM paper_trades WHERE symbol = :sym AND event = 'CLOSE' AND pnl_usd IS NOT NULL ORDER BY timestamp DESC LIMIT 10"),
                {"sym": token},
            ).fetchall()
            _ks_pnls = [float(r.pnl_usd) for r in reversed(_ks_rows)]
            _ks_allow, _ks_reason = check_token_killswitch(token, _ks_pnls, tier=tier)
            if not _ks_allow:
                logger.info("🔪 KILLSWITCH [%s] (tier=%s): %s -- skipping trade", token, tier, _ks_reason)
                return
        except Exception as _ks_err:
            logger.debug("Killswitch check error: %s", _ks_err)

        size_mult = health.get_size_multiplier(token)
        # Apply session multiplier
        size_mult *= session_mult

        if action != 0 and float(position_size) > 0.0:
            adjusted_size = float(position_size) * size_mult
            if size_mult < 1.0:
                logger.info(
                    "SIZE-ADJUSTED [%s]: %.0f%% ($%.2f → $%.2f) — tier=%s, session=%s",
                    token, size_mult * 100, float(position_size), adjusted_size,
                    tier, session_mode,
                )
            logger.info(
                "✅ TRADE-APPROVED [%s]: %s | tier=%s | lev=%sx | slip=%sbps | session=%s",
                token, action_str, tier, tier_cfg['max_leverage'],
                tier_cfg['slippage_bps'], session_mode,
            )
            _handle_open_position(db, token, action_str, adjusted_size, info, current_price)
    finally:
        db.close()

    try:
        state.last_processed_at_utc[token] = pd.Timestamp.utcnow().isoformat()
    except Exception:
        pass


async def _ws_loop(state: _BotState):
    """WebSocket-driven candle loop."""
    ws = BingXSwapWebSocket(symbols=TOKENS, interval=TIMEFRAME)
    logger.info("Using WS feed: %s | interval=%s", ws.ws_url, TIMEFRAME)

    state.ws_last_event_monotonic = time.monotonic()
    stream = ws.stream()
    while True:
        try:
            evt = await asyncio.wait_for(stream.__anext__(), timeout=120)
        except asyncio.TimeoutError:
            raise RuntimeError("No WS events received for >120s")
        except StopAsyncIteration:
            raise RuntimeError("WS stream ended")

        state.ws_last_event_monotonic = time.monotonic()
        prev = state.last_kline_start_ms.get(evt.symbol)

        if prev is None or int(evt.kline_start_ms) != int(prev):
            state.last_kline_start_ms[evt.symbol] = evt.kline_start_ms
            try:
                await _process_symbol_on_new_candle(state, evt.symbol, evt.kline_start_ms)
            except Exception as e:
                logger.error("WS-driven processing error for %s: %s", evt.symbol, e)


async def _rest_polling_loop(state: _BotState):
    """REST polling fallback loop."""
    last_processed_candle: dict[str, Any] = dict.fromkeys(TOKENS, None)
    while True:
        for token in state.engines:
            logger.info("Processing %s...", token)
            df = await state.bingx.get_klines(token, interval=TIMEFRAME, limit=3000)
            if df is None or df.empty:
                logger.warning("No data for %s", token)
                continue
            try:
                latest_candle_time = df.index[-1]
            except Exception:
                continue
            if last_processed_candle.get(token) == latest_candle_time:
                continue
            last_processed_candle[token] = latest_candle_time
            await _process_symbol_on_new_candle(state, token, None)
        await asyncio.sleep(30)


async def main():
    """Bot entry point -- init, heartbeat, event loop."""
    _lock = acquire_single_instance_lock("/tmp/profitlab_quantum/bot.lock")
    logger.info("Starting Quantum Bot (Paper Trading Mode)...")

    engines = _init_engines()
    _load_equity(engines)
    state = _BotState(BingXReader(), engines)

    _write_heartbeat(_heartbeat_payload(state))

    async def _heartbeat_loop():
        while True:
            try:
                _write_heartbeat(_heartbeat_payload(state))
            except Exception as e:
                logger.error("Heartbeat loop error: %s", e)
            await asyncio.sleep(30)

    _heartbeat_task = asyncio.create_task(_heartbeat_loop())  # prevent GC

    while True:
        try:
            if USE_WS_FEED:
                try:
                    await _ws_loop(state)
                except Exception as e:
                    logger.error("WS loop failed; falling back to REST polling: %s", e)
                    await asyncio.sleep(2)
                    await _rest_polling_loop(state)
            else:
                await _rest_polling_loop(state)
        except Exception as e:
            logger.error("Main loop error: %s", e)
            await asyncio.sleep(30)

if __name__ == "__main__":
    # Create tables if not exists
    with db_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP,
                symbol VARCHAR(20),
                action VARCHAR(10),
                price FLOAT,
                size FLOAT,
                margin FLOAT,
                leverage FLOAT,
                reason TEXT
            );
        """))

        # Ensure new columns exist for already-created tables
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS margin FLOAT;"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS leverage FLOAT;"))

        # Extended trade fields for SL/TP and full-close events
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS event VARCHAR(10);"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS entry_price FLOAT;"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS exit_price FLOAT;"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS pnl_usd FLOAT;"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS sl FLOAT;"))
        conn.execute(text("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS tp FLOAT;"))

        # Open positions table (single position per symbol)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol VARCHAR(20) PRIMARY KEY,
                side VARCHAR(10),
                entry_price FLOAT,
                notional_usd FLOAT,
                margin_usd FLOAT,
                leverage FLOAT,
                qty FLOAT,
                sl FLOAT,
                tp FLOAT,
                open_time TIMESTAMP
            );
        """))

        # TP0/TP1 columns for graduated take-profit system
        conn.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS tp0_price FLOAT;"))
        conn.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS tp0_hit BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS tp1_price FLOAT;"))
        conn.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS tp1_hit BOOLEAN DEFAULT FALSE;"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS paper_equity (
                symbol VARCHAR(20) PRIMARY KEY,
                balance FLOAT,
                peak FLOAT,
                updated_at TIMESTAMP
            );
        """))
        
        # Table for storing detailed decision context for the Strategy Dashboard
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS decision_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP,
                symbol VARCHAR(20),
                features JSONB,
                agent_probs JSONB,
                risk_metrics JSONB
            );
        """))
        conn.commit()

    asyncio.run(main())
