#!/usr/bin/env python3
"""
Offline training for new tokens using historical parquet data.
V2 - Vectorized NumPy (no slow Python loops).
"""
import os, sys, time, logging, random, gc
import numpy as np
import torch
import pandas as pd
from pathlib import Path

os.chdir('/srv/profitlab_quantum')
sys.path.insert(0, '/srv/profitlab_quantum')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('offline_train')

from app.config import DATABASE_URL, PPO_WEIGHTS_DIR, PPO_WEIGHTS_PATH, PPO_PER_SYMBOL
from app.features.smc_features import SMCFeatureCalculator
from app.models.agent import QuantumAgent
from app.state_schema import STATE_COLUMNS, INPUT_DIM

NEW_SYMBOLS = [
    'BTC-USDT', 'ETH-USDT', 'XRP-USDT', 'BNB-USDT', 'SOL-USDT',
    'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'TRX-USDT', 'LINK-USDT',
    'DOT-USDT', 'TON-USDT', 'SUI-USDT', 'SHIB-USDT', 'XLM-USDT',
    'HBAR-USDT', 'BCH-USDT', 'LTC-USDT', 'UNI-USDT', 'NEAR-USDT',
]
NUM_UPDATES = 20
SEQ_LEN = 32

def add_technical_indicators(df):
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float)
    
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    df['rsi_normalized'] = (rsi - 50) / 50
    
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    df['atr_pct'] = atr / (close + 1e-10)
    
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    df['ema_20_dist'] = (close - ema20) / (close + 1e-10)
    df['ema_50_dist'] = (close - ema50) / (close + 1e-10)
    df['ema_200_dist'] = (close - ema200) / (close + 1e-10)
    
    vol_ma = volume.rolling(20).mean()
    df['volume_ratio'] = volume / (vol_ma + 1e-10)
    
    df['momentum_5'] = close.pct_change(5)
    df['momentum_10'] = close.pct_change(10)
    df['trend_strength'] = (ema20 - ema50) / (close + 1e-10)
    return df

def add_golden_hour(df):
    df['hour_sin'] = 0.0
    df['hour_cos'] = 1.0
    df['is_golden_hour'] = 0.0
    df['liquidity_score'] = 0.5
    
    if 'time' in df.columns:
        try:
            times = pd.to_datetime(df['time'], unit='ms', utc=True)
            hour_float = times.dt.hour + times.dt.minute / 60.0
            df['hour_sin'] = np.sin(2 * np.pi * hour_float / 24.0)
            df['hour_cos'] = np.cos(2 * np.pi * hour_float / 24.0)
            df['is_golden_hour'] = ((hour_float >= 14.5) & (hour_float <= 17.0)).astype(float)
            df['liquidity_score'] = np.where(
                (hour_float >= 8) & (hour_float <= 17), 0.8,
                np.where((hour_float >= 1) & (hour_float <= 8), 0.5, 0.3)
            )
        except Exception:
            pass
    return df

def add_v3_pro_indicators(df):
    """V3 PRO indicators - 14 new institutional-grade features."""
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    df['macd_signal_dist'] = (macd_line - signal_line) / (close + 1e-10)
    df['macd_histogram'] = df['macd_signal_dist'].copy()

    # Bollinger Bands (20, 2)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_range = bb_upper - bb_lower
    df['bb_position'] = (close - bb_lower) / (bb_range + 1e-10)
    df['bb_width'] = bb_range / (bb_mid + 1e-10)

    # Stochastic (14, 3)
    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = (close - low14) / (high14 - low14 + 1e-10)
    stoch_d = stoch_k.rolling(3).mean()
    df['stoch_k'] = (stoch_k - 0.5) * 2
    df['stoch_d'] = (stoch_d - 0.5) * 2

    # ADX (14)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    plus_di = (plus_dm.rolling(14).mean() / (atr14 + 1e-10)) * 100
    minus_di = (minus_dm.rolling(14).mean() / (atr14 + 1e-10)) * 100
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
    adx = dx.rolling(14).mean()
    df['adx_normalized'] = adx / 100.0

    # OBV slope
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_ma = obv.rolling(20).mean()
    df['obv_slope'] = (obv - obv_ma) / (obv_ma.abs() + 1e-10)

    # VWAP (rolling ~1 day of 5m candles)
    typical_price = (high + low + close) / 3
    cum_vol = volume.rolling(288).sum()
    cum_tp_vol = (typical_price * volume).rolling(288).sum()
    vwap = cum_tp_vol / (cum_vol + 1e-10)
    df['vwap_dist'] = (close - vwap) / (close + 1e-10)

    # Multi-timeframe price changes
    df['price_change_1h'] = close.pct_change(12)
    df['price_change_4h'] = close.pct_change(48)

    # Volatility & structure
    df['high_low_ratio'] = (high - low) / (close + 1e-10)
    df['close_position'] = (close - low) / (high - low + 1e-10)

    # Volume momentum
    df['volume_momentum'] = volume.pct_change(5)
    return df

