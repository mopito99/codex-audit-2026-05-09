"""
PATHOLOGY_TAXONOMY_v1 · QuantumBot PPO reward shaping
Created 2026-05-07 (r149-pent Q17)

Initial pathology taxonomy for Gemma narrator → reward shaping pipeline.
Each pathology has:
  - detection: callable (episode_log) → bool
  - delta: float reward adjustment when triggered
  - min_precision: required precision in manual sampling before activation
  - level: L1 (psychological) | L2 (execution) | L3 (timing) | L4 (risk_mgmt) | L_POS (positive)

Validation pipeline before activation:
  1. Gemma narrator tags 100 sample episodes
  2. Marco/Claude manual-sample 20 to validate precision
  3. If precision < min_precision → tag is NOT activated in reward function
  4. Cross-validation against alternate narrator (Claude) every 30 episodes

Reward delta is applied PER STEP when detection fires, NOT cumulatively per episode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


EpisodeStep = dict[str, Any]
EpisodeLog = list[EpisodeStep]


@dataclass(frozen=True)
class Pathology:
    name: str
    level: str
    delta: float
    min_precision: float
    description: str
    detection: Callable[[EpisodeStep, EpisodeLog], bool] = field(repr=False)


# ────────────────────────────────────────────────────────────
# Detection helpers
# ────────────────────────────────────────────────────────────

def _seconds_since(step: EpisodeStep, ref_step: EpisodeStep) -> float:
    return float(step["timestamp"]) - float(ref_step["timestamp"])


def _last_closed_loss_step(log: EpisodeLog, before_idx: int) -> EpisodeStep | None:
    for i in range(before_idx - 1, -1, -1):
        s = log[i]
        if s.get("event") == "close" and s.get("closed_pnl", 0) < 0:
            return s
    return None


# ────────────────────────────────────────────────────────────
# L1 — Psychological pathologies
# ────────────────────────────────────────────────────────────

def _detect_revenge_trade(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    idx = log.index(step)
    prev_loss = _last_closed_loss_step(log, idx)
    if prev_loss is None:
        return False
    if _seconds_since(step, prev_loss) > 300:  # 5 min
        return False
    size_new = step.get("size", 0)
    size_prev = prev_loss.get("size", 1)
    return size_new > size_prev * 1.2


def _detect_martingale(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    idx = log.index(step)
    if idx == 0:
        return False
    prev_open = next(
        (log[i] for i in range(idx - 1, -1, -1) if log[i].get("event") == "open"),
        None,
    )
    if prev_open is None:
        return False
    prev_close = next(
        (log[i] for i in range(idx - 1, -1, -1)
         if log[i].get("event") == "close" and
            log[i].get("symbol") == prev_open.get("symbol")),
        None,
    )
    if prev_close is None or prev_close.get("closed_pnl", 0) >= 0:
        return False
    return step.get("size", 0) > 2 * prev_open.get("size", 1)


def _detect_panic_close(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "close":
        return False
    open_step = next(
        (s for s in log if s.get("event") == "open" and
         s.get("position_id") == step.get("position_id")),
        None,
    )
    if open_step is None:
        return False
    duration = _seconds_since(step, open_step)
    if duration >= 60:
        return False
    drawdown_pct = abs(step.get("closed_pnl_pct", 0))
    return drawdown_pct < 0.01  # closed in first 60s with <1% drawdown


def _detect_over_leverage(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    leverage = step.get("leverage", 1.0)
    volatility_sigma = step.get("market_volatility_sigma", 0.0)
    return leverage >= 5.0 and volatility_sigma > 2.0


def _detect_bag_hold(step: EpisodeStep, log: EpisodeLog) -> bool:
    """Position open >2h with growing drawdown and bot took no action."""
    if step.get("event") != "tick":
        return False
    open_step = next(
        (s for s in log if s.get("event") == "open" and
         s.get("position_id") == step.get("position_id")),
        None,
    )
    if open_step is None:
        return False
    duration = _seconds_since(step, open_step)
    if duration < 7200:  # < 2h
        return False
    return step.get("drawdown_pct", 0) > 0.03  # growing >3%


# ────────────────────────────────────────────────────────────
# L2 — Execution pathologies
# ────────────────────────────────────────────────────────────

def _detect_slippage_eat(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    actual = step.get("execution_price", 0)
    quote = step.get("quote_price", 0)
    if not quote:
        return False
    slippage_pct = abs(actual - quote) / quote
    return slippage_pct >= 0.003  # ≥0.3%


def _detect_chasing_pump(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open" or step.get("side") != "long":
        return False
    pump_1h = step.get("price_change_1h", 0)
    has_signal = step.get("strategy_signal_present", False)
    return pump_1h >= 0.05 and not has_signal


def _detect_whip_chase(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    idx = log.index(step)
    for i in range(idx - 1, max(idx - 10, -1), -1):
        prev = log[i]
        if prev.get("event") != "open":
            continue
        if prev.get("symbol") != step.get("symbol"):
            continue
        if _seconds_since(step, prev) > 60:
            break
        if prev.get("side") != step.get("side"):
            return True
    return False


def _detect_signal_skip(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "tick":
        return False
    return (
        step.get("strategy_signal_strength", 0) > 0.8 and
        step.get("action_taken") in (None, "hold")
    )


# ────────────────────────────────────────────────────────────
# L3 — Timing pathologies
# ────────────────────────────────────────────────────────────

def _detect_weekend_yolo(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    weekday = step.get("utc_weekday")  # 0=Mon, 6=Sun
    hour = step.get("utc_hour", 0)
    if weekday == 4 and hour >= 22:
        return True
    if weekday == 5:
        return True
    if weekday == 6 and hour < 24:
        return True
    return False


def _detect_low_liq_session(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    return step.get("session_volume_percentile", 1.0) < 0.20


def _detect_news_chase(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    return step.get("seconds_since_news_tag", 9999) <= 30


def _detect_over_traded_session(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    idx = log.index(step)
    cnt = 0
    for i in range(idx - 1, -1, -1):
        prev = log[i]
        if prev.get("event") != "open":
            continue
        if _seconds_since(step, prev) > 3600:
            break
        cnt += 1
    return cnt >= 20


# ────────────────────────────────────────────────────────────
# L4 — Risk management pathologies
# ────────────────────────────────────────────────────────────

def _detect_correlation_breakdown(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    open_positions = step.get("currently_open_positions", [])
    longs_btc = any(p["symbol"] == "BTC-USDT" and p["side"] == "long" for p in open_positions)
    longs_sol = any(p["symbol"] == "SOL-USDT" and p["side"] == "long" for p in open_positions)
    if not (longs_btc and longs_sol):
        return False
    return step.get("btc_sol_correlation_30d", 1.0) < 0.30


def _detect_concentration_risk(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "tick":
        return False
    largest_pos_pct = step.get("largest_position_pct_capital", 0)
    duration = step.get("largest_position_duration_min", 0)
    return largest_pos_pct > 0.40 and duration > 30


def _detect_no_stop_loss(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "tick":
        return False
    return (
        step.get("position_open_seconds", 0) > 300 and
        step.get("position_has_stop_loss", True) is False
    )


def _detect_recovery_time_violation(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    idx = log.index(step)
    for i in range(idx - 1, -1, -1):
        prev = log[i]
        if prev.get("event") != "tick":
            continue
        if _seconds_since(step, prev) > 120:
            break
        if prev.get("drawdown_pct", 0) > 0.02:
            return True
    return False


# ────────────────────────────────────────────────────────────
# L_POS — Positive reinforcement
# ────────────────────────────────────────────────────────────

def _detect_disciplined_close(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "close":
        return False
    return step.get("close_reason") == "tp_hit"


def _detect_risk_off_volatility(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    sigma = step.get("market_volatility_sigma", 0)
    if sigma <= 2.0:
        return False
    avg_size_30d = step.get("avg_open_size_30d", step.get("size", 1))
    return step.get("size", 0) < avg_size_30d * 0.7


def _detect_signal_executed_clean(step: EpisodeStep, log: EpisodeLog) -> bool:
    if step.get("event") != "open":
        return False
    actual = step.get("execution_price", 0)
    quote = step.get("quote_price", 0)
    if not quote:
        return False
    return abs(actual - quote) / quote < 0.001  # <0.1% slippage


def _detect_pattern_correlation_held(step: EpisodeStep, log: EpisodeLog) -> bool:
    """Mantained position during drawdown <2% (no panic close)."""
    if step.get("event") != "tick":
        return False
    return (
        0.005 < step.get("drawdown_pct", 0) < 0.02 and
        step.get("position_open_seconds", 0) > 60 and
        step.get("action_taken") in (None, "hold")
    )


# ────────────────────────────────────────────────────────────
# TAXONOMY v1 — single source of truth
# ────────────────────────────────────────────────────────────

PATHOLOGY_TAXONOMY_v1: dict[str, Pathology] = {
    # L1 psychological
    "revenge_trade": Pathology(
        "revenge_trade", "L1", -0.5, 0.70,
        "New position within 5min after closed-loss with size>1.2× prev",
        _detect_revenge_trade,
    ),
    "martingale": Pathology(
        "martingale", "L1", -0.7, 0.75,
        "Size doubled after losing trade",
        _detect_martingale,
    ),
    "panic_close": Pathology(
        "panic_close", "L1", -0.3, 0.65,
        "Closed <60s with <1% drawdown",
        _detect_panic_close,
    ),
    "bag_hold": Pathology(
        "bag_hold", "L1", -0.4, 0.70,
        "Position >2h with growing drawdown, no action",
        _detect_bag_hold,
    ),
    "over_leverage": Pathology(
        "over_leverage", "L1", -0.6, 0.75,
        "Leverage ≥5x in volatility >2σ session",
        _detect_over_leverage,
    ),
    # L2 execution
    "slippage_eat": Pathology(
        "slippage_eat", "L2", -0.2, 0.80,
        "Entry price ≥0.3% worse than quote",
        _detect_slippage_eat,
    ),
    "chasing_pump": Pathology(
        "chasing_pump", "L2", -0.4, 0.65,
        "Long after +5% pump in 1h with no signal",
        _detect_chasing_pump,
    ),
    "whip_chase": Pathology(
        "whip_chase", "L2", -0.3, 0.70,
        "Direction reversal within same minute",
        _detect_whip_chase,
    ),
    "signal_skip": Pathology(
        "signal_skip", "L2", -0.1, 0.60,
        "High-confidence signal ignored (sometimes correct)",
        _detect_signal_skip,
    ),
    # L3 timing
    "weekend_yolo": Pathology(
        "weekend_yolo", "L3", -0.2, 0.85,
        "Position opened during low-volume weekend window",
        _detect_weekend_yolo,
    ),
    "low_liq_session": Pathology(
        "low_liq_session", "L3", -0.1, 0.70,
        "Trade in <20%ile volume session",
        _detect_low_liq_session,
    ),
    "news_chase": Pathology(
        "news_chase", "L3", -0.3, 0.65,
        "Entry within 30s of news tag",
        _detect_news_chase,
    ),
    "over_traded_session": Pathology(
        "over_traded_session", "L3", -0.2, 0.75,
        ">20 trades in 1h",
        _detect_over_traded_session,
    ),
    # L4 risk management
    "correlation_breakdown": Pathology(
        "correlation_breakdown", "L4", -0.5, 0.70,
        "Long BTC + Long SOL when corr30d <0.3",
        _detect_correlation_breakdown,
    ),
    "concentration_risk": Pathology(
        "concentration_risk", "L4", -0.6, 0.80,
        ">40% of capital in single pair >30min",
        _detect_concentration_risk,
    ),
    "no_stop_loss": Pathology(
        "no_stop_loss", "L4", -0.8, 0.90,
        "Position open >5min without stop_loss",
        _detect_no_stop_loss,
    ),
    "recovery_time_violation": Pathology(
        "recovery_time_violation", "L4", -0.4, 0.70,
        "New position <2min after >2% drawdown",
        _detect_recovery_time_violation,
    ),
    # L_POS positive reinforcement
    "disciplined_close": Pathology(
        "disciplined_close", "L_POS", +0.3, 0.65,
        "Closed at TP target",
        _detect_disciplined_close,
    ),
    "risk_off_volatility": Pathology(
        "risk_off_volatility", "L_POS", +0.4, 0.70,
        "Reduced size during volatility >2σ",
        _detect_risk_off_volatility,
    ),
    "signal_executed_clean": Pathology(
        "signal_executed_clean", "L_POS", +0.2, 0.80,
        "Signal executed with <0.1% slippage",
        _detect_signal_executed_clean,
    ),
    "pattern_correlation_held": Pathology(
        "pattern_correlation_held", "L_POS", +0.1, 0.65,
        "Maintained position during <2% drawdown (no panic)",
        _detect_pattern_correlation_held,
    ),
}


def apply_taxonomy(
    step: EpisodeStep,
    log: EpisodeLog,
    enabled_tags: set[str] | None = None,
) -> dict[str, float]:
    """Apply taxonomy detections to a single step.

    Returns: {pathology_name: reward_delta} for tags that fired.
    Only tags in enabled_tags are evaluated (None = all).
    """
    fired: dict[str, float] = {}
    for name, pathology in PATHOLOGY_TAXONOMY_v1.items():
        if enabled_tags is not None and name not in enabled_tags:
            continue
        try:
            if pathology.detection(step, log):
                fired[name] = pathology.delta
        except (KeyError, ValueError, TypeError):
            continue
    return fired


def reward_delta_for_step(
    step: EpisodeStep,
    log: EpisodeLog,
    enabled_tags: set[str] | None = None,
) -> float:
    """Sum of reward deltas from all firing tags. To be added to PPO base reward."""
    return sum(apply_taxonomy(step, log, enabled_tags).values())
