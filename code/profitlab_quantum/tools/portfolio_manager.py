import sys
import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.append("/srv/profitlab_quantum")

from app.models.agent import QuantumAgent
from app.features.smc_features import SMCFeatureCalculator
from app.state_schema import STATE_COLUMNS

# Config
DATA_DIR = Path("/srv/profitlab_quantum/data/historical")
PPO_WEIGHTS_DIR = Path("/srv/profitlab_quantum/artifacts/ppo/by_symbol")
CONFIG_FILE = Path("/srv/profitlab_quantum/active_tokens.json")
_SL_PCT = 0.02
_TP1_PCT = 0.02
_TRAILING_PCT = 0.02

def load_and_prep_data(filepath, days=30):
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
    
    # Filter last X days
    cutoff_date = df_5m["timestamp"].max() - timedelta(days=days)
    df_5m = df_5m[df_5m["timestamp"] > cutoff_date].reset_index(drop=True)
    
    if len(df_5m) < 100: return None

    # 1. Calculate HTF (1h) Context
    df_1h = df_5m.set_index("timestamp").resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    
    calc = SMCFeatureCalculator()
    df_5m = calc.calculate_all(df_5m)
    
    df_1h['htf_trend'] = df_1h['close'].pct_change(24).fillna(0)
    df_1h['htf_bias'] = np.where(df_1h['htf_trend'] > 0, 1, -1)
    
    df_5m = pd.merge_asof(df_5m, df_1h[['htf_trend', 'htf_bias']], on='timestamp', direction='backward')
    df_5m = df_5m.fillna(0)
    
    # Golden Hour Features
    hour_float = df_5m['timestamp'].dt.hour + df_5m['timestamp'].dt.minute / 60.0
    df_5m['hour_sin'] = np.sin(2 * np.pi * hour_float / 24.0)
    df_5m['hour_cos'] = np.cos(2 * np.pi * hour_float / 24.0)
    df_5m['is_golden_hour'] = np.where(
        (hour_float >= 14.5) & (hour_float <= 17.0), 1.0,
        np.where(
            ((hour_float >= 7.0) & (hour_float <= 9.0)) | ((hour_float >= 21.0) & (hour_float <= 23.0)),
            0.5, 0.0
        )
    )
    df_5m['liquidity_score'] = 0.5
    
    return df_5m

def _close_position_pm(pos, entry_price, exit_price, size, capital):
    """Close position and return (capital, pnl_pct)."""
    pnl_usd = size * (exit_price - entry_price) * pos
    principal = size * entry_price
    fee = size * exit_price * 0.001
    return capital + (principal + pnl_usd - fee), pnl_usd / principal


def _manage_open_position_pm(pos, entry_price, tp1_price, sl_price, tp1_hit, size,
                              capital, curr_high, curr_low, trailing_pct):
    """Manage open position: SL, TP1, trailing. Returns tuple of updated state."""
    sl_hit = (pos == 1 and curr_low <= sl_price) or (pos == -1 and curr_high >= sl_price)
    if sl_hit:
        capital, pnl_pct = _close_position_pm(pos, entry_price, sl_price, size, capital)
        return True, capital, 0, sl_price, False, pnl_pct

    if not tp1_hit:
        tp1_triggered = (pos == 1 and curr_high >= tp1_price) or \
                        (pos == -1 and curr_low <= tp1_price)
        if tp1_triggered:
            close_size = size * 0.30
            size -= close_size
            pnl_usd = close_size * (tp1_price - entry_price) * pos
            principal = close_size * entry_price
            fee = close_size * tp1_price * 0.001
            capital += (principal + pnl_usd - fee)
            sl_price = entry_price
            tp1_hit = True

    if tp1_hit:
        if pos == 1:
            sl_price = max(sl_price, curr_high * (1 - trailing_pct))
        else:
            sl_price = min(sl_price, curr_low * (1 + trailing_pct))

    return False, capital, size, sl_price, tp1_hit, 0.0