def _add_v4_indicators(df):
    """V4 indicators – 8 additional PPO learning features."""
    close = df['close'].astype(float)
    high  = df['high'].astype(float)
    low   = df['low'].astype(float)
    volume = df['volume'].astype(float)

    # RSI-14
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / (loss + 1e-10)
    df['rsi_14'] = (rs / (1 + rs) - 0.5) * 2

    # Williams %R (14)
    hh14 = high.rolling(14).max()
    ll14 = low.rolling(14).min()
    df['williams_r'] = ((close - hh14) / (hh14 - ll14 + 1e-10) + 0.5) * 2

    # CCI normalised (20)
    tp   = (high + low + close) / 3
    mavg = tp.rolling(20).mean()
    mdev = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    df['cci_normalized'] = ((tp - mavg) / (0.015 * mdev + 1e-10)) / 200.0

    # MFI normalised (14)
    mf_raw = tp * volume
    pos_mf = mf_raw.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_mf = mf_raw.where(tp <= tp.shift(1), 0).rolling(14).sum()
    mfi    = pos_mf / (pos_mf + neg_mf + 1e-10)
    df['mfi_normalized'] = (mfi - 0.5) * 2

    # ATR % (14)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df['atr_pct_14'] = tr.rolling(14).mean() / (close + 1e-10)

    # Keltner position
    ema20  = close.ewm(span=20).mean()
    atr10  = tr.rolling(10).mean()
    k_up   = ema20 + 2 * atr10
    k_dn   = ema20 - 2 * atr10
    df['keltner_position'] = (close - k_dn) / (k_up - k_dn + 1e-10)

    # Squeeze indicator
    bb_std  = close.rolling(20).std()
    bb_up   = close.rolling(20).mean() + 2 * bb_std
    df['squeeze_on'] = (bb_up < k_up).astype(float)

    # EMA-9 distance
    ema9 = close.ewm(span=9).mean()
    df['ema_9_dist'] = (close - ema9) / (close + 1e-10)
    return df

def generate_experiences(symbol):
    """Vectorized experience generation with 56-dim features."""
    sym_file = symbol.replace('-', '_')
    candidates = [
        f'/srv/profitlab_quantum/data/historical/{sym_file}_5m_6m.parquet',
        f'/srv/profitlab_quantum/data/historical/{sym_file}_5m.parquet',
    ]
    
    parquet_path = None
    for c in candidates:
        if os.path.exists(c):
            parquet_path = c
            break
    
    if not parquet_path:
        logger.error(f'No parquet found for {symbol}')
        return []
    
    logger.info(f'Loading {parquet_path}')
    df = pd.read_parquet(parquet_path)
    logger.info(f'Loaded {len(df)} candles')
    
    # Calculate SMC features
    t0 = time.time()
    calc = SMCFeatureCalculator()
    features = calc.calculate_all(df)
    logger.info(f'SMC features: {time.time()-t0:.1f}s')
    
    for col in ['htf_bias', 'htf_trend']:
        if col not in features.columns:
            features[col] = 0.0
    
    features = add_golden_hour(features)
    features = add_technical_indicators(features)
    features = add_v3_pro_indicators(features)
    features = _add_v4_indicators(features)
    features = features.fillna(0.0)
    logger.info(f'All {INPUT_DIM} features computed')
    
    # ---- VECTORIZED: extract all states as numpy matrix ----
    # Ensure all STATE_COLUMNS exist
    for col in STATE_COLUMNS:
        if col not in features.columns:
            features[col] = 0.0
    
    all_states = features[STATE_COLUMNS].values.astype(np.float32)  # (N, 34)
    all_states = np.nan_to_num(all_states, nan=0.0, posinf=0.0, neginf=0.0)
    N = len(all_states)
    
    closes = features['close'].values.astype(np.float64)
    
    # Sliding window sequences using stride_tricks
    start_idx = SEQ_LEN + 200  # skip warmup
    end_idx = N - 1            # need i+1 for future return
    
    if end_idx <= start_idx:
        logger.warning(f'Not enough data for {symbol}')
        return []
    
    n_samples = end_idx - start_idx
    logger.info(f'Building {n_samples} sequences...')
    
    # Build all (32,34) sequences at once using numpy stride tricks
    # For each i in [start_idx, end_idx), sequence is all_states[i-31:i+1]
    strides = all_states.strides  # (row_stride, col_stride)
    shape = (N - SEQ_LEN + 1, SEQ_LEN, INPUT_DIM)
    strided = np.lib.stride_tricks.as_strided(all_states, shape=shape, strides=(strides[0],) + strides)
    
    # Select only the indices we need: from (start_idx - SEQ_LEN + 1) mapped to strided index
    # strided[k] = all_states[k:k+32], so for sample at position i, we need strided[i-31]
    seq_indices = np.arange(start_idx - SEQ_LEN + 1, end_idx - SEQ_LEN + 1)
    sequences = strided[seq_indices].copy()  # (n_samples, 32, 34) - copy to avoid stride issues
    
    # Compute future returns vectorized
    sample_indices = np.arange(start_idx, end_idx)
    future_ret = (closes[sample_indices + 1] - closes[sample_indices]) / (closes[sample_indices] + 1e-10)
    
    # Determine actions and rewards vectorized
    actions = np.full(n_samples, 2, dtype=np.int64)   # default Hold
    rewards = np.full(n_samples, 0.01, dtype=np.float64)
    
    buy_mask = future_ret > 0.001
    sell_mask = future_ret < -0.001
    
    actions[buy_mask] = 0
    rewards[buy_mask] = future_ret[buy_mask] * 100
    
    actions[sell_mask] = 1
    rewards[sell_mask] = -future_ret[sell_mask] * 100
    
    logger.info(f'Actions: Buy={buy_mask.sum()}, Sell={sell_mask.sum()}, Hold={(~buy_mask & ~sell_mask).sum()}')
    
    # Build memory tuples
    log_prob = torch.tensor(-1.0)
    value = torch.tensor(0.0)
    
    memory = []
    for i in range(n_samples):
        ts_ms = int((start_idx + i) * 300000)
        memory.append((ts_ms, sequences[i], int(actions[i]), float(rewards[i]), 0.0, log_prob, value))
    
    logger.info(f'Generated {len(memory)} experiences')
    
    # Free memory
    del strided, sequences, features, df
    gc.collect()
    
    return memory

