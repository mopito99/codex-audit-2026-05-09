import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import torch
import glob
from tqdm import tqdm

# Add project root to path
sys.path.append("/srv/profitlab_quantum")

from app.models.agent import QuantumAgent
from app.features.smc_features import SMCFeatureCalculator
from app.state_schema import STATE_COLUMNS

# Config
DATA_DIR = Path("/srv/profitlab_quantum/data/historical")
OUTPUT_MODEL_PATH = Path("/srv/profitlab_quantum/artifacts/ppo_foundation_v1.pt")
EPOCHS = 5
BATCH_SIZE = 4096  # Steps before update
LEARNING_RATE = 3e-4

def load_and_prep_data(filepath):
    print(f"Loading {filepath}...")
    df_5m = pd.read_parquet(filepath)
    
    # Ensure timestamp is datetime
    if "timestamp" not in df_5m.columns:
        # Try to infer from index or other cols
        if "open_time" in df_5m.columns:
            df_5m["timestamp"] = pd.to_datetime(df_5m["open_time"], unit="ms")
        else:
            print(f"Skipping {filepath}: No timestamp column")
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
    
    # HTF Features
    print("  Calculating HTF features...")
    df_1h = calc.calculate_all(df_1h)
    
    # Calculate Bias & Trend on HTF
    # Logic from engine.py
    df_1h['htf_bias'] = 0.0
    df_1h['htf_trend'] = 0.0
    
    # Vectorized bias calc
    bull = df_1h.get('is_ob_bull', 0) + df_1h.get('is_fvg_bull', 0)
    bear = df_1h.get('is_ob_bear', 0) + df_1h.get('is_fvg_bear', 0)
    df_1h['htf_bias'] = (bull - bear).clip(-2, 2)
    
    # Vectorized trend calc (13 period ~ 13 hours)
    df_1h['htf_trend'] = df_1h['close'].pct_change(13).clip(-0.05, 0.05)
    
    # 2. Calculate LTF (5m) Features
    print("  Calculating LTF features...")
    df_5m = calc.calculate_all(df_5m)
    
    # 3. Merge HTF context into LTF
    # We use merge_asof to map each 5m candle to the *last completed* 1h candle
    df_1h = df_1h[['htf_bias', 'htf_trend']].sort_index()
    df_5m = df_5m.sort_values("timestamp")
    
    df_merged = pd.merge_asof(
        df_5m, 
        df_1h, 
        left_on="timestamp", 
        right_index=True, 
        direction="backward"
    )
    
    # Fill NaNs
    df_merged = df_merged.fillna(0.0)
    
    return df_merged

def _normalize_state(raw_state: np.ndarray) -> np.ndarray:
    """Median-scale a raw state vector (matches engine.py inference)."""
    finite = np.isfinite(raw_state)
    scale = float(np.median(np.abs(raw_state[finite]))) if finite.any() else 1.0
    if scale <= 1e-8:
        scale = 1.0
    return np.clip(raw_state / scale, -10.0, 10.0)


def _step_reward(action: int, curr_price: float, next_price: float) -> float:
    """Compute immediate reward for a single action."""
    pct_change = (next_price - curr_price) / curr_price
    if action == 1:      # Long
        return pct_change * 100.0
    if action == 2:      # Short
        return -pct_change * 100.0
    return -0.01         # Hold penalty


def _train_on_symbol(agent, df) -> tuple:
    """Run one forward pass on *df*, return (total_reward, total_trades)."""
    agent._state_window = []

    states_np = df[STATE_COLUMNS].values.astype(np.float32)
    prices = df['close'].values.astype(np.float32)

    total_reward = 0.0
    total_trades = 0

    for i in tqdm(range(len(df) - 1), desc="Steps", leave=False):
        state_vec = _normalize_state(states_np[i])
        action, log_prob, value, _, _ = agent.get_action(state_vec)

        reward = _step_reward(action, prices[i], prices[i + 1])
        done = (i == len(df) - 2)

        agent.remember(state_vec, action, reward, done, log_prob, value)

        if len(agent.memory) >= BATCH_SIZE:
            agent.update(clear_memory=True)

        total_reward += reward
        if action != 0:
            total_trades += 1

    agent.update(clear_memory=True)
    return total_reward, total_trades


def _load_all_data() -> list:
    """Load and prep every parquet file from DATA_DIR."""
    files = sorted(DATA_DIR.glob("*_6m.parquet"))
    all_dfs = []
    for f in files:
        df = load_and_prep_data(f)
        if df is not None:
            all_dfs.append(df)
    return all_dfs


def train():
    input_dim = len(STATE_COLUMNS)
    agent = QuantumAgent(
        input_dim=input_dim,
        action_dim=3,
        lr=LEARNING_RATE,
        use_transformer=True,
        seq_len=32,
    )
    print(f"Agent initialized. Input dim: {input_dim}")

    all_dfs = _load_all_data()
    if not all_dfs:
        print("No data found!")
        return

    rng = np.random.default_rng(seed=42)

    for epoch in range(EPOCHS):
        print(f"\n=== EPOCH {epoch+1}/{EPOCHS} ===")
        rng.shuffle(all_dfs)

        total_reward = 0.0
        total_trades = 0
        for df in all_dfs:
            r, t = _train_on_symbol(agent, df)
            total_reward += r
            total_trades += t

        print(f"Epoch {epoch+1} Result: Total Reward={total_reward:.2f}, Trades={total_trades}")
        agent.save(str(OUTPUT_MODEL_PATH))
        print(f"Saved model to {OUTPUT_MODEL_PATH}")

if __name__ == "__main__":
    train()