def _get_entry_signal_pm(agent, raw_state, curr_price):
    """Determine entry signal. Returns 0/1/2."""
    finite = np.isfinite(raw_state)
    scale = float(np.median(np.abs(raw_state[finite]))) if finite.any() else 1.0
    if scale <= 1e-8:
        scale = 1.0
    state_vec = np.clip(raw_state / scale, -10.0, 10.0)
    action, _, _, policy, _ = agent.get_action(state_vec)
    probs = policy.detach().cpu().numpy().tolist()

    prox_limit = curr_price * 0.003
    has_bull = raw_state[10] > 0.5 or raw_state[11] < prox_limit
    has_bear = raw_state[9] > 0.5 or raw_state[12] < prox_limit
    threshold = 0.30 if ((action == 1 and has_bull) or (action == 2 and has_bear)) else 0.40

    if action == 1 and probs[1] > threshold:
        return 1
    if action == 2 and probs[2] > threshold:
        return 2
    return 0


def _calc_equity_pm(capital, position, size, entry_price, price):
    """Calculate current equity."""
    if position == 0:
        return capital
    return capital + size * (price - entry_price) * position


def _record_trade_pm(pnl_pct, trades, wins):
    """Record trade result. Returns (trades, wins)."""
    trades += 1
    if pnl_pct > 0:
        wins += 1
    return trades, wins


def _process_step_eval(position, entry_price, sl_price, tp1_price, tp1_hit,
                       size, capital, curr_high, curr_low,
                       agent, states_np_i, curr_price):
    """Process one simulation step. Returns updated state tuple:
    (position, entry_price, sl_price, tp1_price, tp1_hit, size, capital, trade_closed, pnl_pct)."""
    if position != 0:
        closed, capital, size, sl_price, tp1_hit, pnl_pct = _manage_open_position_pm(
            position, entry_price, tp1_price, sl_price, tp1_hit, size,
            capital, curr_high, curr_low, _TRAILING_PCT)
        if closed:
            return 0, entry_price, sl_price, tp1_price, tp1_hit, size, capital, True, pnl_pct
        return position, entry_price, sl_price, tp1_price, tp1_hit, size, capital, False, 0.0

    final_action = _get_entry_signal_pm(agent, states_np_i, curr_price)
    if final_action != 0:
        position = 2 * (final_action == 1) - 1
        entry_price = curr_price
        size = capital / entry_price
        capital = 0
        sl_price = entry_price * (1 - _SL_PCT * position)
        tp1_price = entry_price * (1 + _TP1_PCT * position)
        tp1_hit = False

    return position, entry_price, sl_price, tp1_price, tp1_hit, size, capital, False, 0.0


def evaluate_symbol(symbol, agent, days=30):
    """Backtest a single symbol and return performance metrics."""
    files = list(DATA_DIR.glob(f"{symbol}_*.parquet"))
    if not files:
        return None
    df = load_and_prep_data(files[0], days=days)
    if df is None:
        return None

    capital = 1000.0
    initial_capital = capital
    position = 0
    entry_price = sl_price = tp1_price = 0.0
    tp1_hit = False
    size = 0.0
    trades = wins = 0
    peak_capital = capital
    max_drawdown = 0.0

    states_np = df[STATE_COLUMNS].values.astype(np.float32)
    prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values

    for i in range(len(df) - 1):
        equity = _calc_equity_pm(capital, position, size, entry_price, prices[i])
        peak_capital = max(peak_capital, equity)
        max_drawdown = max(max_drawdown, (peak_capital - equity) / peak_capital)

        position, entry_price, sl_price, tp1_price, tp1_hit, size, capital, closed, pnl_pct = \
            _process_step_eval(position, entry_price, sl_price, tp1_price, tp1_hit,
                               size, capital, highs[i], lows[i],
                               agent, states_np[i], prices[i])
        if closed:
            trades, wins = _record_trade_pm(pnl_pct, trades, wins)

    if position != 0:
        capital, pnl_pct = _close_position_pm(position, entry_price, prices[-1], size, capital)
        trades, wins = _record_trade_pm(pnl_pct, trades, wins)

    roi = (capital - initial_capital) / initial_capital * 100
    return {
        "symbol": symbol, "roi": roi,
        "drawdown": max_drawdown * 100, "trades": trades,
        "win_rate": (wins / trades * 100) if trades > 0 else 0.0,
    }