def get_weights_path(symbol):
    if PPO_PER_SYMBOL:
        return Path(PPO_WEIGHTS_DIR) / symbol.replace('/', '_') / 'ppo.pt'
    return Path(PPO_WEIGHTS_PATH)

def train_symbol(symbol):
    logger.info(f'\n{"="*60}')
    logger.info(f'OFFLINE TRAINING {symbol}')
    logger.info(f'{"="*60}')
    
    all_memory = generate_experiences(symbol)
    if len(all_memory) < 128:
        logger.warning(f'Too few experiences ({len(all_memory)}). Skipping.')
        return False
    
    # Use most recent 4096 samples
    if len(all_memory) > 4096:
        all_memory = all_memory[-4096:]
    
    logger.info(f'Training with {len(all_memory)} samples')
    
    weights_path = get_weights_path(symbol)
    
    # Create FRESH agent (ignore incompatible 25-dim backup weights)
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove old incompatible weights if they exist
    if weights_path.exists():
        old_state = torch.load(str(weights_path), map_location='cpu', weights_only=True)
        if 'model_state_dict' in old_state:
            first_key = list(old_state['model_state_dict'].keys())[0]
            if old_state['model_state_dict'][first_key].shape[-1] != INPUT_DIM:
                logger.info(f'Removing incompatible old weights (dim={old_state["model_state_dict"][first_key].shape[-1]})')
                weights_path.unlink()
    
    agent = QuantumAgent(
        input_dim=INPUT_DIM,
        action_dim=3,
        autosave_path=str(weights_path),
        autosave_every_updates=1,
        db_url=DATABASE_URL,
        symbol=symbol,
    )
    logger.info(f'Training on device: {agent.device}')
    
    for update_i in range(NUM_UPDATES):
        agent.memory = list(all_memory)
        if update_i > 0:
            random.shuffle(agent.memory)
        
        initial_count = agent._update_count
        agent.update(clear_memory=False)
        
        if agent._update_count > initial_count:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: OK (count={agent._update_count})')
        else:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: No update')
            break
    
    agent.save(str(weights_path))
    logger.info(f'Weights saved: {weights_path} ({weights_path.stat().st_size/1024:.1f} KB)')
    
    # Free GPU memory
    del agent
    gc.collect()
    torch.cuda.empty_cache()
    
    return True

def main():
    logger.info('='*60)
    logger.info('OFFLINE TRAINING V2 - VECTORIZED')
    logger.info(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"}')
    logger.info(f'Tokens: {NEW_SYMBOLS}')
    logger.info(f'Updates per token: {NUM_UPDATES}')
    logger.info('='*60)
    
    start = time.time()
    results = {}
    
    for symbol in NEW_SYMBOLS:
        try:
            t0 = time.time()
            ok = train_symbol(symbol)
            dt = time.time() - t0
            results[symbol] = f'OK ({dt:.1f}s)' if ok else 'SKIPPED'
        except Exception as e:
            logger.error(f'FAILED {symbol}: {e}')
            import traceback; traceback.print_exc()
            results[symbol] = f'FAILED: {e}'
    
    elapsed = time.time() - start
    
    logger.info(f'\n{"="*60}')
    logger.info(f'TRAINING COMPLETE - Total: {elapsed:.1f}s')
    for sym, status in results.items():
        logger.info(f'  {sym}: {status}')
    
    logger.info('\nAll weight files:')
    all_syms = ['BTC-USDT','ETH-USDT','BNB-USDT','SOL-USDT','XRP-USDT',
                'ADA-USDT','DOGE-USDT','AVAX-USDT','TRX-USDT','DOT-USDT']
    for sym in all_syms:
        p = get_weights_path(sym)
        if p.exists():
            sz = p.stat().st_size / 1024
            logger.info(f'  {p}: {sz:.1f} KB')
        else:
            logger.info(f'  {p}: MISSING')
    logger.info('='*60)

if __name__ == '__main__':
    main()
