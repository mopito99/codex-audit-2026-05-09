from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# ── Playbook System (Gemma4 Strategy Engine) ─────────────────
import threading as _threading


def _compute_liquidity(hour: int) -> float:
    """Compute liquidity score based on UTC hour."""
    if 13 <= hour <= 16: return 1.0    # London + US overlap
    if 7 <= hour <= 12: return 0.8     # London only
    if 17 <= hour <= 21: return 0.7    # US only
    if 22 <= hour or hour <= 1: return 0.4  # Asia early
    return 0.3                          # Dead hours (2-6 UTC)


# ── BTC Momentum + Funding Rate Intelligence ──────────────────
import time as _time
import requests as _requests

_btc_cache: dict[str, float] = {"momentum": 0.0, "ts": 0.0}
_funding_cache: dict[str, dict] = {}  # symbol -> {rate, ts}
_BINGX_BASE = "https://open-api.bingx.com"


def _get_btc_momentum() -> float:
    """Get BTC 1h price change (%). Cached 60s."""
    now = _time.time()
    if now - _btc_cache["ts"] < 60:
        return _btc_cache["momentum"]
    try:
        r = _requests.get(f"{_BINGX_BASE}/openApi/swap/v3/quote/klines",
                          params={"symbol": "BTC-USDT", "interval": "1h", "limit": 2},
                          timeout=5)
        data = r.json().get("data", [])
        if len(data) >= 2:
            prev_close = float(data[-2]["close"])
            curr_close = float(data[-1]["close"])
            pct = ((curr_close - prev_close) / prev_close) * 100
            _btc_cache["momentum"] = round(pct, 3)
            _btc_cache["ts"] = now
    except Exception:
        pass
    return _btc_cache["momentum"]


def _get_funding_rate(symbol: str) -> float:
    """Get current funding rate for a symbol. Cached 300s."""
    now = _time.time()
    cached = _funding_cache.get(symbol)
    if cached and now - cached["ts"] < 300:
        return cached["rate"]
    try:
        r = _requests.get(f"{_BINGX_BASE}/openApi/swap/v2/quote/premiumIndex",
                          params={"symbol": symbol}, timeout=5)
        data = r.json().get("data", {})
        rate = float(data.get("lastFundingRate", 0))
        _funding_cache[symbol] = {"rate": rate, "ts": now}
        return rate
    except Exception:
        return _funding_cache.get(symbol, {}).get("rate", 0.0)

# ── CIRCUIT BREAKER: Drawdown Protection ──────────────────────
_DAILY_MAX_DRAWDOWN_PCT = 10.0   # Max 10% loss per day → stop trading
_TOTAL_MAX_DRAWDOWN_PCT = 100.0   # Max 20% from peak → full stop
_circuit_state: dict[str, Any] = {
    "daily_start_equity": None,
    "daily_date": None,
    "peak_equity": None,
    "tripped": False,
    "trip_reason": None,
}


def _check_circuit_breaker(current_equity: float, initial_capital: float) -> tuple[bool, str]:
    """Check if circuit breaker should trip. Returns (allow_trading, reason)."""
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Reset daily tracker at midnight UTC
    if _circuit_state["daily_date"] != now_date:
        _circuit_state["daily_date"] = now_date
        _circuit_state["daily_start_equity"] = current_equity
        # Don't reset total trip — that requires manual reset

    # Initialize peak
    if _circuit_state["peak_equity"] is None:
        # Use current equity as baseline (not initial_capital which may be higher
        # than actual balance after losses — would false-trip the CB on restart)
        _circuit_state["peak_equity"] = current_equity
    else:
        _circuit_state["peak_equity"] = max(_circuit_state["peak_equity"], current_equity)

    peak = _circuit_state["peak_equity"]
    daily_start = _circuit_state["daily_start_equity"] or current_equity

    # Check TOTAL drawdown from peak
    total_dd = ((peak - current_equity) / peak) * 100 if peak > 0 else 0
    if total_dd >= _TOTAL_MAX_DRAWDOWN_PCT:
        _circuit_state["tripped"] = True
        _circuit_state["trip_reason"] = f"TOTAL DD {total_dd:.1f}% >= {_TOTAL_MAX_DRAWDOWN_PCT}%"
        return False, _circuit_state["trip_reason"]

    # Check DAILY drawdown
    daily_dd = ((daily_start - current_equity) / daily_start) * 100 if daily_start > 0 else 0
    if daily_dd >= _DAILY_MAX_DRAWDOWN_PCT:
        _circuit_state["tripped"] = True
        _circuit_state["trip_reason"] = f"DAILY DD {daily_dd:.1f}% >= {_DAILY_MAX_DRAWDOWN_PCT}%"
        return False, _circuit_state["trip_reason"]

    # Still tripped from before? (only total trip persists across days)
    if _circuit_state["tripped"] and total_dd >= _TOTAL_MAX_DRAWDOWN_PCT:
        return False, _circuit_state["trip_reason"] or "circuit_breaker_active"

    # All clear — reset trip if daily has recovered
    if _circuit_state["tripped"] and total_dd < _TOTAL_MAX_DRAWDOWN_PCT:
        _circuit_state["tripped"] = False
        _circuit_state["trip_reason"] = None

    return True, "OK"


_playbook_lock = _threading.Lock()
_playbook_cache: dict[str, Any] = {"data": None, "mtime": 0.0}
_PLAYBOOK_PATH = str(Path(__file__).resolve().parent.parent / "data" / "playbook.json")


def load_playbook() -> dict | None:
    """Load playbook.json with caching (checks mtime)."""
    try:
        mtime = os.path.getmtime(_PLAYBOOK_PATH)
        with _playbook_lock:
            if _playbook_cache["data"] is not None and mtime <= _playbook_cache["mtime"]:
                return _playbook_cache["data"]
        with open(_PLAYBOOK_PATH) as f:
            data = json.load(f)
        with _playbook_lock:
            _playbook_cache["data"] = data
            _playbook_cache["mtime"] = mtime
        return data
    except Exception:
        return None


def match_playbook_rules(features: dict[str, Any]) -> dict[str, Any]:
    """Match current features against playbook rules.
    
    Returns: {action: 0|1|2, sl_pct, tp1_pct, tp2_pct, rule_id, reason, confidence}
    """
    pb = load_playbook()
    if not pb or not pb.get("rules"):
        return {"action": 0, "rule_id": None, "reason": "no_playbook"}
    
    best_match = None
    best_confidence = -1.0
    
    for rule in pb["rules"]:
        conditions = rule.get("conditions", [])
        if not conditions:
            continue
        
        all_met = True
        for cond in conditions:
            col = cond.get("col", cond.get("name", ""))
            op = cond.get("op", ">")
            val = cond.get("val", 0)
            
            feat_val = features.get(col)
            if feat_val is None:
                all_met = False
                break
            
            try:
                feat_val = float(feat_val)
                val = float(val) if not isinstance(val, bool) else val
            except (TypeError, ValueError):
                all_met = False
                break
            
            if op == "<" and not (feat_val < val):
                all_met = False; break
            elif op == ">" and not (feat_val > val):
                all_met = False; break
            elif op == "==" and feat_val != val:
                all_met = False; break
            elif op == "<=" and not (feat_val <= val):
                all_met = False; break
            elif op == ">=" and not (feat_val >= val):
                all_met = False; break
        
        if all_met:
            conf = float(rule.get("confidence", 0.5))
            if conf > best_confidence:
                best_confidence = conf
                direction = rule.get("direction", "HOLD")
                action = 1 if direction == "LONG" else (2 if direction == "SHORT" else 0)
                best_match = {
                    "action": action,
                    "direction": direction,
                    "sl_pct": float(rule.get("sl_pct", 0.02)),
                    "tp1_pct": float(rule.get("tp1_pct", 0.015)),
                    "tp2_pct": float(rule.get("tp2_pct", rule.get("tp_pct", 0.03))),
                    "rule_id": rule.get("id", "?"),
                    "reason": rule.get("reason", ""),
                    "confidence": conf,
                }
    
    if best_match:
        return best_match
    return {"action": 0, "rule_id": None, "reason": "no_match"}

from typing import Any

from app.smallcap_guards import (
    check_spread_guard, check_volume_gate, check_session_filter,
    compute_atr_sl_tp, check_pump_and_dump_risk, adjust_leverage_for_liquidity,
    check_token_killswitch, check_momentum_burst,
)

import torch  # type: ignore[import-untyped]
import pandas as pd
import numpy as np
from app.features.smc_features import SMCFeatureCalculator
from app.risk.cppi import RiskManager
from app.models.agent import QuantumAgent
from app.config import (
    AGENT_TYPE,
    DT_CONTEXT_LEN,
    DT_TARGET_RTG,
    PPO_WEIGHTS_PATH,
    PPO_PER_SYMBOL,
    PPO_WEIGHTS_DIR,
    PPO_LEARNING_MODE,
    PPO_CHUNK_WINDOW_HOURS,
    PPO_CHUNK_UPDATE_EVERY_HOURS,
    PPO_CHUNK_MIN_SAMPLES,
    PPO_CHUNK_MAX_SAMPLES,
    DT_WEIGHTS_PATH,
    DT_META_PATH,
    DATABASE_URL,
    get_cached_league_leverage
)
from app.models.decision_transformer import DTConfig, DecisionTransformer, DecisionTransformerAgent
from app.market_context import get_market_context
from app.state_schema import STATE_COLUMNS as _CANONICAL_STATE_COLUMNS, V3_INDICATOR_COLS as _CANONICAL_V3, V4_INDICATOR_COLS as _CANONICAL_V4