def _evaluate_candidate(symbol_pair, input_dim, active_tokens):
    """Evaluate a single candidate symbol. Returns (result_dict, status, leverage_tier) or None."""
    symbol = symbol_pair.split("-")[0]
    model_path = PPO_WEIGHTS_DIR / symbol_pair / "ppo.pt"
    if not model_path.exists():
        print(f"{symbol:<10} | {'N/A':<8} | {'N/A':<6} | {'0':<6} | {'0.0':<6} | {'NO MODEL':<10}")
        return None

    agent = QuantumAgent(input_dim=input_dim, action_dim=3, use_transformer=True, seq_len=32)
    try:
        agent.load(str(model_path))
    except Exception as e:
        print(f"Load Error for {symbol}: {e}")
        return None

    res = evaluate_symbol(symbol, agent, days=30)
    if res is None:
        print(f"{symbol:<10} | {'N/A':<8} | {'N/A':<6} | {'0':<6} | {'0.0':<6} | {'NO DATA':<10}")
        return None

    is_approved = res['roi'] > 0 and res['drawdown'] < 25.0 and res['trades'] >= 5
    leverage_tier = 1.0
    status = "REJECTED"

    if is_approved:
        status = "APPROVED"
        if res['roi'] > 10.0 and res['win_rate'] > 55.0:
            leverage_tier = 3.0
        elif res['roi'] > 5.0 and res['win_rate'] > 50.0:
            leverage_tier = 2.0
    elif symbol_pair in [t['symbol'] if isinstance(t, dict) else t for t in active_tokens]:
        status = "DEMOTED"

    print(f"{symbol:<10} | {res['roi']:<8.2f} | {res['drawdown']:<6.1f} | {res['trades']:<6} | "
          f"{res['win_rate']:<6.1f} | {status:<10} | {leverage_tier}x")

    if is_approved:
        return {"symbol": symbol_pair, "leverage": leverage_tier}
    return None


def main():
    print("Starting Portfolio Manager Evaluation...")
    
    # Load Config
    if not CONFIG_FILE.exists():
        print("Config file not found.")
        return
        
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
        
    candidates = config.get("candidates", [])
    active_tokens = config.get("active_tokens", [])
    
    # Load Agent
    input_dim = len(STATE_COLUMNS)

    new_active_tokens = []
    
    print(f"{'SYMBOL':<10} | {'ROI':<8} | {'DD':<6} | {'TRADES':<6} | {'WR':<6} | {'STATUS':<10}")
    print("-" * 70)
    
    for symbol_pair in candidates:
        result = _evaluate_candidate(symbol_pair, input_dim, active_tokens)
        if result is not None:
            new_active_tokens.append(result)

    # Always keep BTC as anchor
    btc_pair = "BTC-USDT"
    if not any(t['symbol'] == btc_pair for t in new_active_tokens) and btc_pair in candidates:
        print("Adding BTC-USDT as Anchor (Safety Net).")
        new_active_tokens.insert(0, {"symbol": btc_pair, "leverage": 1.0})

    # Update Config
    # We need to store objects now, not just strings.
    # But app/config.py expects strings in TOKENS list.
    # We will save a complex object in active_tokens.json, and app/config.py will need to parse it.
    
    config["active_tokens"] = new_active_tokens
    config["last_update"] = datetime.now().isoformat()
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
        
    print("-" * 70)
    print(f"Updated Active Tokens: {new_active_tokens}")

if __name__ == "__main__":
    main()
