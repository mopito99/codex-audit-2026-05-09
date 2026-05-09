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

# Trading Params
TP1_PCT = 0.02  # 2% Target for TP1
SL_PCT = 0.015  # 1.5% Stop Loss
TP1_SIZE = 0.30 # Close 30% at TP1
COOLDOWN_CANDLES = 48 # 4 hours (5m candles)
MAX_CONSECUTIVE_LOSSES = 2
CONFIDENCE_THRESHOLD = 0.50

def load_and_prep_data(filepath):
    print(f"Loading {filepath}...")
    df_5m = pd.read_parquet(filepath)
    
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
    df_1h = calc.calculate_all(df_1h)
    
    df_1h['htf_bias'] = 0.0
    df_1h['htf_trend'] = 0.0
    bull = df_1h.get('is_ob_bull', 0) + df_1h.get('is_fvg_bull', 0)
    bear = df_1h.get('is_ob_bear', 0) + df_1h.get('is_fvg_bear', 0)
    df_1h['htf_bias'] = (bull - bear).clip(-2, 2)
    df_1h['htf_trend'] = df_1h['close'].pct_change(13).clip(-0.05, 0.05)
    
    # 2. Calculate LTF (5m) Features
    df_5m = calc.calculate_all(df_5m)
    
    # 3. Merge
    df_1h = df_1h[['htf_bias', 'htf_trend']].sort_index()
    df_5m = df_5m.sort_values("timestamp")
    df_merged = pd.merge_asof(
        df_5m, 
        df_1h, 
        left_on="timestamp", 
        right_index=True, 
        direction="backward"
    )
    
    return df_merged.fillna(0.0)

def _manage_long_position(entry_price, position_size, tp1_hit, curr_high, curr_low, capital):
    """Manage an open long position. Returns (closed, capital, position_size, tp1_hit, pnl)."""
    sl_price = entry_price * (1.001 if tp1_hit else (1 - SL_PCT))
    tp1_price = entry_price * (1 + TP1_PCT)

    if curr_low <= sl_price:
        pnl = (sl_price - entry_price) * position_size
        return True, capital + pnl, 0, False, pnl

    if not tp1_hit and curr_high >= tp1_price:
        close_amt = position_size * TP1_SIZE
        pnl = (tp1_price - entry_price) * close_amt
        capital += pnl
        position_size -= close_amt
        tp1_hit = True

    return False, capital, position_size, tp1_hit, 0.0


def _manage_short_position(entry_price, position_size, tp1_hit, curr_high, curr_low, capital):
    """Manage an open short position. Returns (closed, capital, position_size, tp1_hit, pnl)."""
    sl_price = entry_price * (0.999 if tp1_hit else (1 + SL_PCT))
    tp1_price = entry_price * (1 - TP1_PCT)

    if curr_high >= sl_price:
        pnl = (entry_price - sl_price) * position_size
        return True, capital + pnl, 0, False, pnl

    if not tp1_hit and curr_low <= tp1_price:
        close_amt = position_size * TP1_SIZE
        pnl = (entry_price - tp1_price) * close_amt
        capital += pnl
        position_size -= close_amt
        tp1_hit = True

    return False, capital, position_size, tp1_hit, 0.0


def _get_entry_signal_v2(agent, raw_state, price):
    """Determine entry signal with trend and setup filters. Returns 0/1/2."""
    finite = np.isfinite(raw_state)
    scale = float(np.median(np.abs(raw_state[finite]))) if finite.any() else 1.0
    if scale <= 1e-8:
        scale = 1.0
    state_vec = np.clip(raw_state / scale, -10.0, 10.0)

    action, _, _, policy, _ = agent.get_action(state_vec)
    probs = policy.detach().cpu().numpy().tolist()
    prob_long, prob_short = probs[1], probs[2]

    htf_trend_raw = raw_state[20]
    is_uptrend = htf_trend_raw > -0.002
    is_downtrend = htf_trend_raw < 0.002

    prox_limit = price * 0.003
    has_bull_setup = raw_state[10] > 0.5 or raw_state[11] < prox_limit
    has_bear_setup = raw_state[9] > 0.5 or raw_state[12] < prox_limit

    if action == 1 and ((is_uptrend and prob_long > CONFIDENCE_THRESHOLD) or
                         (has_bull_setup and prob_long > 0.60)):
        return 1
    if action == 2 and ((is_downtrend and prob_short > CONFIDENCE_THRESHOLD) or
                        (has_bear_setup and prob_short > 0.60)):
        return 2
    return 0