def _safe_float(val: object, default: float | None = None) -> float | None:
    try:
        if val is None:
            return default
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

def _json_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
        if np.isfinite(f):
            return f
    except (TypeError, ValueError):
        pass
    return None

logger = logging.getLogger(__name__)


class QuantumEngine:
    def __init__(self, initial_capital: float = 10000.0, *, symbol: str | None = None) -> None:
        self.capital = initial_capital
        self.portfolio_value = initial_capital

        self.symbol = str(symbol) if symbol is not None else None
        
        # Shared calendar path
        self.market_context = get_market_context("/srv/profitlab_ai_link/config/event_calendar_usd_high_plus_holidays.csv")
        
        self.feature_calculator = SMCFeatureCalculator()
        self.risk_manager = RiskManager()
        self.risk_manager.set_initial_capital(initial_capital)
        
        # Input dim: OHLCV (5) + SMC Features (approx 14)
        # We need to dynamically determine input_dim or fix it.
        # Let's check the number of features generated by SMCFeatureCalculator
        # For now, we'll use a larger number and pad/truncate or just re-initialize if needed.
        # But better: The agent expects a fixed input size.
        # Let's count the columns in smc_features.py:
        # open, high, low, close, volume (5)
        # fvg_bull_size, fvg_bear_size, is_fvg_bull, is_fvg_bear (4)
        # is_ob_bull, is_ob_bear, ob_top, ob_bottom, ob_bull_top, ob_bull_bottom, ob_bear_top, ob_bear_bottom (8)
        # is_sweep_high, is_sweep_low (2)
        # We build an explicit, stable state vector:
        # 5 OHLCV + 4 FVG + 2 sweeps + 8 OB proximity/freshness + 2 HTF context + 4 Golden Hour = 25
        self.state_columns = list(_CANONICAL_STATE_COLUMNS)
        self.input_dim = len(self.state_columns)  # 56 (V4)

        def _safe_symbol_for_path(sym: str) -> str:
            s = (sym or "").strip().upper()
            out: list[str] = []
            for ch in s:
                if ch.isalnum() or ch in ("-", "_", "."):
                    out.append(ch)
                else:
                    out.append("_")
            return "".join(out) or "UNKNOWN"

        def _ppo_weights_path() -> Path:
            if bool(PPO_PER_SYMBOL) and self.symbol:
                sym = _safe_symbol_for_path(self.symbol)
                return Path(str(PPO_WEIGHTS_DIR)) / sym / "ppo.pt"
            return Path(str(PPO_WEIGHTS_PATH))

        self._init_agent(_ppo_weights_path)
        
        # Learning State
        self.prev_state = None
        self.prev_action = None
        self.prev_price = None
        self.prev_log_prob = None
        self.prev_value = None
        self._returns_window = []
        self._returns_window_maxlen = 120

        # Chunked learning schedule (per engine/per symbol)
        self._last_train_ts_ms: int | None = self._load_last_train_ts()

        # Cooldown post-SL (evitar revenge trading)
        self._cooldown_until_ts_ms: int = 0


    def _load_last_train_ts(self) -> int | None:
        """Load last training timestamp from DB for this symbol."""
        if not self.symbol:
            return None
        try:
            import psycopg2  # type: ignore[import-untyped]
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute(
                "SELECT EXTRACT(EPOCH FROM trained_at) * 1000 "
                "FROM ppo_training_log WHERE symbol = %s "
                "ORDER BY trained_at DESC LIMIT 1",
                (self.symbol,),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return int(row[0])
        except Exception:
            pass
        return None

    def _init_agent(self, _ppo_weights_path: Callable[[], Path]) -> None:
        """Initialize the trading agent (DT or PPO)."""
        if AGENT_TYPE == "decision_transformer":
            self._init_decision_transformer()
        else:
            self._init_ppo_agent(_ppo_weights_path)

    def _init_decision_transformer(self) -> None:
        """Initialize Decision Transformer agent."""
        dt_cfg = DTConfig(state_dim=self.input_dim, act_dim=3, context_len=int(DT_CONTEXT_LEN))
        meta_path = Path(str(DT_META_PATH))
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                dt_cfg = DTConfig(
                    state_dim=self.input_dim, act_dim=3,
                    context_len=int(meta.get("context_len", DT_CONTEXT_LEN)),
                    d_model=int(meta.get("d_model", 128)),
                    nhead=int(meta.get("nhead", 4)),
                    nlayer=int(meta.get("nlayer", 3)),
                )
            except Exception:
                pass
        dt_model = DecisionTransformer(dt_cfg)
        weights_path = Path(str(DT_WEIGHTS_PATH))
        if weights_path.exists():
            try:
                dt_model.load_state_dict(torch.load(str(weights_path), map_location="cpu"))  # type: ignore[arg-type]
            except Exception:
                pass
        self.agent: QuantumAgent | DecisionTransformerAgent = DecisionTransformerAgent(dt_model, target_rtg=float(DT_TARGET_RTG))

    def _init_ppo_agent(self, _ppo_weights_path: Callable[[], Path]) -> None:
        """Initialize PPO agent with optional weight loading."""
        weights_path = _ppo_weights_path()
        autosave_every = 1 if str(PPO_LEARNING_MODE).strip().lower() == "chunked" else None
        self.agent = QuantumAgent(
            input_dim=self.input_dim, action_dim=3,
            autosave_path=str(weights_path),
            autosave_every_updates=autosave_every,
            db_url=DATABASE_URL if str(PPO_LEARNING_MODE).strip().lower() == "chunked" else None,
            symbol=self.symbol,
        )
        if weights_path.exists():
            try:
                self.agent.load(str(weights_path))  # type: ignore[arg-type]
            except Exception:
                pass
            return
        # Bootstrap from legacy global weights if per-symbol missing
        try:
            legacy = Path(str(PPO_WEIGHTS_PATH))
            if legacy.exists():
                self.agent.load(str(legacy))  # type: ignore[arg-type]
        except Exception:
            pass
    def _should_train(self, now_ts_ms: int) -> int | None:
        """Check if chunked training should run. Returns every_ms or None."""
        if not bool(getattr(self.agent, "is_on_policy", True)):
            return None
        if str(PPO_LEARNING_MODE).strip().lower() != "chunked":
            return None
        try:
            window_h = float(PPO_CHUNK_WINDOW_HOURS)
            every_h = float(PPO_CHUNK_UPDATE_EVERY_HOURS)
        except Exception:
            return None
        if window_h <= 0 or every_h <= 0:
            return None

        every_ms = int(every_h * 3600.0 * 1000.0)
        min_ts_ms = int(now_ts_ms) - int(window_h * 3600.0 * 1000.0)

        if hasattr(self.agent, "prune_memory"):
            try:
                self.agent.prune_memory(min_ts_ms=int(min_ts_ms))  # type: ignore[union-attr]
            except Exception:
                pass

        if self._last_train_ts_ms is None:
            self._last_train_ts_ms = int(now_ts_ms)
            return None
        if int(now_ts_ms) - int(self._last_train_ts_ms) < every_ms:
            return None
        return every_ms

    def maybe_train(self, *, now_ts_ms: int) -> bool:
        """Chunked PPO training: rolling buffer updated every PPO_CHUNK_UPDATE_EVERY_HOURS.

        IMPORTANT: _should_train() has side-effects (sets _last_train_ts_ms on first call).
        Cache the result in a local variable to avoid calling it twice — a second call
        would see 0ms elapsed and return None, silently blocking all training.
        """
        should = self._should_train(now_ts_ms)  # cache — do NOT call again below
        logger.info("[%s] maybe_train called: _should=%s, mem=%d, min=%d", self.symbol, should, len(getattr(self.agent, "memory", [])), max(32, int(PPO_CHUNK_MIN_SAMPLES)))
        if should is None:
            return False

        min_samples = max(32, int(PPO_CHUNK_MIN_SAMPLES))
        if len(getattr(self.agent, "memory", [])) < int(min_samples):
            return False

        max_samples = int(PPO_CHUNK_MAX_SAMPLES)
        if max_samples > 0 and len(self.agent.memory) > max_samples:  # type: ignore[union-attr]
            self.agent.memory = self.agent.memory[-max_samples:]  # type: ignore[union-attr]

        try:
            before = int(getattr(self.agent, "_update_count", 0) or 0)
            self.agent.update(clear_memory=False)  # type: ignore[union-attr]
            after = int(getattr(self.agent, "_update_count", 0) or 0)
            if after > before:
                self._last_train_ts_ms = int(now_ts_ms)
                logger.info("[%s] PPO chunked update #%d, memory=%d",
                            self.symbol, after, len(getattr(self.agent, "memory", [])))
                # NOTE: _reset_paper_stats removed — deleting trades destroyed
                # all history, prevented league leverage from advancing, and
                # eliminated the trade-outcome reward signal the PPO needs.
                return True
        except Exception:
            logger.exception("[%s] maybe_train failed", self.symbol)
        return False

    def _reset_paper_stats_for_symbol(self) -> None:
        """DISABLED — was deleting all paper_trades/positions every PPO update,
        destroying trade history and preventing the agent from learning from
        actual trade outcomes.  Kept as no-op for safety.
        """
        return
        
    # ── step() helper methods (extracted for readability) ──────────────

    def _compute_htf_context(self, htf_data: pd.DataFrame | None) -> tuple[float, float]:
        """Compute HTF bias and trend from 1-hour data."""
        htf_bias = 0.0
        htf_trend = 0.0
        if htf_data is not None and not htf_data.empty:
            try:
                htf_features = self.feature_calculator.calculate_all(htf_data)
                htf_state = htf_features.iloc[-1]
                bull = int(htf_state.get('is_ob_bull', 0)) + int(htf_state.get('is_fvg_bull', 0))
                bear = int(htf_state.get('is_ob_bear', 0)) + int(htf_state.get('is_fvg_bear', 0))
                htf_bias = float(np.clip(bull - bear, -2, 2))
                try:
                    htf_close = htf_data['close']
                    if len(htf_close) >= 13:
                        ref = float(htf_close.iloc[-13])
                        last = float(htf_close.iloc[-1])
                        if ref != 0:
                            htf_trend = float(np.clip((last - ref) / ref, -0.05, 0.05))
                except Exception:
                    pass
            except Exception:
                pass
        return htf_bias, htf_trend

    def _compute_time_features(self) -> tuple[float, float, float, float]:
        """Compute golden hour, cyclic time encoding, and liquidity context."""
        try:
            now_utc = pd.Timestamp.now(tz='UTC')
            hour_float = now_utc.hour + now_utc.minute / 60.0
            hour_sin = float(np.sin(2 * np.pi * hour_float / 24.0))
            hour_cos = float(np.cos(2 * np.pi * hour_float / 24.0))
            is_golden_hour = 1.0 if (14.5 <= hour_float <= 17.0) else 0.0
            if (7.0 <= hour_float <= 9.0) or (21.0 <= hour_float <= 23.0):
                is_golden_hour = 0.5
            try:
                m_status = self.market_context.get_status(now_utc)
                liquidity_score = float(m_status.liquidity_score)
            except Exception:
                liquidity_score = 0.5
        except Exception:
            hour_sin = 0.0
            hour_cos = 1.0
            is_golden_hour = 0.0
            liquidity_score = 0.5
        return hour_sin, hour_cos, is_golden_hour, liquidity_score

    @staticmethod
    def _compute_oscillators(
        close: pd.Series, high: pd.Series, low: pd.Series,
        volume: pd.Series, n: int, px: float, row: dict[str, Any],
    ) -> None:
        """Compute MACD, BB, Stochastic, ADX oscillators into row."""
        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12).mean()  # type: ignore[arg-type]
        ema26 = close.ewm(span=26).mean()  # type: ignore[arg-type]
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()  # type: ignore[arg-type]
        row['macd_signal_dist'] = float((macd.iloc[-1] - signal.iloc[-1]) / (px + 1e-10)) if n > 26 else 0.0
        # FIX Bug#5: macd_histogram was a duplicate of macd_signal_dist.
        # Now stores the raw MACD line value (not MACD-signal distance) — genuinely different.
        row['macd_histogram'] = float(macd.iloc[-1] / (px + 1e-10)) if n > 26 else 0.0

        # Bollinger Bands (20, 2)
        if n >= 20:
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_range = float((bb_mid.iloc[-1] + 2 * bb_std.iloc[-1]) - (bb_mid.iloc[-1] - 2 * bb_std.iloc[-1]))
            row['bb_position'] = float((px - (bb_mid.iloc[-1] - 2 * bb_std.iloc[-1])) / (bb_range + 1e-10))
            row['bb_width'] = float(bb_range / (bb_mid.iloc[-1] + 1e-10))
        else:
            row['bb_position'] = 0.5
            row['bb_width'] = 0.0

        # Stochastic (14, 3)
        if n >= 14:
            low14 = low.rolling(14).min()
            high14 = high.rolling(14).max()
            stoch_k = (close - low14) / (high14 - low14 + 1e-10)
            row['stoch_k'] = float((stoch_k.iloc[-1] - 0.5) * 2)
            row['stoch_d'] = float((stoch_k.rolling(3).mean().iloc[-1] - 0.5) * 2) if n >= 16 else 0.0
        else:
            row['stoch_k'] = 0.0
            row['stoch_d'] = 0.0

        # ADX (14)
        if n >= 28:
            plus_dm = high.diff().clip(lower=0)  # type: ignore[arg-type]
            minus_dm = (-low.diff()).clip(lower=0)  # type: ignore[arg-type]
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr14 = tr.rolling(14).mean()
            plus_di = (plus_dm.rolling(14).mean() / (atr14 + 1e-10)) * 100
            minus_di = (minus_dm.rolling(14).mean() / (atr14 + 1e-10)) * 100
            dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
            row['adx_normalized'] = float(dx.rolling(14).mean().iloc[-1] / 100.0)
        else:
            row['adx_normalized'] = 0.0

    @staticmethod
    def _compute_volume_price_features(
        close: pd.Series, high: pd.Series, low: pd.Series,
        volume: pd.Series, n: int, px: float, row: dict[str, Any],
    ) -> None:
        """Compute OBV, VWAP, price changes, structure, volume momentum into row."""
        # OBV slope
        if n >= 20:
            obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()  # type: ignore[union-attr]
            obv_ma = obv.rolling(20).mean()  # type: ignore[union-attr]
            row['obv_slope'] = float((obv.iloc[-1] - obv_ma.iloc[-1]) / (abs(obv_ma.iloc[-1]) + 1e-10))  # type: ignore[union-attr]
        else:
            row['obv_slope'] = 0.0

        # VWAP distance (rolling 288 ~ 1 day of 5m candles)
        if n >= 50:
            tp = (high + low + close) / 3
            window = min(288, n)
            cum_vol = volume.rolling(window).sum()
            vwap = (tp * volume).rolling(window).sum() / (cum_vol + 1e-10)
            row['vwap_dist'] = float((px - vwap.iloc[-1]) / (px + 1e-10))
        else:
            row['vwap_dist'] = 0.0

        # Multi-TF price changes
        row['price_change_1h'] = float(close.pct_change(12).iloc[-1]) if n > 12 else 0.0
        row['price_change_4h'] = float(close.pct_change(48).iloc[-1]) if n > 48 else 0.0

        # Candle structure
        row['high_low_ratio'] = float((high.iloc[-1] - low.iloc[-1]) / (px + 1e-10))
        row['close_position'] = float((px - low.iloc[-1]) / (high.iloc[-1] - low.iloc[-1] + 1e-10))
        row['volume_momentum'] = float(volume.pct_change(5).iloc[-1]) if n > 5 else 0.0

    @staticmethod
    def _compute_v4_momentum(
        close: pd.Series, high: pd.Series, low: pd.Series,
        volume: pd.Series, n: int, px: float, row: dict[str, Any],
    ) -> None:
        """V4 momentum indicators: RSI, Williams %R, CCI, MFI."""
        # RSI (14) using Wilder's EMA smoothing, normalized to [-1, 1].
        # FIX Bug#5: V2 rsi_normalized uses SMA-based RSI. This uses Wilder's EWM
        # (alpha=1/14), which produces different values — eliminates the duplicate.
        if n >= 15:
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()  # type: ignore[arg-type]
            loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()  # type: ignore[arg-type]
            rs = gain / (loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))
            row['rsi_14'] = float((rsi.iloc[-1] - 50) / 50)
        else:
            row['rsi_14'] = 0.0

        # Williams %R (14) normalized to [-1, 1]
        if n >= 14:
            high14 = high.rolling(14).max()
            low14 = low.rolling(14).min()
            wr = (high14.iloc[-1] - px) / (high14.iloc[-1] - low14.iloc[-1] + 1e-10)
            row['williams_r'] = float((wr - 0.5) * 2)
        else:
            row['williams_r'] = 0.0

        # CCI (20) normalized: CCI/200 clamped to [-1, 1]
        if n >= 20:
            tp = (high + low + close) / 3
            tp_mean = tp.rolling(20).mean()
            tp_mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)  # type: ignore[arg-type]
            cci = (tp.iloc[-1] - tp_mean.iloc[-1]) / (0.015 * tp_mad.iloc[-1] + 1e-10)
            row['cci_normalized'] = float(np.clip(cci / 200, -1, 1))
        else:
            row['cci_normalized'] = 0.0

        # MFI (14) normalized to [-1, 1]
        if n >= 15:
            tp = (high + low + close) / 3
            mf = tp * volume
            delta_tp = tp.diff()
            pos_mf = (mf * (delta_tp > 0).astype(float)).rolling(14).sum()
            neg_mf = (mf * (delta_tp <= 0).astype(float)).rolling(14).sum()
            mfi = 100 - (100 / (1 + pos_mf / (neg_mf + 1e-10)))
            row['mfi_normalized'] = float((mfi.iloc[-1] - 50) / 50)
        else:
            row['mfi_normalized'] = 0.0

    @staticmethod
    def _compute_v4_volatility(
        close: pd.Series, high: pd.Series, low: pd.Series,
        n: int, px: float, row: dict[str, Any],
    ) -> None:
        """V4 volatility indicators: ATR%, Keltner, Squeeze, EMA9 dist."""
        # ATR% (14) — volatility as % of price
        if n >= 15:
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            row['atr_pct_14'] = float(atr.iloc[-1] / (px + 1e-10))
        else:
            row['atr_pct_14'] = 0.0

        # Keltner Channel position [0, 1] + Squeeze
        if n >= 20:
            ema20 = close.ewm(span=20).mean()  # type: ignore[arg-type]
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr20 = tr.rolling(20).mean()
            kc_upper = ema20 + 2 * atr20
            kc_lower = ema20 - 2 * atr20
            kc_range = float(kc_upper.iloc[-1] - kc_lower.iloc[-1])
            row['keltner_position'] = float((px - kc_lower.iloc[-1]) / (kc_range + 1e-10))

            # Squeeze: BB inside tighter Keltner = low vol about to expand
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = bb_mid.iloc[-1] + 2 * bb_std.iloc[-1]
            bb_lower = bb_mid.iloc[-1] - 2 * bb_std.iloc[-1]
            kc_up_tight = ema20.iloc[-1] + 1.5 * atr20.iloc[-1]
            kc_lo_tight = ema20.iloc[-1] - 1.5 * atr20.iloc[-1]
            row['squeeze_on'] = float(bb_lower > kc_lo_tight and bb_upper < kc_up_tight)
        else:
            row['keltner_position'] = 0.5
            row['squeeze_on'] = 0.0

        # Price distance from EMA 9 (scalping signal)
        if n >= 10:
            ema9 = close.ewm(span=9).mean()  # type: ignore[arg-type]
            row['ema_9_dist'] = float((px - ema9.iloc[-1]) / (px + 1e-10))
        else:
            row['ema_9_dist'] = 0.0

    _V3_INDICATOR_COLS = _CANONICAL_V3
    _V4_INDICATOR_COLS = _CANONICAL_V4

    def _compute_indicators(self, market_data: pd.DataFrame, row: dict[str, Any]) -> None:
        """Compute V3+V4 institutional technical indicators, modifying *row* in-place."""
        try:
            close = market_data['close'].astype(float)
            high = market_data['high'].astype(float)
            low = market_data['low'].astype(float)
            volume = market_data['volume'].astype(float)
            n = len(close)
            px = float(close.iloc[-1]) if n > 0 else 1.0

            self._compute_oscillators(close, high, low, volume, n, px, row)
            self._compute_volume_price_features(close, high, low, volume, n, px, row)
            self._compute_v4_momentum(close, high, low, volume, n, px, row)
            self._compute_v4_volatility(close, high, low, n, px, row)
        except Exception:
            for col in self._V3_INDICATOR_COLS + self._V4_INDICATOR_COLS:
                row[col] = row.get(col, 0.0)

    def _build_state_vector(self, row: dict[str, Any] | pd.Series) -> np.ndarray:  # type: ignore[type-arg]
        """Build and normalize the state vector from the enriched feature row."""
        state_values: list[float] = []
        for col in self.state_columns:
            try:
                v = row.get(col, 0.0)
                if v is None or (isinstance(v, float) and not np.isfinite(v)):
                    v = 0.0
                state_values.append(float(v))
            except Exception:
                state_values.append(0.0)
        state_vector = np.array(state_values, dtype=np.float32)
        finite = np.isfinite(state_vector)
        if finite.any():
            scale = float(np.median(np.abs(state_vector[finite])))
        else:
            scale = 1.0
        if not np.isfinite(scale) or scale <= 1e-8:
            scale = 1.0
        return np.clip(state_vector / scale, -10.0, 10.0)

    def _reward_entry_quality(self, current_state: dict[str, Any] | pd.Series, current_price: float) -> float:
        """Bonus for entries near OB/FVG zones."""
        try:
            bull_dist = float(current_state.get('bull_ob_distance', 999) or 999)
            bear_dist = float(current_state.get('bear_ob_distance', 999) or 999)
            px = float(current_price) if current_price else 1.0
            prox_threshold = px * 0.005
            if ((self.prev_action == 1 and bull_dist < prox_threshold)
                    or (self.prev_action == 2 and bear_dist < prox_threshold)):
                return 0.3
        except Exception:
            pass
        return 0.0

    def _reward_htf_alignment(self, current_state: dict[str, Any] | pd.Series) -> float:
        """Bonus/penalty for HTF trend alignment."""
        try:
            htf_trend_val = float(current_state.get('htf_trend', 0) or 0)
            if self.prev_action == 1 and htf_trend_val > 0.002:
                return 0.2
            if self.prev_action == 2 and htf_trend_val < -0.002:
                return 0.2
            if self.prev_action == 1 and htf_trend_val < -0.003:
                return -0.3
            if self.prev_action == 2 and htf_trend_val > 0.003:
                return -0.3
        except Exception:
            pass
        return 0.0

    def _reward_hold(self, pct_change: float, current_state: dict[str, Any] | pd.Series) -> float:
        """Reward for correct HOLD decisions.

        Penalize holding during strong moves (missed opportunity).
        Reward holding during choppy/low-vol conditions (patience).
        """
        if self.prev_action != 0:
            return 0.0
        # Tiny bonus for holding during low-volatility (correct patience)
        # Kept small (0.005) so it doesn't compete with the directional reward signal.
        # A large HOLD bonus biases the PPO toward inaction (AVAX/LINK/LTC always HOLD).
        if abs(pct_change) < 0.001:
            return 0.005
        # Penalize missing obvious trends (large moves while sitting out)
        if abs(pct_change) > 0.005:
            return -0.1
        return 0.0

    def _reward_momentum_quality(self, current_state: dict[str, Any] | pd.Series) -> float:
        """Bonus for entering during squeeze fire or strong momentum.

        Squeeze fire (BB was inside KC, now expanding) = high probability move.
        ADX > 0.5 = strong trend, good for directional entries.
        """
        if self.prev_action == 0:
            return 0.0
        bonus = 0.0
        try:
            squeeze_on = float(current_state.get('squeeze_on', 0) or 0)
            adx = float(current_state.get('adx_normalized', 0) or 0)
            # Entering right as squeeze fires = great timing
            if squeeze_on > 0.5:
                bonus += 0.15
            # Strong trend confirmation
            if adx > 0.5:
                bonus += 0.1
        except Exception:
            pass
        return bonus

    def _compute_reward_and_learn(
        self, current_price: float, current_state: dict[str, Any] | pd.Series, now_ts_ms: int,
    ) -> None:
        """Compute multi-factor PPO reward for previous step and store transition.

        Reward components:
        1. Base: realized return × 100 (directional correctness)
        2. Entry quality: OB/FVG proximity bonus
        3. HTF alignment: trend confirmation bonus/penalty
        4. Hold quality: patience vs missed opportunity
        5. Momentum quality: squeeze/ADX entry timing bonus
        """
        if not (bool(getattr(self.agent, "is_on_policy", True))
                and self.prev_state is not None  # type: ignore[redundant-expr]
                and self.prev_action is not None):
            return
        pct_change = (current_price - self.prev_price) / self.prev_price if self.prev_price else 0.0

        if self.prev_action == 1:  # Long
            realized_r = float(pct_change)
        elif self.prev_action == 2:  # Short
            realized_r = float(-pct_change)
        else:  # Hold
            realized_r = 0.0

        # Multi-factor reward
        # Amplified from 100x → 200x so a 0.3% directional move gives base_reward=0.6,
        # dominating zone bonuses (max ~0.3) and giving the PPO a clearer learning signal.
        base_reward = realized_r * 200.0
        reward = (base_reward
                  + self._reward_entry_quality(current_state, current_price)
                  + self._reward_htf_alignment(current_state)
                  + self._reward_hold(pct_change, current_state)
                  + self._reward_momentum_quality(current_state))

        # Store transition
        if hasattr(self.agent, "remember"):
            try:
                self.agent.remember(  # type: ignore[union-attr]
                    self.prev_state, self.prev_action, float(reward), False,  # type: ignore[arg-type]
                    self.prev_log_prob, self.prev_value, int(now_ts_ms))  # type: ignore[arg-type]
            except TypeError:
                self.agent.remember(  # type: ignore[union-attr]
                    self.prev_state, self.prev_action, float(reward), False,  # type: ignore[arg-type]
                    self.prev_log_prob, self.prev_value)  # type: ignore[arg-type]

        # Online learning mode: update immediately
        if str(PPO_LEARNING_MODE).strip().lower() == "online":
            if hasattr(self.agent, "update"):
                self.agent.update(clear_memory=True)  # type: ignore[union-attr]

    @staticmethod
    def _zone_pair(
        state: dict[str, Any] | pd.Series,
        dist_key: str, age_key: str, mit_key: str,
        fvg_dist_key: str, fvg_age_key: str, fvg_mit_key: str,
        prox_limit: float,
    ) -> tuple[float, int, float, int, float | None, float, int, int, bool, bool]:
        """Extract one side (bull or bear) of SMC zone data."""
        dist = float(state.get(dist_key, 999) or 999)
        near = int(dist < prox_limit)
        age = float(state.get(age_key, 0.0) or 0.0)
        mit = int(state.get(mit_key, 0) or 0)
        fvg_dist = _safe_float(state.get(fvg_dist_key))
        fvg_age = float(state.get(fvg_age_key, 0.0) or 0.0)
        fvg_mit = int(state.get(fvg_mit_key, 0) or 0)
        fvg_ok = int(fvg_dist is not None and fvg_dist < prox_limit)
        valid_ob = (near == 1) and (mit == 0)
        valid_fvg = (fvg_ok == 1) and (fvg_mit == 0)
        return dist, near, age, mit, fvg_dist, fvg_age, fvg_mit, fvg_ok, valid_ob, valid_fvg

    def _extract_smc_zones(self, current_state: dict[str, Any] | pd.Series, current_price: float) -> dict[str, Any]:
        """Extract SMC zone data (OB, FVG, sweeps) for confluence analysis."""
        px = float(current_price) if current_price else 0.0
        prox_limit = px * 0.003
        sweep_low = int(current_state.get('is_sweep_low', 0) or 0)
        sweep_high = int(current_state.get('is_sweep_high', 0) or 0)

        bd, nbo, boa, bom, fbd, fba, fbm, fbok, vbo, vbf = self._zone_pair(
            current_state, 'bull_ob_distance', 'bull_ob_age', 'bull_ob_mitigated',
            'fvg_bull_distance', 'fvg_bull_age', 'fvg_bull_mitigated', prox_limit)
        ed, neo, eoa, eom, fed, fea, fem, feok, veo, vef = self._zone_pair(
            current_state, 'bear_ob_distance', 'bear_ob_age', 'bear_ob_mitigated',
            'fvg_bear_distance', 'fvg_bear_age', 'fvg_bear_mitigated', prox_limit)

        return {
            'near_bull_ob': nbo, 'near_bear_ob': neo,
            'bull_ob_dist': bd, 'bear_ob_dist': ed,
            'bull_ob_age': boa, 'bear_ob_age': eoa,
            'bull_ob_mit': bom, 'bear_ob_mit': eom,
            'fvg_bull_dist': fbd, 'fvg_bear_dist': fed,
            'fvg_bull_age': fba, 'fvg_bear_age': fea,
            'fvg_bull_mit': fbm, 'fvg_bear_mit': fem,
            'fvg_bull_ok': fbok, 'fvg_bear_ok': feok,
            'sweep_low': sweep_low, 'sweep_high': sweep_high,
            'has_bull_setup': bool(sweep_low or vbo or vbf),
            'has_bear_setup': bool(sweep_high or veo or vef),
        }

    @staticmethod
    def _trend_filter(htf_trend: float) -> tuple[int, int]:
        """Return (allow_long, allow_short) based on HTF trend.

        Threshold raised from 0.003 to 0.010 so only meaningful trend moves
        block counter-trend entries (avoids false filters on noise).
        """
        threshold = 0.010
        if htf_trend < -threshold:
            print(f"Trend Filter: DOWNTREND ({htf_trend:.4f}) -> LONG blocked")
            return 0, 1
        if htf_trend > threshold:
            print(f"Trend Filter: UPTREND ({htf_trend:.4f}) -> SHORT blocked")
            return 1, 0
        return 1, 1

    @staticmethod
    def _log_blocked_trade(
        action: int, prob: float, conf_thr: float,
        allow: int, score: int, min_conf: int,
    ) -> None:
        """Log why a trade was blocked."""
        reasons: list[str] = []
        if prob <= conf_thr:
            reasons.append(f"conf={prob:.3f}<{conf_thr}")
        if allow == 0:
            reasons.append("counter-trend")
        if score < min_conf:
            reasons.append(f"score={score}<{min_conf}")
        name = "LONG" if action == 1 else "SHORT"
        print(f"  {name} BLOCKED -> HOLD: {', '.join(reasons)}")

    def _make_trade_decision(
        self, action: int, probs: list[float], htf_trend: float, zones: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        """Apply trend + confidence + confluence gates. Returns (final_action, scores dict)."""
        prob_long, prob_short = probs[1], probs[2]
        allow_long, allow_short = self._trend_filter(htf_trend)

        # [BESTIA v3] Filtro profesional: el PPO debe DEMOSTRAR convicción + confluencia SMC
        long_score = sum([htf_trend > 0.005, zones['has_bull_setup'], prob_long > 0.45, prob_long > 0.55])
        short_score = sum([htf_trend < -0.005, zones['has_bear_setup'], prob_short > 0.45, prob_short > 0.55])

        conf_thr = 0.45  # Requiere convicción real del PPO (no random)
        min_conf = 2    # Mínimo 2 factores de confluencia para disparar
        final_action = 0

        if action == 1 and prob_long > conf_thr and allow_long and long_score >= min_conf:
            final_action = 1
            print(f"  LONG APPROVED: prob={prob_long:.3f}, allow={allow_long}, score={long_score}/4")
        elif action == 2 and prob_short > conf_thr and allow_short and short_score >= min_conf:
            final_action = 2
            print(f"  SHORT APPROVED: prob={prob_short:.3f}, allow={allow_short}, score={short_score}/4")
        elif action == 1:
            self._log_blocked_trade(1, prob_long, conf_thr, allow_long, long_score, min_conf)
        elif action == 2:
            self._log_blocked_trade(2, prob_short, conf_thr, allow_short, short_score, min_conf)

        return final_action, {
            'long_score': long_score, 'short_score': short_score,
            'allow_long': allow_long, 'allow_short': allow_short,
        }

    def _apply_confluence_filter(
        self, action: int, probs: list[float], htf_trend: float,
        current_state: dict[str, Any] | pd.Series, current_price: float,
    ) -> dict[str, Any]:
        """Apply trend + SMC + confidence gating. Returns dict with filtered action and reporting vars."""
        zones = self._extract_smc_zones(current_state, current_price)
        final_action, scores = self._make_trade_decision(action, probs, htf_trend, zones)

        result = dict(zones)
        result['action'] = final_action
        result.update(scores)
        return result

    def _get_market_event_context(self) -> tuple[float, bool]:
        """Get event risk and pause status from market context."""
        try:
            m_status = self.market_context.get_status(pd.Timestamp.now(tz='UTC'))
            return float(m_status.position_size_multiplier), "pause" in str(m_status.trading_mode).lower()
        except Exception:
            return 1.0, False

    def _compute_margin_cap(self, setup_quality: float) -> float:
        """Calculate CPPI margin cap with institutional confidence override."""
        cushion = float(self.portfolio_value - float(self.risk_manager.floor_value or 0.0))
        cap = float(self.risk_manager.cppi_multiplier) * max(0.0, cushion)
        cap = float(np.clip(cap, 0.0, float(self.portfolio_value)))
        min_margin = 10.0
        if cap < min_margin and self.portfolio_value > (min_margin * 2.0):
            if setup_quality >= 0.40:
                print(f"Risk Override: Upgrading margin to ${min_margin} due to High Confidence ({setup_quality:.2f})")
                return min_margin
            if cap < 1.0:
                return 0.0
        return cap

    def _compute_leverage(self, margin_usd: float, desired_notional: float, max_leverage: float) -> float:
        """Fixed leverage — replica exacta de lo que usaríamos en real (5x)."""
        return get_cached_league_leverage()  # type: ignore[return-value]

    def _compute_risk_sizing(
        self, action: int, market_data: pd.DataFrame, long_score: int, short_score: int,
    ) -> dict[str, Any]:
        """CPPI + vol targeting + league leverage sizing."""
        event_mult, is_paused = self._get_market_event_context()

        ann_factor = 324.2
        current_vol = market_data['close'].pct_change().rolling(window=20).std().iloc[-1] * ann_factor
        if np.isnan(current_vol):
            current_vol = 0.60

        # Hard brakes
        if self.risk_manager.floor_value is not None and self.portfolio_value <= self.risk_manager.floor_value:
            action = 0
        if is_paused:
            action = 0

        max_leverage = 10.0
        setup_quality = max(0.25, float(np.clip(float(max(long_score, short_score)) / 4.0, 0.0, 1.0)))
        margin_cap_usd = self._compute_margin_cap(setup_quality)

        desired_notional_raw = float(self.risk_manager.calculate_vol_targeting_position(current_vol, self.portfolio_value))
        desired_notional = float(desired_notional_raw) * float(setup_quality) * event_mult

        safe_size = float(min(desired_notional_raw, margin_cap_usd * max_leverage)) if margin_cap_usd > 0 else 0.0

        if action == 0 or margin_cap_usd <= 0.0:
            margin_usd, leverage, notional_usd = 0.0, 1.0, 0.0
        else:
            margin_usd = float(margin_cap_usd)
            leverage = self._compute_leverage(margin_usd, desired_notional, max_leverage)
            notional_usd = margin_usd * leverage

        print(f"Action: {action}, Margin: {margin_usd:.2f}, Lev: {leverage:.2f}x, Notional: {notional_usd:.2f}, Portfolio: {self.portfolio_value:.2f}")

        return {
            'action': action, 'margin_usd': margin_usd, 'leverage': leverage,
            'notional_usd': notional_usd, 'safe_size': safe_size,
            'setup_quality': setup_quality, 'current_vol': current_vol,
        }

    @staticmethod
    def _sl_tp_long(
        px: float, pct_buf: float,
        ob_bottom: float | None, ob_top: float | None,
        recent_low: float | None, recent_high: float | None,
    ) -> tuple[float | None, float | None]:
        """Compute SL/TP for a LONG trade."""
        sl = None
        if ob_bottom is not None and ob_top is not None and ob_bottom > 0:
            buf = max(pct_buf, 0.50 * max(0.0, float(ob_top - ob_bottom)))
            sl = float(ob_bottom - buf)
        elif recent_low is not None:
            sl = float(recent_low - pct_buf)
        tp = float(recent_high) if recent_high is not None else None
        if sl is not None:
            risk = float(px - sl)
            if risk > 0 and (tp is None or tp <= px):
                tp = float(px + 2.0 * risk)
        return sl, tp

    @staticmethod
    def _sl_tp_short(
        px: float, pct_buf: float,
        ob_top: float | None, ob_bottom: float | None,
        recent_high: float | None, recent_low: float | None,
    ) -> tuple[float | None, float | None]:
        """Compute SL/TP for a SHORT trade."""
        sl = None
        if ob_top is not None and ob_bottom is not None and ob_top > 0:
            buf = max(pct_buf, 0.50 * max(0.0, float(ob_top - ob_bottom)))
            sl = float(ob_top + buf)
        elif recent_high is not None:
            sl = float(recent_high + pct_buf)
        tp = float(recent_low) if recent_low is not None else None
        if sl is not None:
            risk = float(sl - px)
            if risk > 0 and (tp is None or tp >= px):
                tp = float(px - 2.0 * risk)
        return sl, tp

    def _place_structural_sl_tp(
        self, action: int, px: float,
        current_state: dict[str, Any] | pd.Series, market_data: pd.DataFrame,
    ) -> tuple[float | None, float | None]:
        """Place SL/TP based on OB zones and swing liquidity pools."""
        try:
            recent_high = float(market_data['high'].iloc[-21:-1].max())
            recent_low = float(market_data['low'].iloc[-21:-1].min())
        except Exception:
            recent_high = None
            recent_low = None

        pct_buf = abs(px) * 0.005
        if action == 1:
            return self._sl_tp_long(
                px, pct_buf,
                _safe_float(current_state.get('active_ob_bull_bottom'), default=None),
                _safe_float(current_state.get('active_ob_bull_top'), default=None),
                recent_low, recent_high)
        if action == 2:
            return self._sl_tp_short(
                px, pct_buf,
                _safe_float(current_state.get('active_ob_bear_top'), default=None),
                _safe_float(current_state.get('active_ob_bear_bottom'), default=None),
                recent_high, recent_low)
        return None, None

    @staticmethod
    def _widen_if_needed(
        px: float, level: float, min_pct: float, is_long: bool, is_sl: bool,
    ) -> float:
        """Widen SL or TP to minimum distance if too close."""
        dist_pct = abs(px - level) / px
        if dist_pct >= min_pct:
            return level
        label = "SL" if is_sl else "TP"
        reason = "noise filter" if is_sl else "fee coverage"
        print(f"{label} Widened: {dist_pct*100:.2f}% -> {min_pct*100:.1f}% ({reason})")
        if is_sl:
            return float(px * (1 - min_pct)) if is_long else float(px * (1 + min_pct))
        return float(px * (1 + min_pct)) if is_long else float(px * (1 - min_pct))

    def _enforce_sl_tp_limits(
        self, action: int, px: float,
        sl_price: float | None, tp_price: float | None,
    ) -> tuple[float | None, float | None]:
        """Enforce minimum SL/TP distances, direction validation, and R:R ratio.

        CRITICAL FIX 2026-03-02: Previously 70% of trades had SL on the WRONG
        side of entry (e.g. SL above entry for LONG). This alone caused the
        22.5% win-rate catastrophe.  Now we:
          1. Force SL to the correct side of entry price.
          2. Widen min SL from 0.5% → 1.5% (crypto 5m noise filter).
          3. Widen min TP from 1.0% → 3.0% (covers fees + gives room to run).
          4. Enforce min R:R 2.0:1 (was 1.5, insufficient after round-trip fees).
        """
        MIN_SL_PCT = 0.015   # 1.5% — survives normal 5m crypto noise
        MIN_TP_PCT = 0.015   # 1.5% — realistic target (was 3%, model never reached it)
        MIN_RR = 1.5         # R:R 1.5:1 (loosened to allow more viable setups)

        is_long = (action == 1)

        # ── STEP 0: Fix SL direction (CRITICAL) ──────────────────────
        if px > 0 and sl_price is not None:
            if is_long and sl_price >= px:
                # SL above entry for LONG → force below entry at minimum distance
                print(f"SL DIRECTION FIX: LONG SL {sl_price:.4f} >= entry {px:.4f} → forcing below")
                sl_price = float(px * (1 - MIN_SL_PCT))
            elif not is_long and sl_price <= px:
                # SL below entry for SHORT → force above entry at minimum distance
                print(f"SL DIRECTION FIX: SHORT SL {sl_price:.4f} <= entry {px:.4f} → forcing above")
                sl_price = float(px * (1 + MIN_SL_PCT))

        # ── STEP 0b: Fix TP direction ────────────────────────────────
        if px > 0 and tp_price is not None:
            if is_long and tp_price <= px:
                print(f"TP DIRECTION FIX: LONG TP {tp_price:.4f} <= entry {px:.4f} → forcing above")
                tp_price = float(px * (1 + MIN_TP_PCT))
            elif not is_long and tp_price >= px:
                print(f"TP DIRECTION FIX: SHORT TP {tp_price:.4f} >= entry {px:.4f} → forcing below")
                tp_price = float(px * (1 - MIN_TP_PCT))

        # ── STEP 1: Widen SL to minimum distance ─────────────────────
        if px > 0 and sl_price is not None:
            sl_price = self._widen_if_needed(px, sl_price, MIN_SL_PCT, is_long, is_sl=True)

        # ── STEP 2: Widen TP to minimum distance ─────────────────────
        if px > 0 and tp_price is not None:
            tp_price = self._widen_if_needed(px, tp_price, MIN_TP_PCT, is_long, is_sl=False)

        # ── STEP 3: R:R sanity check ─────────────────────────────────
        if sl_price is not None and tp_price is not None:
            risk_dist = abs(px - sl_price)
            if risk_dist > 0:
                rr = abs(tp_price - px) / risk_dist
                if rr < MIN_RR:
                    new_reward = risk_dist * MIN_RR
                    tp_price = float(px + new_reward) if is_long else float(px - new_reward)
                    print(f"R:R Fix: {rr:.2f} -> {MIN_RR} (TP widened to {tp_price:.2f})")
        return sl_price, tp_price

    def _compute_sl_tp(
        self, action: int, current_price: float,
        current_state: dict[str, Any] | pd.Series, market_data: pd.DataFrame,
    ) -> tuple[float | None, float | None]:
        """Compute SL/TP from SMC structures with minimum distance and R:R enforcement."""
        if action == 0:
            return None, None
        px = float(current_price) if current_price else 0.0
        sl_price, tp_price = self._place_structural_sl_tp(action, px, current_state, market_data)
        return self._enforce_sl_tp_limits(action, px, sl_price, tp_price)

    def _get_agent_metadata(self) -> tuple[str, int]:
        """Return (backbone, seq_len) for the active agent."""
        if AGENT_TYPE == "decision_transformer":
            return "decision_transformer", int(getattr(getattr(self.agent, "cfg", None), "context_len", 0) or int(DT_CONTEXT_LEN))
        backbone = "transformer_encoder" if bool(getattr(self.agent.model, "use_transformer", False)) else "mlp"  # type: ignore[union-attr]
        return backbone, int(getattr(self.agent, "seq_len", 0) or 0)

    @staticmethod
    def _extract_microstructure(microstructure: dict[str, Any] | None) -> dict[str, float | None]:
        """Extract microstructure fields from orderbook snapshot."""
        ms = microstructure or {}
        return {k: _safe_float(ms.get(k), default=None) for k in ("mid", "spread_bps", "imbalance", "bid_depth_usd", "ask_depth_usd")}

    @staticmethod
    def _state_float(state: dict[str, Any] | pd.Series, key: str, default: float = 0.0) -> float:
        """Safely extract a float from state dict."""
        return float(state.get(key, default) or default)

    @staticmethod
    def _state_int(state: dict[str, Any] | pd.Series, key: str) -> int:
        """Safely extract an int from state dict."""
        return int(state.get(key, 0) or 0)

    def _build_info_dict(
        self, action: int, symbol: str | None,
        htf_bias: float, htf_trend: float,
        current_state: dict[str, Any] | pd.Series,
        cf: dict[str, Any], risk: dict[str, Any],
        sl_price: float | None, tp_price: float | None,
        probs: list[float], microstructure: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the dashboard info dictionary."""
        action_str = ["HOLD", "LONG", "SHORT"][int(action)]
        backbone, seq_len = self._get_agent_metadata()
        ms = self._extract_microstructure(microstructure)

        s = current_state
        sf = self._state_float
        si = self._state_int

        return {
            "features": {
                "fvg_bull": si(s, 'is_fvg_bull'), "fvg_bear": si(s, 'is_fvg_bear'),
                "ob_bull": si(s, 'is_ob_bull'), "ob_bear": si(s, 'is_ob_bear'),
                "sweep_high": si(s, 'is_sweep_high'), "sweep_low": si(s, 'is_sweep_low'),
                "near_bull_ob": cf['near_bull_ob'], "near_bear_ob": cf['near_bear_ob'],
                "htf_bias": float(htf_bias), "htf_trend": float(htf_trend),
                "setup_long_score": cf['long_score'], "setup_short_score": cf['short_score'],
                "allow_long": cf['allow_long'], "allow_short": cf['allow_short'],
                "recommendation": action_str, "confidence": float(risk['setup_quality']),
                "analysis": f"{symbol or ''} | {action_str} | trend={htf_trend:.4f} | long_sc={cf['long_score']} short_sc={cf['short_score']}",
                "agent_backbone": backbone, "agent_seq_len": seq_len,
                "ms_mid": _json_float(ms["mid"]), "ms_spread_bps": _json_float(ms["spread_bps"]),
                "ms_imbalance": _json_float(ms["imbalance"]),
                "ms_bid_depth_usd": _json_float(ms["bid_depth_usd"]),
                "ms_ask_depth_usd": _json_float(ms["ask_depth_usd"]),
                "bull_ob_distance": _json_float(s.get('bull_ob_distance')),
                "bear_ob_distance": _json_float(s.get('bear_ob_distance')),
                "bull_ob_age": sf(s, 'bull_ob_age'), "bear_ob_age": sf(s, 'bear_ob_age'),
                "bull_ob_tests": sf(s, 'bull_ob_tests'), "bear_ob_tests": sf(s, 'bear_ob_tests'),
                "bull_ob_mitigated": si(s, 'bull_ob_mitigated'), "bear_ob_mitigated": si(s, 'bear_ob_mitigated'),
                "fvg_bull_distance": _json_float(s.get('fvg_bull_distance')),
                "fvg_bear_distance": _json_float(s.get('fvg_bear_distance')),
                "fvg_bull_age": sf(s, 'fvg_bull_age'), "fvg_bear_age": sf(s, 'fvg_bear_age'),
                "fvg_bull_tests": sf(s, 'fvg_bull_tests'), "fvg_bear_tests": sf(s, 'fvg_bear_tests'),
                "fvg_bull_mitigated": si(s, 'fvg_bull_mitigated'), "fvg_bear_mitigated": si(s, 'fvg_bear_mitigated'),
                "close_price": sf(s, 'close'),
            },
            "probs": probs,
            "orders": {"sl": sl_price, "tp": tp_price},
            "risk": {
                "volatility": float(risk.get('current_vol', 0.6)),
                "safe_size": float(risk['safe_size']),
                "margin_usd": float(risk['margin_usd']),
                "leverage": float(risk['leverage']),
                "notional_usd": float(risk['notional_usd']),
                "cppi_floor": float(self.risk_manager.floor_value or 0.0)
            },
        }

    def step(
        self,
        market_data: pd.DataFrame,
        htf_data: pd.DataFrame | None = None,
        symbol: str | None = None,
        microstructure: dict[str, Any] | None = None,
    ) -> tuple[int, float, dict[str, Any]]:
        """Execute one step of the trading loop."""
        # Timestamp for scheduling/training (prefer kline time)
        now_ts_ms = None
        try:
            if "time" in market_data.columns and len(market_data) > 0:
                now_ts_ms = int(market_data["time"].iloc[-1])
        except Exception:
            now_ts_ms = None
        if now_ts_ms is None:
            now_ts_ms = int(pd.Timestamp.utcnow().value // 1_000_000)

        # 1. Calculate Features (5m execution layer)
        features = self.feature_calculator.calculate_all(market_data)
        current_state = features.iloc[-1]

        htf_bias, htf_trend = self._compute_htf_context(htf_data)
        hour_sin, hour_cos, is_golden_hour, liquidity_score = self._compute_time_features()

        # Build enriched state row
        row = features.iloc[-1].copy()
        row['htf_bias'] = float(htf_bias)
        row['htf_trend'] = float(htf_trend)
        row['hour_sin'] = float(hour_sin)
        row['hour_cos'] = float(hour_cos)
        row['is_golden_hour'] = float(is_golden_hour)
        row['liquidity_score'] = float(liquidity_score)

        self._compute_indicators(market_data, row)  # type: ignore[arg-type]

        # FIX Bug#4: normalize OB absolute-price distances by ATR so they are
        # scale-invariant across symbols (BTC OB dist $300 vs DOGE OB dist $0.002).
        # Without normalization these raw values dominate the median-scaling in
        # _build_state_vector and flatten all other features.
        try:
            atr_pct = float(row.get('atr_pct', 0) or 0)
            px_now = float(row.get('close', 1) or 1)
            atr_abs = max(atr_pct * px_now, px_now * 0.001)  # floor at 0.1% of price
            for _dist_col in ('bull_ob_distance', 'bear_ob_distance'):
                raw_d = row.get(_dist_col)
                if raw_d is not None and np.isfinite(float(raw_d)):
                    row[_dist_col] = float(raw_d) / atr_abs
                else:
                    row[_dist_col] = 0.0
        except Exception:
            pass

        state_vector = self._build_state_vector(row)  # type: ignore[arg-type]

        # 2. PLAYBOOK DECISION (Gemma4 Strategy Engine — replaces PPO)
        current_price = float(current_state.get('close', 0))

        # ── CIRCUIT BREAKER CHECK ──
        cb_allow, cb_reason = _check_circuit_breaker(self.portfolio_value, self.capital)
        cb_tripped = not cb_allow
        if cb_tripped:
            print(f"  🚨 CIRCUIT BREAKER: {cb_reason} | Equity: ${self.portfolio_value:.2f} | NO NEW TRADES")

        # Extract features that playbook rules need
        playbook_features = {
            "rsi": float(row.get("rsi", 50)),
            "ema_dist": float(row.get("ema_9_dist", 0) or 0),
            "vol_ratio": float(row.get("volume_ratio", 1) or 1),
            "bb_position": float(row.get("bb_position", 0.5) or 0.5),
            "squeeze": float(row.get("squeeze_on", 0) or 0),
            "adx": float(row.get("adx", 0) or 0),
            "htf_trend": float(htf_trend),
            "swing_low": 1.0 if float(row.get("is_sweep_low", 0) or 0) > 0 else 0.0,
            "swing_high": 1.0 if float(row.get("is_sweep_high", 0) or 0) > 0 else 0.0,
            "fvg_bull": 1.0 if float(row.get("fvg_bull_distance", 999) or 999) < 0.01 else 0.0,
            "fvg_bear": 1.0 if float(row.get("fvg_bear_distance", 999) or 999) < 0.01 else 0.0,
            "macd_cross_up": 1.0 if float(row.get("macd_line", 0) or 0) > 0 and float(row.get("macd_line", 0) or 0) < 0.001 else 0.0,
            "macd_cross_down": 1.0 if float(row.get("macd_line", 0) or 0) < 0 and float(row.get("macd_line", 0) or 0) > -0.001 else 0.0,
            # Direct feature names from strategy_engine
            "rsi_oversold": float(row.get("rsi", 50)),
            "rsi_deep_os": float(row.get("rsi", 50)),
            "vol_spike": float(row.get("volume_ratio", 1) or 1),
            "vol_big_spike": float(row.get("volume_ratio", 1) or 1),
            "bb_low": float(row.get("keltner_position", 0.5) or 0.5),
            "bb_high": float(row.get("keltner_position", 0.5) or 0.5),
            "squeeze_fire": float(row.get("squeeze_on", 0) or 0),
            "htf_up": float(htf_trend),
            "htf_down": float(htf_trend),
            "adx_trending": float(row.get("adx", 0) or 0),
            "ema_below": float(row.get("ema_9_dist", 0) or 0),
            "ema_above": float(row.get("ema_9_dist", 0) or 0),
            # Time-based features
            "hour_utc": float(datetime.now(timezone.utc).hour),
            "liquidity": _compute_liquidity(datetime.now(timezone.utc).hour),
            # Market intelligence
            "btc_momentum": _get_btc_momentum(),
            "funding_rate": _get_funding_rate(symbol) * 100,  # normalize to %
        }

        pb_match = match_playbook_rules(playbook_features)
        action = pb_match["action"]
        
        # Debug: log key feature values every candle
        btc_m = playbook_features['btc_momentum']
        fund = playbook_features['funding_rate']
        print(f"  [PB] rsi={playbook_features['rsi']:.1f} adx={playbook_features['adx']:.1f} vol={playbook_features['vol_ratio']:.2f} btc={btc_m:+.2f}% fund={fund:+.4f}% | match={pb_match.get('rule_id','none')}")
        
        # ── BTC DUMP GUARD: Block LONGs when BTC is crashing ──────
        if action == 1 and btc_m < -1.5:
            print(f"  🛡️ BTC GUARD: LONG blocked — BTC dropping {btc_m:.2f}% in 1h")
            action = 0
        # ── SHORT FILTER: Only short when BTC is actually falling ──
        # Data shows: 5 SHORT closes = 5 losses = -$17.51
        # SHORTs only profitable when market is genuinely bearish
        if action == 2 and btc_m > -0.3:
            print(f"  🛡️ SHORT FILTER: blocked — BTC flat/up ({btc_m:+.2f}%), need <-0.3% for shorts")
            action = 0
        
        # ── CIRCUIT BREAKER: Override all new trades ──
        if cb_tripped and action != 0:
            print(f"  🚨 CB OVERRIDE: {pb_match.get('direction','?')} blocked — drawdown limit reached")
            action = 0

        # ── LIQUIDEZ INTELIGENTE: Small-Cap Protection Suite ──────────
        # Gate 1: Session Filter (data-driven: night = -$48.27 loss)
        session_mode, session_size_mult = check_session_filter()
        if session_mode == "PAUSED" and action != 0:
            print(f"  🌙 SESSION FILTER: {session_mode} — no trades 0-6 UTC")
            action = 0
        elif session_mode == "LONG_ONLY" and action == 2:
            print(f"  🌙 SESSION FILTER: LONG_ONLY — SHORT blocked (21-23 UTC)")
            action = 0

        # Gate 2: Volume Spike Gate
        if action != 0:
            vol_allow, vol_reason, vol_ratio_live = check_volume_gate(market_data)
            if not vol_allow:
                print(f"  📊 VOLUME GATE: blocked — {vol_reason}")
                action = 0

        # Gate 3: Momentum Burst (bonus confidence for strong setups)
        _momentum_signal = "HOLD"
        if action != 0:
            try:
                _vol_r = float(playbook_features.get("vol_ratio", 1.0))
                _momentum_signal, _mb_level = check_momentum_burst(market_data, _vol_r)
                if _momentum_signal != "HOLD":
                    if (_momentum_signal == "LONG" and action == 1) or (_momentum_signal == "SHORT" and action == 2):
                        print(f"  🚀 MOMENTUM BURST: confirms {_momentum_signal} (volume+breakout+3-candle)")
                    elif _momentum_signal != ["HOLD", "LONG", "SHORT"][:1]:
                        # Momentum says opposite direction — be cautious
                        pass
            except Exception:
                pass

        # Gate 4: Anti-Dump Shield
        if action != 0:
            vol_ratio_for_dump = float(playbook_features.get("vol_ratio", 1.0))
            dump_safe, dump_reason = check_pump_and_dump_risk(market_data, vol_ratio_for_dump)
            if not dump_safe:
                print(f"  🧱 ANTI-DUMP: blocked — {dump_reason}")
                action = 0

        # Gate 4: Spread Guardian (uses microstructure from orderbook)
        if action != 0 and microstructure is not None:
            ms_data = microstructure or {}
            notional_est = float(self.portfolio_value * 0.05)  # rough 5% position
            spread_allow, spread_reason, spread_bps_val = check_spread_guard(ms_data, notional_est)
            if not spread_allow:
                print(f"  🛡️ SPREAD GUARD: blocked — {spread_reason}")
                action = 0
            elif "elevated" in spread_reason:
                print(f"  ⚠️ SPREAD WARN: {spread_reason}")

        # Build zones dict for compatibility
        zones = self._extract_smc_zones(current_state, current_price)
        
        # Apply trend filter — relaxed for high-confidence playbook signals
        # Original threshold 0.010 blocks too many valid setups
        # Playbook rules are backtested so we trust them more
        pb_conf = pb_match.get('confidence', 0)
        trend_threshold = 0.030 if pb_conf >= 0.7 else 0.015  # relaxed vs normal
        allow_long = 1 if htf_trend > -trend_threshold else 0
        allow_short = 1 if htf_trend < trend_threshold else 0
        # Always allow both in range-bound
        if abs(htf_trend) < 0.005:
            allow_long, allow_short = 1, 1
        
        if action == 1 and not allow_long:
            print(f"  PLAYBOOK LONG blocked: HTF={htf_trend:.4f} < -{trend_threshold}")
            action = 0
        elif action == 2 and not allow_short:
            print(f"  PLAYBOOK SHORT blocked: HTF={htf_trend:.4f} > {trend_threshold}")
            action = 0
        
        if action != 0:
            print(f"  ✅ PLAYBOOK {pb_match.get('direction','?')} triggered: Rule {pb_match.get('rule_id','?')} | {pb_match.get('reason','')[:60]}")
        
        # Build probs-like for compatibility (dashboard)
        probs = [0.8 if action == 0 else 0.1,
                 pb_match.get("confidence", 0.5) if action == 1 else 0.1,
                 pb_match.get("confidence", 0.5) if action == 2 else 0.1]
        
        cf = dict(zones)
        cf["action"] = action
        cf["long_score"] = 3 if action == 1 else 0
        cf["short_score"] = 3 if action == 2 else 0
        cf["allow_long"] = allow_long
        cf["allow_short"] = allow_short
        cf["playbook_rule"] = pb_match.get("rule_id")
        cf["playbook_reason"] = pb_match.get("reason", "")

        # 3. Risk Management (CPPI + vol targeting + league leverage)
        risk = self._compute_risk_sizing(action, market_data, cf['long_score'], cf['short_score'])
        action = risk['action']

        # 3.1 SL/TP — prefer ATR-based (Liquidez Inteligente) over fixed playbook %
        if action != 0:
            direction_str = "LONG" if action == 1 else "SHORT"
            lev = float(risk.get('leverage', 20.0))
            atr_result = compute_atr_sl_tp(market_data, direction_str, lev, current_price)
            if atr_result is not None:
                sl_price = atr_result['sl']
                tp_price = atr_result['tp2']  # Use TP2 (3x ATR) as main TP
                print(f"  ATR SL/TP: SL={atr_result['sl_pct']*100:.2f}% TP R:R={atr_result['rr_ratio']:.1f}:1 ATR={atr_result['atr_14']:.6f}")
            elif pb_match.get('sl_pct'):
                sl_pct = pb_match['sl_pct']
                tp_pct = pb_match.get('tp2_pct', pb_match.get('tp_pct', 0.03))
                if action == 1:
                    sl_price = current_price * (1 - sl_pct)
                    tp_price = current_price * (1 + tp_pct)
                else:
                    sl_price = current_price * (1 + sl_pct)
                    tp_price = current_price * (1 - tp_pct)
                print(f"  Playbook SL/TP: SL={sl_pct*100:.1f}% TP={tp_pct*100:.1f}%")
            else:
                sl_price, tp_price = self._compute_sl_tp(action, current_price, current_state, market_data)
        else:
            sl_price, tp_price = None, None

        # Cooldown check (no revenge trading after SL)
        if action != 0 and now_ts_ms < self._cooldown_until_ts_ms:
            cooldown_left_s = (self._cooldown_until_ts_ms - now_ts_ms) / 1000.0
            print(f"Cooldown active: {cooldown_left_s:.0f}s remaining, skipping trade.")
            action = 0

        # 4. Build info dict for dashboard
        info = self._build_info_dict(
            action, symbol, htf_bias, htf_trend, current_state,
            cf, risk, sl_price, tp_price, probs, microstructure)  # type: ignore[arg-type]

        # 5. Execute (Simulation)
        # Apply session size multiplier (Liquidez Inteligente)
        final_notional = risk['notional_usd']
        try:
            _sess_mode, _sess_mult = check_session_filter()
            if _sess_mult < 1.0 and action != 0:
                final_notional = final_notional * _sess_mult
                print(f"  Session sizing: {_sess_mode} → {_sess_mult*100:.0f}% size (${final_notional:.2f})")
        except Exception:
            pass

        return action, final_notional, info

if __name__ == "__main__":
    # Test run
    rng = np.random.default_rng(42)
    data = {
        'open': rng.normal(100, 5, 100),
        'high': rng.normal(102, 5, 100),
        'low': rng.normal(98, 5, 100),
        'close': rng.normal(100, 5, 100),
        'volume': rng.normal(1000, 100, 100)
    }
    df = pd.DataFrame(data)
    
    engine = QuantumEngine()
    engine.step(df)
