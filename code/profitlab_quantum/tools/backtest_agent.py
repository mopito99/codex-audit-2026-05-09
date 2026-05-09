import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import torch
from tqdm import tqdm

# Add project root to path
sys.path.append("/srv/profitlab_quantum")

from app.models.agent import QuantumAgent
from app.features.smc_features import SMCFeatureCalculator
from app.state_schema import STATE_COLUMNS

# Config
DATA_DIR = Path("/srv/profitlab_quantum/data/historical")
MODEL_PATH = Path("/srv/profitlab_quantum/artifacts/ppo/ppo.pt")

# FINAL PORTFOLIO: TOP 5 MAJORS
SYMBOLS = ["AVAX"]

def load_and_prep_data(filepath):
    try:
        df_5m = pd.read_parquet(filepath)
    except Exception:
        return None
    
    if "timestamp" not in df_5m.columns:
        if "open_time" in df_5m.columns:
            df_5m["timestamp"] = pd.to_datetime(df_5m["open_time"], unit="ms")
        else:
            return None
            
    df_5m = df_5m.sort_values("timestamp").reset_index(drop=True)
    
    # 1. Calculate HTF (1h) Context
    df_1h = df_5m.set_index("timestamp").resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    
    calc = SMCFeatureCalculator()
    df_5m = calc.calculate_all(df_5m)
    
    # Add HTF context (simple merge)
    df_1h['htf_trend'] = df_1h['close'].pct_change(24).fillna(0) # 24h trend
    df_1h['htf_bias'] = np.where(df_1h['htf_trend'] > 0, 1, -1)
    
    # Merge HTF back to 5m (ffill)
    df_5m = pd.merge_asof(df_5m, df_1h[['htf_trend', 'htf_bias']], on='timestamp', direction='backward')
    df_5m = df_5m.fillna(0)
    
    return df_5m

def _close_position(pos, entry_price, sl_price, size, capital):
    """Close position at SL price and return updated capital, pnl_pct."""
    pnl_usd = size * (sl_price - entry_price) * pos
    principal = size * entry_price
    gross_return = principal + pnl_usd
    fee = size * sl_price * 0.001
    return capital + (gross_return - fee), pnl_usd / principal


def _handle_tp1(pos, entry_price, tp1_price, size, capital, curr_high, curr_low):
    """Check and execute TP1 partial close. Returns (tp1_hit, size, capital, sl_price)."""
    tp1_triggered = (pos == 1 and curr_high >= tp1_price) or \
                    (pos == -1 and curr_low <= tp1_price)
    if not tp1_triggered:
        return False, size, capital, None
    close_size = size * 0.30
    size -= close_size
    pnl_usd = close_size * (tp1_price - entry_price) * pos
    principal = close_size * entry_price
    fee = close_size * tp1_price * 0.001
    capital += (principal + pnl_usd - fee)
    return True, size, capital, entry_price  # SL moves to breakeven


def _update_trailing_sl(pos, sl_price, curr_high, curr_low, trailing_pct):
    """Update trailing stop-loss."""
    if pos == 1:
        new_sl = curr_high * (1 - trailing_pct)
        return max(sl_price, new_sl)
    new_sl = curr_low * (1 + trailing_pct)
    return min(sl_price, new_sl)


def _get_entry_signal(agent, raw_state, curr_price):
    """Determine entry signal. Returns final_action (0=hold, 1=long, 2=short)."""
    finite = np.isfinite(raw_state)
    scale = float(np.median(np.abs(raw_state[finite]))) if finite.any() else 1.0
    if scale <= 1e-8:
        scale = 1.0
    state_vec = np.clip(raw_state / scale, -10.0, 10.0)

    action, _, _, policy, _ = agent.get_action(state_vec)
    probs = policy.detach().cpu().numpy().tolist()
    prob_long, prob_short = probs[1], probs[2]

    sweep_low = raw_state[10]
    bull_dist = raw_state[11]
    sweep_high = raw_state[9]
    bear_dist = raw_state[12]

    prox_limit = curr_price * 0.003
    has_bull_setup = sweep_low > 0.5 or bull_dist < prox_limit
    has_bear_setup = sweep_high > 0.5 or bear_dist < prox_limit

    threshold = 0.40
    if (action == 1 and has_bull_setup) or (action == 2 and has_bear_setup):
        threshold = 0.30

    if action == 1 and prob_long > threshold:
        return 1
    if action == 2 and prob_short > threshold:
        return 2
    return 0


def _calc_equity_bt(capital, position, size, entry_price, price):
    """Calculate current equity."""
    if position == 0:
        return capital
    return capital + size * (price - entry_price) * position


def _account_trade(pnl_pct, cd, i, trades, wins, cooldown_idx):
    """Record trade result. Returns (trades, wins, cooldown_idx)."""
    trades += 1
    if pnl_pct > 0:
        wins += 1
    if cd > 0:
        cooldown_idx = i + cd
    return trades, wins, cooldown_idx