def _calc_equity_v2(capital, position, entry_price, position_size, price):
    """Calculate current equity for V2 backtest."""
    if position == 1:
        return capital + (price - entry_price) * position_size
    if position == -1:
        return capital + (entry_price - price) * position_size
    return capital


def _account_trade_v2(pnl, cd, i, trades, wins, cooldown_until):
    """Record a closed trade. Returns (trades, wins, cooldown_until)."""
    trades += 1
    if pnl > 0:
        wins += 1
    if cd > 0:
        cooldown_until = i + cd
    return trades, wins, cooldown_until


def _process_position_v2(position, entry_price, position_size, tp1_hit,
                         curr_high, curr_low, capital, consecutive_losses):
    """Process one tick for open position. Returns (closed, capital, position_size, tp1_hit,
    pnl, consecutive_losses, cooldown_steps)."""
    if position == 1:
        closed, capital, position_size, tp1_hit, pnl = _manage_long_position(
            entry_price, position_size, tp1_hit, curr_high, curr_low, capital)
    else:
        closed, capital, position_size, tp1_hit, pnl = _manage_short_position(
            entry_price, position_size, tp1_hit, curr_high, curr_low, capital)

    cooldown_steps = 0
    if closed:
        if pnl > 0:
            consecutive_losses = 0
        else:
            consecutive_losses += 1
            if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                cooldown_steps = COOLDOWN_CANDLES

    return closed, capital, position_size, tp1_hit, pnl, consecutive_losses, cooldown_steps


def _backtest_symbol_v2(agent, df):
    """Run V2 backtest for a single symbol. Returns (profit, max_dd, trades, wins, trades_per_day)."""
    capital = 1000.0
    initial_capital = capital
    position = 0
    entry_price = position_size = 0.0
    tp1_hit = False
    consecutive_losses = 0
    cooldown_until = 0
    trades = wins = 0
    peak_capital = capital
    max_drawdown = 0.0

    states_np = df[STATE_COLUMNS].values.astype(np.float32)
    prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    agent._state_window = []

    for i in range(len(df) - 1):
        equity = _calc_equity_v2(capital, position, entry_price, position_size, prices[i])
        peak_capital = max(peak_capital, equity)
        max_drawdown = max(max_drawdown, (peak_capital - equity) / peak_capital)

        if i < cooldown_until and position == 0:
            continue

        if position != 0:
            closed, capital, position_size, tp1_hit, pnl, consecutive_losses, cd = \
                _process_position_v2(position, entry_price, position_size, tp1_hit,
                                     highs[i], lows[i], capital, consecutive_losses)
            if closed:
                trades, wins, cooldown_until = _account_trade_v2(
                    pnl, cd, i, trades, wins, cooldown_until)
                position = 0
            continue

        final_action = _get_entry_signal_v2(agent, states_np[i], prices[i])
        if final_action != 0:
            position = 2 * (final_action == 1) - 1
            entry_price = prices[i]
            position_size = capital / entry_price
            tp1_hit = False

    if position != 0:
        pnl = (prices[-1] - entry_price) * position_size * position
        capital += pnl
        trades, wins, _ = _account_trade_v2(pnl, 0, 0, trades, wins, 0)

    profit = capital - initial_capital
    return profit, initial_capital, max_drawdown, trades, wins


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

    for f in files:
        symbol = f.name.split("_")[0]
        df = load_and_prep_data(f)
        if df is None:
            continue

        profit, invested, max_dd, trades, wins = _backtest_symbol_v2(agent, df)
        wr = (wins / trades * 100) if trades > 0 else 0.0
        profit_pct = (profit / invested) * 100
        trades_per_day = trades / 180.0

        print(f"  {symbol}: Profit=${profit:.2f} ({profit_pct:.1f}%) | MaxDD={max_dd*100:.1f}% | "
              f"Trades/Day={trades_per_day:.2f} (Total {trades}) | WR={wr:.1f}%")

if __name__ == "__main__":
    run_backtest()
