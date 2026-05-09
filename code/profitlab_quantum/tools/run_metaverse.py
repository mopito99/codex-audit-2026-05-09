import os
import sys
import argparse
import json
import logging
import asyncio
import numpy as np
import pandas as pd
import torch
from pathlib import Path

# Add project root to path
sys.path.append("/srv/profitlab_quantum")

from app.data.bingx import BingXReader
from app.models.timegan import TimeGAN, TimeGANTrainConfig, make_sliding_windows
from app.engine import QuantumEngine
from app.config import TOKENS

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [METAVERSE] %(message)s",
    handlers=[
        logging.FileHandler("metaverse.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Metaverse")

def _minmax_scale(x: np.ndarray, eps: float = 1e-8):
    x_min = x.min(axis=0, keepdims=True)
    x_max = x.max(axis=0, keepdims=True)
    scale = np.maximum(x_max - x_min, eps)
    return (x - x_min) / scale, x_min, scale

def _minmax_inverse(x: np.ndarray, x_min: np.ndarray, scale: np.ndarray):
    return x * scale + x_min

async def train_and_generate_scenarios(symbol: str, timeframe: str = "5m", seq_len: int = 48, n_samples: int = 200):
    """Trains TimeGAN on recent data and generates synthetic scenarios."""
    logger.info("🔮 [%s] Training TimeGAN & Generating Scenarios...", symbol)
    
    # 1. Fetch Real Data
    reader = BingXReader()
    # Fetch enough data for training (e.g., 1000 candles)
    df = await reader.get_klines(symbol, interval=timeframe, limit=1000)
    if df is None or df.empty:
        logger.error("❌ [%s] No data found.", symbol)
        return None

    cols = ["open", "high", "low", "close", "volume"]
    x = df[cols].astype(float).to_numpy()

    # 2. Preprocess
    x_scaled, x_min, scale = _minmax_scale(x)
    windows = make_sliding_windows(x_scaled, seq_len=seq_len)

    # 3. Train TimeGAN (Fast mode for daily updates)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TimeGAN(feature_dim=len(cols), hidden_dim=64, num_layers=2)
    model.to(device)

    # Reduced steps for daily incremental learning
    cfg = TimeGANTrainConfig(
        seq_len=seq_len,
        batch_size=64,
        lr=1e-3,
        device=device,
        pretrain_steps=100,   # Fast
        supervisor_steps=100, # Fast
        joint_steps=200,      # Fast
    )

    model.fit(windows, cfg)

    # 4. Generate Synthetic Data (The "Dream")
    logger.info("💤 [%s] Dreaming %d scenarios...", symbol, n_samples)
    with torch.no_grad():
        x_hat = model.sample(n_samples, seq_len).detach().cpu().numpy()
    
    # Inverse scale to get real price ranges
    x_hat_real = _minmax_inverse(x_hat, x_min, scale)
    
    return x_hat_real


def _build_state_vector(row, state_columns):
    """Build state vector from feature row, with neutral HTF assumptions."""
    state_values = []
    for col in state_columns:
        if col == 'htf_bias':
            v = 0.0
        elif col == 'htf_trend':
            v = 0.0
        else:
            v = row.get(col, 0.0)
        try:
            fv = float(v)
            if not np.isfinite(fv):
                fv = 0.0
        except (TypeError, ValueError):
            fv = 0.0
        state_values.append(fv)
    return np.clip(np.array(state_values, dtype=np.float32), -10.0, 10.0)


def _compute_step_reward(action: int, current_close: float, next_close: float) -> float | None:
    """Compute amplified synthetic reward for one step. Returns None to skip."""
    if current_close == 0:
        return None
    pct_change = (next_close - current_close) / current_close
    if action == 1:       # LONG
        reward = pct_change
    elif action == 2:     # SHORT
        reward = -pct_change
    else:                 # HOLD
        reward = -0.0001
    return reward * 10.0


def _process_scenario(engine, agent, scenario_data, cols):
    """Run agent through one synthetic scenario, returning (reward, transitions)."""
    df = pd.DataFrame(scenario_data, columns=cols)
    try:
        features = engine.feature_calculator.calculate_all(df)
    except Exception:
        return 0.0, 0

    start_idx = 25
    if len(features) <= start_idx:
        return 0.0, 0

    total_reward = 0.0
    transitions = 0
    for t in range(start_idx, len(features) - 1):
        state_vector = _build_state_vector(features.iloc[t], engine.state_columns)
        action, log_prob, value, _, _ = agent.get_action(state_vector)

        reward = _compute_step_reward(action, df['close'].iloc[t], df['close'].iloc[t + 1])
        if reward is None:
            continue

        done = (t == len(features) - 2)
        if hasattr(agent, "remember"):
            try:
                agent.remember(state_vector, action, reward, done, log_prob, value, int(t * 1000))
            except TypeError:
                agent.remember(state_vector, action, reward, done, log_prob, value)

        total_reward += reward
        transitions += 1

    return total_reward, transitions


def train_agent_on_scenarios(symbol: str, scenarios: np.ndarray):
    """Feeds synthetic scenarios into the PPO Agent to update policy."""
    logger.info("🧠 [%s] Updating Brain with Synthetic Data...", symbol)

    engine = QuantumEngine(symbol=symbol)
    agent = engine.agent

    if not hasattr(agent, "update"):
        logger.warning("⚠️ [%s] Agent is not trainable (Decision Transformer?). Skipping.", symbol)
        return

    cols = ["open", "high", "low", "close", "volume"]
    total_reward = 0.0
    transitions = 0

    for i in range(scenarios.shape[0]):
        r, t = _process_scenario(engine, agent, scenarios[i], cols)
        total_reward += r
        transitions += t

    logger.info("📊 [%s] Generated %d synthetic transitions. Total Reward: %.4f", symbol, transitions, total_reward)

    if transitions > 0:
        _update_and_save(agent, symbol)

def _update_and_save(agent, symbol: str):
    """Run PPO update and persist weights."""
    initial_updates = getattr(agent, "_update_count", 0)
    agent.update(clear_memory=True)
    final_updates = getattr(agent, "_update_count", 0)

    if final_updates > initial_updates:
        logger.info("✅ [%s] Brain updated successfully (%d steps).", symbol, final_updates - initial_updates)
        save_path = Path(f"/srv/profitlab_quantum/artifacts/ppo/by_symbol/{symbol}/ppo.pt")
        agent.save(str(save_path))
        logger.info("💾 [%s] Saved updated brain to %s", symbol, save_path)
    else:
        logger.warning("⚠️ [%s] Update called but no gradient step taken (maybe insufficient samples?).", symbol)


async def main():
    logger.info("🚀 Starting Metaverse Training Cycle...")
    
    for token in TOKENS:
        try:
            # 1. Train TimeGAN & Generate
            scenarios = await train_and_generate_scenarios(token, n_samples=100) # 100 scenarios * ~20 steps = 2000 transitions
            
            if scenarios is not None:
                # 2. Train Agent
                train_agent_on_scenarios(token, scenarios)
                
        except Exception as e:
            logger.error("🔥 [%s] Critical Error in Metaverse: %s", token, e, exc_info=True)
            
    logger.info("🏁 Metaverse Cycle Complete.")

if __name__ == "__main__":
    asyncio.run(main())