def _manage_open_bt(position, entry_price, sl_price, tp1_price, tp1_hit, size,
                    capital, curr_high, curr_low, trailing_pct, consecutive_losses):
    """Handle one tick for an open position.

    Returns (closed, capital, size, sl_price, tp1_hit, pnl_pct,
             consecutive_losses, cooldown_steps).
    """
    sl_hit = (position == 1 and curr_low <= sl_price) or \
             (position == -1 and curr_high >= sl_price)
    if sl_hit:
        capital, pnl_pct = _close_position(position, entry_price, sl_price, size, capital)
        cooldown_steps = 0
        if not tp1_hit:
            consecutive_losses += 1
            if consecutive_losses >= 2:
                cooldown_steps = 48
                consecutive_losses = 0
        else:
            consecutive_losses = 0
        return True, capital, 0, sl_price, False, pnl_pct, consecutive_losses, cooldown_steps

    if not tp1_hit:
        tp1_hit, size, capital, new_sl = _handle_tp1(
            position, entry_price, tp1_price, size, capital, curr_high, curr_low)
        if tp1_hit:
            sl_price = new_sl

    if tp1_hit:
        sl_price = _update_trailing_sl(position, sl_price, curr_high, curr_low, trailing_pct)

    return False, capital, size, sl_price, tp1_hit, 0.0, consecutive_losses, 0


def _backtest_symbol(agent, df):
    """Run backtest for a single symbol. Returns (profit, initial_capital, max_drawdown, trades, wins)."""
    SL_PCT, TP1_PCT, TRAILING_PCT = 0.02, 0.02, 0.02
    capital = 1000.0
    initial_capital = capital
    position = 0
    entry_price = sl_price = tp1_price = 0.0
    tp1_hit = False
    size = 0.0
    consecutive_losses = 0
    cooldown_until_idx = 0
    trades = wins = 0
    peak_capital = capital
    max_drawdown = 0.0

    states_np = df[STATE_COLUMNS].values.astype(np.float32)
    prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    agent._state_window = []

    for i in range(len(df) - 1):
        equity = _calc_equity_bt(capital, position, size, entry_price, prices[i])
        peak_capital = max(peak_capital, equity)
        max_drawdown = max(max_drawdown, (peak_capital - equity) / peak_capital)

        if i < cooldown_until_idx:
            continue

        if position != 0:
            closed, capital, size, sl_price, tp1_hit, pnl_pct, consecutive_losses, cd = \
                _manage_open_bt(position, entry_price, sl_price, tp1_price, tp1_hit,
                                size, capital, highs[i], lows[i], TRAILING_PCT, consecutive_losses)
            if closed:
                trades, wins, cooldown_until_idx = _account_trade(
                    pnl_pct, cd, i, trades, wins, cooldown_until_idx)
                position = 0
            continue

        final_action = _get_entry_signal(agent, states_np[i], prices[i])
        if final_action != 0:
            position = 2 * (final_action == 1) - 1
            entry_price = prices[i]
            size = capital / entry_price
            capital = 0
            sl_price = entry_price * (1 - SL_PCT * position)
            tp1_price = entry_price * (1 + TP1_PCT * position)
            tp1_hit = False

    if position != 0:
        capital, pnl_pct = _close_position(position, entry_price, prices[-1], size, capital)
        trades, wins, _ = _account_trade(pnl_pct, 0, 0, trades, wins, 0)

    return capital - initial_capital, initial_capital, max_drawdown, trades, wins


def run_backtest():
    input_dim = len(STATE_COLUMNS)
    agent = QuantumAgent(input_dim=input_dim, action_dim=3, use_transformer=True, seq_len=32)

    if MODEL_PATH.exists():
        print(f"Loading model from {MODEL_PATH}")
        agent.load(str(MODEL_PATH))
    else:
        print("Model not found!")
        return

    files = sorted(DATA_DIR.glob("*_6m.parquet"))
    total_profit = total_invested = 0.0

    print(f"{'SYMBOL':<10} | {'PROFIT':<10} | {'ROI':<8} | {'DD':<6} | {'TRADES':<6} | {'WR':<6}")
    print("-" * 65)

    for f in files:
        symbol = f.name.split("_")[0]
        if symbol not in SYMBOLS:
            continue
        df = load_and_prep_data(f)
        if df is None:
            continue

        profit, invested, max_dd, trades, wins = _backtest_symbol(agent, df)
        wr = (wins / trades * 100) if trades > 0 else 0.0
        roi = (profit / invested) * 100

        print(f"{symbol:<10} | {profit:<10.2f} | {roi:<7.1f}% | {max_dd*100:<5.1f}% | {trades:<6} | {wr:<5.1f}%")
        total_profit += profit
        total_invested += invested

    print("-" * 65)
    total_roi = (total_profit / total_invested * 100) if total_invested > 0 else 0.0
    print(f"TOTAL PORTFOLIO: Invested={total_invested:.2f} | Profit={total_profit:.2f} | ROI={total_roi:.2f}%")

if __name__ == "__main__":
    run_backtest()
