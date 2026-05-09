"""
Symbol Health Monitor v2 — Graduated response to underperforming tokens.

Instead of a binary pause/unpause, uses a graduated approach:

  TIER 1 — FULL:      1.0x position size (normal trading)
  TIER 2 — REDUCED:   0.50x position size (warning zone)
  TIER 3 — MINIMAL:   0.25x position size (probation)
  TIER 4 — PAUSED:    0.0x — no new positions (only for truly hopeless tokens)

Key improvements over v1:
  - Rolling window: evaluates only the last N trades, not all-time
  - PnL-protected: profitable tokens are NEVER paused regardless of WR/streaks
  - Graduated sizing: reduces size before cutting off entirely
  - Adaptive pause duration: worse performance = longer pause
  - Separate all-time and rolling metrics for transparency

PPO training always continues regardless of tier — the engine keeps learning.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.db import get_db

logger = logging.getLogger(__name__)

# ── Thresholds (tunable) ──────────────────────────────────────────────
# FIX 2026-04-06: Recalibrated to real-world levels.
# Previous thresholds (18 consec losses, 0% WR) NEVER triggered,
# allowing BNB (17% WR, -$2.32) to bleed money unchecked.
# The bot must self-regulate: pause losers, let winners run.
ROLLING_WINDOW = 20              # Evaluate last N trades
MIN_TRADES_FOR_EVAL = 8          # Need at least N closed trades before judging

# Tier thresholds (applied to rolling window)
TIER2_CONSEC_LOSSES = 4          # 4 losses in a row → reduce to 0.50x
TIER3_CONSEC_LOSSES = 6          # 6 losses in a row → reduce to 0.25x
TIER4_CONSEC_LOSSES = 9          # 9 losses in a row → full pause

TIER2_WIN_RATE = 35.0            # % — below 35% in rolling window → 0.50x
TIER3_WIN_RATE = 25.0            # % — below 25% → 0.25x
TIER4_WIN_RATE = 15.0            # % — below 15% → full pause

TIER4_ROLLING_LOSS_USD = -3.0    # Rolling PnL below -$3 → full pause

# PnL protection: if rolling PnL is POSITIVE, max demotion is TIER 2
PNL_POSITIVE_MAX_TIER = 2        # Profitable token can't go below TIER 2

# Pause durations (only for TIER 4)
BASE_PAUSE_HOURS = 12            # Minimum pause — give the market time to change
MAX_PAUSE_HOURS = 48             # Maximum pause — real descanso
PAUSE_PER_ZERO_WR_TRADE = 2.0   # Extra hours per trade at low WR
# ──────────────────────────────────────────────────────────────────────

# Tier multipliers for position sizing
TIER_MULTIPLIERS = {1: 1.0, 2: 0.50, 3: 0.25, 4: 0.0}
TIER_NAMES = {1: "FULL", 2: "REDUCED", 3: "MINIMAL", 4: "PAUSED"}


@dataclass
class SymbolStatus:
    symbol: str
    # All-time stats
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    cumulative_pnl: float = 0.0
    win_rate: float = 0.0
    # Rolling window stats
    rolling_trades: int = 0
    rolling_wins: int = 0
    rolling_losses: int = 0
    rolling_pnl: float = 0.0
    rolling_win_rate: float = 0.0
    consecutive_losses: int = 0
    # Health tier
    tier: int = 1                 # 1=FULL, 2=REDUCED, 3=MINIMAL, 4=PAUSED
    size_multiplier: float = 1.0  # Applied to position size
    tier_reason: str = ""
    # Pause state (only for TIER 4)
    is_paused: bool = False
    pause_reason: str = ""
    paused_at: float = 0.0
    unpause_at: float = 0.0


class SymbolHealthMonitor:
    """Graduated health monitor — reduces size before pausing."""

    def __init__(self) -> None:
        self._status: dict[str, SymbolStatus] = {}
        self._last_refresh: float = 0.0
        self._refresh_interval_s: float = 120.0

    # ── Public API ────────────────────────────────────────────────────

    def can_trade(self, symbol: str) -> bool:
        """Return True if the symbol is allowed to open new positions."""
        self._maybe_refresh()
        st = self._status.get(symbol)
        if st is None:
            return True
        if st.tier < 4:
            return True
        # TIER 4 = PAUSED — check expiry
        if st.is_paused and time.time() >= st.unpause_at:
            self._unpause(symbol, "Pause expired")
            return True
        return not st.is_paused

    def get_size_multiplier(self, symbol: str) -> float:
        """Return position size multiplier (1.0 = full, 0.5, 0.25, 0.0)."""
        self._maybe_refresh()
        st = self._status.get(symbol)
        if st is None:
            return 1.0
        # If TIER 4 but pause expired, treat as TIER 1 (fresh start)
        if st.tier == 4 and st.is_paused and time.time() >= st.unpause_at:
            self._unpause(symbol, "Pause expired")
            return 1.0
        return st.size_multiplier

    def get_pause_reason(self, symbol: str) -> str:
        st = self._status.get(symbol)
        if st is None:
            return ""
        if st.tier == 4 and st.is_paused:
            remaining_min = max(0, (st.unpause_at - time.time())) / 60
            return f"{st.pause_reason} (unpauses in {remaining_min:.0f}m)"
        if st.tier > 1:
            return f"TIER {st.tier} ({TIER_NAMES[st.tier]}): {st.tier_reason}"
        return ""

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Return serializable snapshot for the API."""
        self._maybe_refresh()
        out: dict[str, dict[str, Any]] = {}
        for sym, st in self._status.items():
            remaining = max(0, st.unpause_at - time.time()) if st.is_paused else 0
            out[sym] = {
                # All-time
                "total_trades": st.total_trades,
                "wins": st.wins,
                "losses": st.losses,
                "win_rate": round(st.win_rate, 1),
                "cumulative_pnl": round(st.cumulative_pnl, 2),
                # Rolling window
                "rolling_trades": st.rolling_trades,
                "rolling_wins": st.rolling_wins,
                "rolling_losses": st.rolling_losses,
                "rolling_pnl": round(st.rolling_pnl, 2),
                "rolling_win_rate": round(st.rolling_win_rate, 1),
                "consecutive_losses": st.consecutive_losses,
                # Health tier
                "tier": st.tier,
                "tier_name": TIER_NAMES.get(st.tier, "?"),
                "size_multiplier": st.size_multiplier,
                "tier_reason": st.tier_reason,
                # Pause (only TIER 4)
                "is_paused": st.is_paused,
                "pause_reason": st.pause_reason,
                "unpause_in_min": round(remaining / 60, 1) if remaining > 0 else 0,
            }
        return out

    def force_refresh(self) -> None:
        """Force an immediate DB read (e.g., after a trade closes)."""
        self._refresh_from_db()

    # ── Internal ──────────────────────────────────────────────────────

    def _maybe_refresh(self) -> None:
        now = time.time()
        if now - self._last_refresh >= self._refresh_interval_s:
            self._refresh_from_db()

    def _refresh_from_db(self) -> None:
        """Read paper_trades and compute per-symbol health."""
        db = get_db()
        try:
            rows = db.execute(text("""
                SELECT symbol, pnl_usd, timestamp
                FROM paper_trades
                WHERE event = 'CLOSE' AND pnl_usd IS NOT NULL
                ORDER BY timestamp ASC
            """)).fetchall()
        except Exception as e:
            logger.warning("SymbolHealth: DB read failed: %s", e)
            return
        finally:
            db.close()

        from collections import defaultdict
        sym_trades: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            sym_trades[row.symbol].append(float(row.pnl_usd))

        now = time.time()

        for symbol, pnls in sym_trades.items():
            prev = self._status.get(symbol)
            st = SymbolStatus(symbol=symbol)

            # ── All-time stats ──
            st.total_trades = len(pnls)
            st.wins = sum(1 for p in pnls if p > 0)
            st.losses = sum(1 for p in pnls if p <= 0)
            st.cumulative_pnl = sum(pnls)
            st.win_rate = (st.wins / st.total_trades * 100) if st.total_trades > 0 else 0

            # ── Rolling window stats ──
            rolling = pnls[-ROLLING_WINDOW:]
            st.rolling_trades = len(rolling)
            st.rolling_wins = sum(1 for p in rolling if p > 0)
            st.rolling_losses = sum(1 for p in rolling if p <= 0)
            st.rolling_pnl = sum(rolling)
            st.rolling_win_rate = (st.rolling_wins / st.rolling_trades * 100) if st.rolling_trades > 0 else 0

            # Consecutive losses from END of list
            consec = 0
            for p in reversed(pnls):
                if p <= 0:
                    consec += 1
                else:
                    break
            st.consecutive_losses = consec

            # ── Determine tier ──
            # Preserve TIER 4 pause if still active
            if prev and prev.tier == 4 and prev.is_paused and now < prev.unpause_at:
                st.tier = 4
                st.size_multiplier = 0.0
                st.tier_reason = prev.tier_reason
                st.is_paused = True
                st.pause_reason = prev.pause_reason
                st.paused_at = prev.paused_at
                st.unpause_at = prev.unpause_at
            else:
                self._compute_tier(st)

            self._status[symbol] = st

        self._last_refresh = now

        # Log summary
        demoted = {s: st.tier for s, st in self._status.items() if st.tier > 1}
        if demoted:
            summary = ", ".join(f"{s}=T{t}({TIER_NAMES[t]})" for s, t in demoted.items())
            logger.info("SymbolHealth: demoted → %s", summary)

    def _compute_tier(self, st: SymbolStatus) -> None:
        """Assign tier based on rolling window performance."""
        if st.rolling_trades < MIN_TRADES_FOR_EVAL:
            st.tier = 1
            st.size_multiplier = 1.0
            st.tier_reason = f"< {MIN_TRADES_FOR_EVAL} trades (evaluating)"
            return

        tier = 1
        reason = ""

        # ── Check consecutive losses ──
        if st.consecutive_losses >= TIER4_CONSEC_LOSSES:
            tier = max(tier, 4)
            reason = f"{st.consecutive_losses} consecutive losses"
        elif st.consecutive_losses >= TIER3_CONSEC_LOSSES:
            tier = max(tier, 3)
            reason = f"{st.consecutive_losses} consecutive losses"
        elif st.consecutive_losses >= TIER2_CONSEC_LOSSES:
            tier = max(tier, 2)
            reason = f"{st.consecutive_losses} consecutive losses"

        # ── Check rolling win rate ──
        if st.rolling_win_rate <= TIER4_WIN_RATE:
            if tier < 4:
                tier = 4
                reason = f"Rolling WR {st.rolling_win_rate:.0f}%"
        elif st.rolling_win_rate < TIER3_WIN_RATE:
            if tier < 3:
                tier = 3
                reason = f"Rolling WR {st.rolling_win_rate:.0f}%"
        elif st.rolling_win_rate < TIER2_WIN_RATE:
            if tier < 2:
                tier = 2
                reason = f"Rolling WR {st.rolling_win_rate:.0f}%"

        # ── Check rolling PnL for TIER 4 ──
        if st.rolling_pnl < TIER4_ROLLING_LOSS_USD:
            if tier < 4:
                tier = 4
                reason = f"Rolling PnL ${st.rolling_pnl:.2f}"

        # ── PnL PROTECTION: profitable tokens can't go below TIER 2 ──
        if st.rolling_pnl > 0 and tier > PNL_POSITIVE_MAX_TIER:
            old_tier = tier
            tier = PNL_POSITIVE_MAX_TIER
            reason = f"PnL-protected (${st.rolling_pnl:+.2f}), was T{old_tier}"
            logger.info(
                "SYMBOL HEALTH: PnL-PROTECTED %s — rolling PnL $%+.2f > 0 → "
                "capped at TIER %d instead of TIER %d",
                st.symbol, st.rolling_pnl, PNL_POSITIVE_MAX_TIER, old_tier,
            )

        # ── Apply tier ──
        st.tier = tier
        st.size_multiplier = TIER_MULTIPLIERS[tier]
        st.tier_reason = reason

        if tier == 4:
            self._apply_pause(st, reason)
        elif tier > 1:
            logger.info(
                "SYMBOL HEALTH: %s → TIER %d (%s) — size %.0f%% — %s",
                st.symbol, tier, TIER_NAMES[tier],
                st.size_multiplier * 100, reason,
            )

    def _apply_pause(self, st: SymbolStatus, reason: str) -> None:
        """Apply TIER 4 pause with adaptive duration."""
        # Adaptive duration: worse stats = longer pause
        # Base 4h + 1h per loss at 0% WR in rolling window, capped at 24h
        extra_hours = 0.0
        if st.rolling_win_rate == 0 and st.rolling_trades > 0:
            extra_hours = st.rolling_trades * PAUSE_PER_ZERO_WR_TRADE
        pause_hours = min(BASE_PAUSE_HOURS + extra_hours, MAX_PAUSE_HOURS)

        st.is_paused = True
        st.pause_reason = reason
        st.paused_at = time.time()
        st.unpause_at = time.time() + pause_hours * 3600

        logger.warning(
            "SYMBOL HEALTH: PAUSING %s — %s (%.0fh pause, rolling WR=%.0f%%, "
            "rolling PnL=$%+.2f, consec=%d)",
            st.symbol, reason, pause_hours,
            st.rolling_win_rate, st.rolling_pnl, st.consecutive_losses,
        )

    def _unpause(self, symbol: str, reason: str) -> None:
        st = self._status.get(symbol)
        if st:
            st.tier = 1
            st.size_multiplier = 1.0
            st.tier_reason = ""
            st.is_paused = False
            st.pause_reason = ""
            st.paused_at = 0
            st.unpause_at = 0
        logger.info("SYMBOL HEALTH: UNPAUSED %s → TIER 1 (FULL) — %s", symbol, reason)


# ── Singleton ─────────────────────────────────────────────────────────
_monitor: SymbolHealthMonitor | None = None

def get_symbol_health_monitor() -> SymbolHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SymbolHealthMonitor()
    return _monitor
