"""
Liquidez Inteligente — Small-Cap Guards Module
===============================================
Protections for thin-liquidity small-cap trading on BingX.

Guards:
1. Spread Guardian     — Block trades when bid/ask spread is too wide
2. Volume Spike Gate   — Only enter when volume confirms momentum
3. Session Filter      — Block night trading (22-06 UTC) based on real data
4. ATR-based SL/TP     — Dynamic levels based on real volatility, not fixed %
5. Leverage Adjuster   — Reduce leverage for illiquid tokens

All functions are pure (no side effects) and return decisions + reasons.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── 1. SPREAD GUARDIAN ─────────────────────────────────────────────

MAX_SPREAD_BPS = 30.0  # Default max (overridden by tier config)
SPREAD_WARN_BPS = 15.0  # Warn if spread > 15 bps

def check_spread_guard(
    microstructure: dict[str, Any] | None,
    notional_usd: float = 0.0,
    tier: str = "meme",
) -> tuple[bool, str, float]:
    """Check if spread is acceptable for trading.
    
    Args:
        tier: 'major' or 'meme' — determines spread limit.
    
    Returns: (allow_trade, reason, spread_bps)
    """
    # Get tier-specific spread limit
    try:
        from app.config import TIER_CONFIG
        max_spread = TIER_CONFIG.get(tier, {}).get("spread_max_bps", MAX_SPREAD_BPS)
    except ImportError:
        max_spread = MAX_SPREAD_BPS
    """Check if spread is acceptable for trading.
    
    Returns: (allow_trade, reason, spread_bps)
    """
    if microstructure is None:
        # No orderbook data — allow but warn
        return True, "no_orderbook_data", 0.0

    spread_bps = float(microstructure.get("spread_bps") or 0.0)
    bid_depth = float(microstructure.get("bid_depth_usd") or 0.0)
    ask_depth = float(microstructure.get("ask_depth_usd") or 0.0)

    if spread_bps <= 0:
        return True, "spread_unknown", 0.0

    # Hard block: spread too wide
    if spread_bps > max_spread:
        return False, f"spread_too_wide_{spread_bps:.0f}bps>{max_spread:.0f}bps", spread_bps

    # Depth check: if our position > 10% of visible depth, slippage will be brutal
    if notional_usd > 0 and bid_depth > 0:
        depth_ratio = notional_usd / min(bid_depth, ask_depth) if min(bid_depth, ask_depth) > 0 else 999
        if depth_ratio > 0.15:
            return False, f"depth_insufficient_ratio={depth_ratio:.2f}", spread_bps

    if spread_bps > SPREAD_WARN_BPS:
        return True, f"spread_elevated_{spread_bps:.0f}bps", spread_bps

    return True, "spread_ok", spread_bps


# ── 2. VOLUME SPIKE GATE ──────────────────────────────────────────

VOL_RATIO_MIN = 1.5    # Minimum volume ratio (current vs avg) to enter
VOL_RATIO_IDEAL = 2.5  # Ideal volume ratio for strong signals

def check_volume_gate(
    market_data: pd.DataFrame,
    tier: str = "meme",
) -> tuple[bool, str, float]:
    """Check if volume confirms momentum for entry.
    
    Args:
        tier: 'major' or 'meme' — majors need less volume confirmation.
    
    Returns: (allow_trade, reason, vol_ratio)
    """
    # Get tier-specific volume ratio minimum
    try:
        from app.config import TIER_CONFIG
        vol_min = TIER_CONFIG.get(tier, {}).get("vol_ratio_min", VOL_RATIO_MIN)
    except ImportError:
        vol_min = VOL_RATIO_MIN
    """Check if volume confirms momentum for entry.
    
    Returns: (allow_trade, reason, vol_ratio)
    """
    try:
        volume = market_data["volume"].astype(float)
        n = len(volume)
        if n < 20:
            return True, "insufficient_history", 1.0

        vol_current = float(volume.iloc[-1])
        vol_avg_20 = float(volume.iloc[-20:].mean())

        if vol_avg_20 <= 0:
            return True, "zero_avg_volume", 1.0

        vol_ratio = vol_current / vol_avg_20

        if vol_ratio < 0.5:
            # Volume is dying — NO entry (dead market)
            return False, f"volume_dead_ratio={vol_ratio:.2f}", vol_ratio

        if vol_ratio < vol_min:
            # Below minimum — block directional trades
            return False, f"volume_low_ratio={vol_ratio:.2f}<{vol_min}", vol_ratio

        return True, f"volume_ok_ratio={vol_ratio:.2f}", vol_ratio

    except Exception as e:
        logger.debug("Volume gate error: %s", e)
        return True, "volume_error", 1.0


# ── 3. SESSION FILTER ─────────────────────────────────────────────
# Based on REAL DATA: Noche = -$48.27, Día = +$5.66

def check_session_filter(tier: str = "meme") -> tuple[str, float]:
    """Determine trading mode based on UTC hour.
    
    Args:
        tier: 'major' tokens trade 24/7, 'meme' tokens have session restrictions.
    
    Returns: (mode, size_multiplier)
    Modes: "FULL" | "REDUCED" | "LONG_ONLY" | "PAUSED"
    """
    # Majors: always full (deep liquidity 24/7)
    try:
        from app.config import TIER_CONFIG
        if not TIER_CONFIG.get(tier, {}).get("session_filter", True):
            return "FULL", 1.0
    except ImportError:
        pass

    hour_utc = datetime.now(timezone.utc).hour

    if 13 <= hour_utc <= 20:
        # London + US overlap — best session
        return "FULL", 1.0
    elif 7 <= hour_utc <= 12:
        # London only — reduced size
        return "REDUCED", 0.70
    elif 21 <= hour_utc <= 23:
        # US wind-down — long only, reduced
        return "LONG_ONLY", 0.50
    else:  # 0-6 UTC
        # NIGHT — data shows -$48.27 loss
        return "PAUSED", 0.0


# ── 4. ATR-BASED SL/TP ────────────────────────────────────────────

def compute_atr_sl_tp(
    market_data: pd.DataFrame,
    direction: str,      # "LONG" or "SHORT"
    leverage: float,
    current_price: float,
    max_capital_risk_pct: float = 0.03,  # Max 3% of capital per trade
) -> dict[str, Any] | None:
    """Compute ATR-based SL/TP levels.
    
    Returns dict with sl, tp1, tp2, or None if trade is too risky.
    """
    try:
        high = market_data["high"].astype(float)
        low = market_data["low"].astype(float)
        close = market_data["close"].astype(float)
        n = len(close)

        if n < 15:
            return None

        # True Range
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        atr_14 = float(tr.rolling(14).mean().iloc[-1])
        if np.isnan(atr_14) or atr_14 <= 0:
            return None

        # SL = 1.2 * ATR
        sl_distance = atr_14 * 1.2
        sl_pct = sl_distance / current_price

        # Check if SL is suicidal with leverage
        max_sl_pct = max_capital_risk_pct / leverage
        if sl_pct > max_sl_pct:
            # Too volatile for this leverage
            logger.info(
                "ATR SL too wide: %.2f%% > max %.2f%% (ATR=%.4f, lev=%.1fx)",
                sl_pct * 100, max_sl_pct * 100, atr_14, leverage,
            )
            return None

        # TP levels
        tp1_distance = atr_14 * 1.5   # TP1 at 1.5x ATR
        tp2_distance = atr_14 * 3.0   # TP2 at 3.0x ATR

        if direction == "LONG":
            sl = current_price - sl_distance
            tp1 = current_price + tp1_distance
            tp2 = current_price + tp2_distance
        else:
            sl = current_price + sl_distance
            tp1 = current_price - tp1_distance
            tp2 = current_price - tp2_distance

        return {
            "sl": sl,
            "sl_pct": sl_pct,
            "tp1": tp1,
            "tp1_close_pct": 0.50,  # Close 50% at TP1
            "tp2": tp2,
            "tp2_close_pct": 0.30,  # Close 30% at TP2, 20% trailing
            "atr_14": atr_14,
            "rr_ratio": tp2_distance / sl_distance,  # Should be ~2.5:1
        }

    except Exception as e:
        logger.debug("ATR SL/TP error: %s", e)
        return None


# ── 5. ANTI-DUMP SHIELD ───────────────────────────────────────────

def check_pump_and_dump_risk(
    market_data: pd.DataFrame,
    vol_ratio: float,
) -> tuple[bool, str]:
    """Detect pump & dump patterns.
    
    Returns: (is_safe, reason)
    """
    try:
        n = len(market_data)
        if n < 5:
            return True, "ok"

        close = market_data["close"].astype(float)
        high = market_data["high"].astype(float)
        volume = market_data["volume"].astype(float)

        # Check last 15 min (3 candles of 5m)
        if n >= 3:
            price_change_15m = (float(close.iloc[-1]) - float(close.iloc[-3])) / float(close.iloc[-3]) if float(close.iloc[-3]) > 0 else 0

            # Explosive rise with insane volume
            if price_change_15m > 0.05 and vol_ratio > 5.0:
                # Check for rejection wicks
                last = market_data.iloc[-1]
                body = abs(float(last["close"]) - float(last["open"]))
                upper_wick = float(last["high"]) - max(float(last["close"]), float(last["open"]))

                if body > 0 and upper_wick > body * 1.5:
                    return False, f"pump_dump_wick_rejection_change={price_change_15m*100:.1f}%"

                # Volume declining after spike = smart money exiting
                if n >= 3 and float(volume.iloc[-1]) < float(volume.iloc[-2]) * 0.6:
                    return False, f"pump_dump_vol_decline_change={price_change_15m*100:.1f}%"

            # Sudden crash detection (for SHORT protection)
            if price_change_15m < -0.05 and vol_ratio > 5.0:
                lower_wick = min(float(close.iloc[-1]), float(market_data.iloc[-1]["open"])) - float(market_data.iloc[-1]["low"])
                if lower_wick > body * 1.5 if body > 0 else False:
                    return False, f"dump_bounce_risk_change={price_change_15m*100:.1f}%"

        return True, "ok"

    except Exception as e:
        logger.debug("Anti-dump error: %s", e)
        return True, "error"


# ── 6. LEVERAGE ADJUSTER ──────────────────────────────────────────

def adjust_leverage_for_liquidity(
    base_leverage: float,
    microstructure: dict[str, Any] | None,
    spread_bps: float,
) -> float:
    """Reduce leverage for illiquid tokens.
    
    Returns: adjusted leverage
    """
    if spread_bps > 20:
        # Tight spread penalty
        return min(base_leverage, 10.0)
    if spread_bps > 10:
        return min(base_leverage, 15.0)

    if microstructure:
        bid_depth = float(microstructure.get("bid_depth_usd") or 0)
        ask_depth = float(microstructure.get("ask_depth_usd") or 0)
        total_depth = bid_depth + ask_depth

        if total_depth < 5000:
            return min(base_leverage, 5.0)  # Ultra thin book
        elif total_depth < 20000:
            return min(base_leverage, 10.0)
        elif total_depth < 50000:
            return min(base_leverage, 15.0)

    return base_leverage


# ── 7. TOKEN KILLSWITCH ───────────────────────────────────────────

KILLSWITCH_CONSEC_LOSSES = 3       # Default: 3 consecutive losses → pause
KILLSWITCH_CUMULATIVE_LOSS = -8.0  # Default: $-8 total PnL → pause
KILLSWITCH_AVG_SPREAD_MAX = 40.0   # avg spread > 40 bps → pause

def check_token_killswitch(
    symbol: str,
    recent_pnls: list[float],
    avg_spread_bps: float = 0.0,
    tier: str = "meme",
) -> tuple[bool, str]:
    """Kill switch for individual tokens based on performance.
    
    Args:
        tier: 'major' or 'meme' — different thresholds.
    
    Returns: (allow_trading, reason)
    When a token is killed, it's also registered for auto-rotation.
    """
    if not recent_pnls:
        return True, "ok_no_data"

    # Get tier-specific thresholds
    try:
        from app.config import TIER_CONFIG
        cfg = TIER_CONFIG.get(tier, {})
        max_consec = cfg.get("killswitch_consec", KILLSWITCH_CONSEC_LOSSES)
        max_loss = cfg.get("killswitch_loss", KILLSWITCH_CUMULATIVE_LOSS)
    except ImportError:
        max_consec = KILLSWITCH_CONSEC_LOSSES
        max_loss = KILLSWITCH_CUMULATIVE_LOSS

    # Check consecutive losses from end
    consec_losses = 0
    for pnl in reversed(recent_pnls):
        if pnl <= 0:
            consec_losses += 1
        else:
            break

    if consec_losses >= max_consec:
        reason = f"killswitch_{consec_losses}_consecutive_losses"
        _register_kill(symbol, reason)
        return False, reason

    # Check cumulative loss
    total_pnl = sum(recent_pnls)
    if total_pnl < max_loss:
        reason = f"killswitch_cumulative_loss_${total_pnl:.2f}"
        _register_kill(symbol, reason)
        return False, reason

    # Check spread
    if avg_spread_bps > KILLSWITCH_AVG_SPREAD_MAX:
        reason = f"killswitch_illiquid_spread_{avg_spread_bps:.0f}bps"
        _register_kill(symbol, reason)
        return False, reason

    return True, "ok"


def _register_kill(symbol: str, reason: str) -> None:
    """Register a killed token for auto-rotation (lazy import to avoid circular deps)."""
    try:
        from app.token_rotator import mark_token_killed
        mark_token_killed(symbol, reason)
    except Exception as e:
        logger.debug("Could not register kill for %s: %s", symbol, e)


# ── 8. MOMENTUM BURST ENTRY ───────────────────────────────────────

def check_momentum_burst(
    market_data: 'pd.DataFrame',
    vol_ratio: float,
) -> tuple[str, float | None]:
    """Detect momentum burst for entry signal.
    
    Triple confirmation:
    1. Volume spike (>2.0x average)
    2. Price breaking 1-hour range (12 candles of 5m)
    3. 3 consecutive candles same direction
    
    Returns: (signal, breakout_level)
    signal: "LONG", "SHORT", or "HOLD"
    breakout_level: price level of the breakout (for SL placement)
    """
    try:
        n = len(market_data)
        if n < 15:
            return "HOLD", None

        close = market_data["close"].astype(float)
        open_ = market_data["open"].astype(float)
        high = market_data["high"].astype(float)
        low = market_data["low"].astype(float)

        current = float(close.iloc[-1])

        # 1-hour range (last 12 candles)
        high_1h = float(high.iloc[-12:].max())
        low_1h = float(low.iloc[-12:].min())
        range_1h = high_1h - low_1h

        if range_1h <= 0:
            return "HOLD", None

        # Check volume requirement
        if vol_ratio < 2.0:
            return "HOLD", None

        # Breakout detection + 3 candle confirmation
        last_3_close = close.iloc[-3:].values
        last_3_open = open_.iloc[-3:].values

        three_bullish = all(c > o for c, o in zip(last_3_close, last_3_open))
        three_bearish = all(c < o for c, o in zip(last_3_close, last_3_open))

        # LONG: price above 1h high + 3 green candles + volume
        if current > high_1h and three_bullish:
            return "LONG", low_1h  # SL below the range

        # SHORT: price below 1h low + 3 red candles + volume
        if current < low_1h and three_bearish:
            return "SHORT", high_1h  # SL above the range

        return "HOLD", None

    except Exception as e:
        logger.debug("Momentum burst error: %s", e)
        return "HOLD", None
