#!/usr/bin/env python3
"""
Download 18 months of 5m candles from BingX public API for all 10 tokens.
Then deep-train PPO models with expanded 48-dim feature set.
"""
import os, sys, time, logging, json, gc, random
import numpy as np
import torch
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

os.chdir('/srv/profitlab_quantum')
sys.path.insert(0, '/srv/profitlab_quantum')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('deep_train')

from app.config import DATABASE_URL, PPO_WEIGHTS_DIR, PPO_WEIGHTS_PATH, PPO_PER_SYMBOL
from app.features.smc_features import SMCFeatureCalculator
from app.models.agent import QuantumAgent

ALL_SYMBOLS = [
    'BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 'XRP-USDT',
    'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'TRX-USDT', 'DOT-USDT'
]

NUM_UPDATES = 50
MAX_SAMPLES = 16384
SEQ_LEN = 32
MONTHS_BACK = 18
BATCH_DAYS = 7  # BingX returns max ~1440 candles per request (5 days of 5m)

# ========== NEW 48-DIM STATE COLUMNS ==========
STATE_COLUMNS = [
    # OHLCV (5)
    'open', 'high', 'low', 'close', 'volume',
    # SMC Features (8)
    'fvg_bull_size', 'fvg_bear_size', 'is_fvg_bull', 'is_fvg_bear',
    'is_sweep_high', 'is_sweep_low',
    'bull_ob_distance', 'bear_ob_distance',
    # OB Metadata (6)
    'bull_ob_age', 'bear_ob_age',
    'bull_ob_tests', 'bear_ob_tests',
    'bull_ob_mitigated', 'bear_ob_mitigated',
    # HTF Context (2)
    'htf_bias', 'htf_trend',
    # Golden Hour Features (4)
    'hour_sin', 'hour_cos',
    'is_golden_hour', 'liquidity_score',
    # V2 Technical (9) - existing
    'rsi_normalized', 'atr_pct',
    'ema_20_dist', 'ema_50_dist', 'ema_200_dist',
    'volume_ratio', 'momentum_5', 'momentum_10', 'trend_strength',
    # V3 PRO Indicators (14) - NEW
    'macd_signal_dist',    # MACD - Signal distance normalized
    'macd_histogram',      # MACD histogram normalized
    'bb_position',         # Bollinger Band position [0,1]
    'bb_width',            # Bollinger Band width (volatility)
    'stoch_k',             # Stochastic %K normalized [-1,1]
    'stoch_d',             # Stochastic %D normalized [-1,1]
    'adx_normalized',      # ADX normalized [0,1]
    'obv_slope',           # OBV slope (accumulation/distribution)
    'vwap_dist',           # Distance to VWAP
    'price_change_1h',     # 1h price change (12 candles)
    'price_change_4h',     # 4h price change (48 candles)
    'high_low_ratio',      # High-Low range / close (volatility)
    'close_position',      # Where close sits in H-L range [0,1]
    'volume_momentum',     # Volume change rate
    # V4: Additional PPO Learning (8)
    'rsi_14', 'williams_r', 'cci_normalized', 'mfi_normalized',
    'atr_pct_14', 'keltner_position', 'squeeze_on', 'ema_9_dist',
]

INPUT_DIM = len(STATE_COLUMNS)  # 56

# ========== DOWNLOAD ==========

def _fetch_candle_batch(bingx_symbol, start_ms, end_ms):
    """Fetch a single batch of candles with retry logic."""
    base_url = "https://open-api-swap.bingx.com/openApi/swap/v3/quote/klines"
    params = {
        'symbol': bingx_symbol, 'interval': '5m',
        'startTime': start_ms, 'endTime': end_ms, 'limit': 1440,
    }
    for attempt in range(3):
        try:
            resp = requests.get(base_url, params=params, timeout=10)
            data = resp.json()
            if 'data' in data and data['data']:
                return [
                    {'time': int(c.get('time', c.get('openTime', 0))),
                     'open': float(c['open']), 'high': float(c['high']),
                     'low': float(c['low']), 'close': float(c['close']),
                     'volume': float(c['volume'])}
                    for c in data['data']
                ]
            return []
        except Exception as e:
            if attempt == 2:
                logger.warning(f'Failed batch: {e}')
            time.sleep(1)
    return []


def download_candles_bingx(symbol: str, months: int = 18) -> pd.DataFrame:
    """Download historical 5m candles from BingX public API."""
    bingx_symbol = symbol.replace('-', '-')  # BTC-USDT format
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=months * 30)

    all_candles = []
    current_start = start_time

    logger.info(f'Downloading {symbol}: {start_time.strftime("%Y-%m-%d")} → {end_time.strftime("%Y-%m-%d")}')

    while current_start < end_time:
        current_end = min(current_start + timedelta(days=BATCH_DAYS), end_time)
        batch = _fetch_candle_batch(
            bingx_symbol,
            int(current_start.timestamp() * 1000),
            int(current_end.timestamp() * 1000),
        )
        all_candles.extend(batch)
        current_start = current_end
        time.sleep(0.15)

    if not all_candles:
        logger.error(f'No candles downloaded for {symbol}')
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    df = df.drop_duplicates(subset='time').sort_values('time').reset_index(drop=True)
    logger.info(f'Downloaded {len(df)} candles for {symbol} ({len(df)/288:.0f} days)')
    return df

# ========== FEATURE ENGINEERING ==========

def add_v2_technical(df):
    """V2 technical indicators (existing 9)."""
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float)
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    df['rsi_normalized'] = (rsi - 50) / 50
    
    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    df['atr_pct'] = atr / (close + 1e-10)
    
    # EMAs
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    df['ema_20_dist'] = (close - ema20) / (close + 1e-10)
    df['ema_50_dist'] = (close - ema50) / (close + 1e-10)
    df['ema_200_dist'] = (close - ema200) / (close + 1e-10)
    
    # Volume ratio
    vol_ma = volume.rolling(20).mean()
    df['volume_ratio'] = volume / (vol_ma + 1e-10)
    
    # Momentum
    df['momentum_5'] = close.pct_change(5)
    df['momentum_10'] = close.pct_change(10)
    
    # Trend strength
    df['trend_strength'] = (ema20 - ema50) / (close + 1e-10)
    return df

def add_v3_pro_indicators(df):
    """V3 PRO indicators - 14 new institutional-grade features."""
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float)
    
    # --- MACD (12, 26, 9) ---
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    df['macd_signal_dist'] = (macd_line - signal_line) / (close + 1e-10)
    df['macd_histogram'] = df['macd_signal_dist'].copy()  # normalized histogram
    
    # --- Bollinger Bands (20, 2) ---
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_range = bb_upper - bb_lower
    df['bb_position'] = (close - bb_lower) / (bb_range + 1e-10)  # [0, 1]
    df['bb_width'] = bb_range / (bb_mid + 1e-10)  # volatility
    
    # --- Stochastic (14, 3) ---
    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = (close - low14) / (high14 - low14 + 1e-10)
    stoch_d = stoch_k.rolling(3).mean()
    df['stoch_k'] = (stoch_k - 0.5) * 2  # normalize to [-1, 1]
    df['stoch_d'] = (stoch_d - 0.5) * 2
    
    # --- ADX (14) ---
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
    df['adx_normalized'] = adx / 100.0  # [0, 1]
    
    # --- OBV slope ---
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_ma = obv.rolling(20).mean()
    df['obv_slope'] = (obv - obv_ma) / (obv_ma.abs() + 1e-10)
    
    # --- VWAP (session-based, approximation using rolling) ---
    typical_price = (high + low + close) / 3
    cum_vol = volume.rolling(288).sum()  # ~1 day of 5m candles
    cum_tp_vol = (typical_price * volume).rolling(288).sum()
    vwap = cum_tp_vol / (cum_vol + 1e-10)
    df['vwap_dist'] = (close - vwap) / (close + 1e-10)
    
    # --- Multi-timeframe price changes ---
    df['price_change_1h'] = close.pct_change(12)   # 12 x 5m = 1h
    df['price_change_4h'] = close.pct_change(48)   # 48 x 5m = 4h
    
    # --- Volatility & structure ---
    df['high_low_ratio'] = (high - low) / (close + 1e-10)
    df['close_position'] = (close - low) / (high - low + 1e-10)  # [0, 1]
    
    # --- Volume momentum ---
    df['volume_momentum'] = volume.pct_change(5)
    
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
            is_golden = ((hour_float >= 14.5) & (hour_float <= 17.0)).astype(float)
            is_silver = (((hour_float >= 7.0) & (hour_float <= 9.0)) | 
                        ((hour_float >= 21.0) & (hour_float <= 23.0))).astype(float)
            df['is_golden_hour'] = is_golden + is_silver * 0.5
            df['liquidity_score'] = np.where(
                (hour_float >= 8) & (hour_float <= 17), 0.8,
                np.where((hour_float >= 1) & (hour_float <= 8), 0.5, 0.3)
            )
        except Exception:
            pass
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
    df['rsi_14'] = (rs / (1 + rs) - 0.5) * 2          # normalised [-1,1]

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

# ========== EXPERIENCE GENERATION ==========

def generate_experiences(symbol, df):
    """Vectorized experience generation with 56-dim features."""
    logger.info(f'Computing features for {len(df)} candles...')
    t0 = time.time()
    
    calc = SMCFeatureCalculator()
    features = calc.calculate_all(df)
    logger.info(f'  SMC features: {time.time()-t0:.1f}s')
    
    for col in ['htf_bias', 'htf_trend']:
        if col not in features.columns:
            features[col] = 0.0
    
    features = add_golden_hour(features)
    features = add_v2_technical(features)
    features = add_v3_pro_indicators(features)
    features = _add_v4_indicators(features)
    features = features.fillna(0.0)
    
    # Ensure all columns exist
    for col in STATE_COLUMNS:
        if col not in features.columns:
            features[col] = 0.0
    
    logger.info(f'  All {INPUT_DIM} features computed: {time.time()-t0:.1f}s')
    
    # Vectorized state matrix
    all_states = features[STATE_COLUMNS].values.astype(np.float32)
    all_states = np.nan_to_num(all_states, nan=0.0, posinf=0.0, neginf=0.0)
    N = len(all_states)
    
    closes = features['close'].values.astype(np.float64)
    
    start_idx = max(SEQ_LEN + 300, 300)  # extra warmup for 200-EMA & 288-VWAP
    end_idx = N - 1
    
    if end_idx <= start_idx:
        logger.warning(f'Not enough data for {symbol}')
        return []
    
    n_samples = end_idx - start_idx
    logger.info(f'  Building {n_samples} sequences...')
    
    # Stride tricks for sliding window
    strides = all_states.strides
    shape = (N - SEQ_LEN + 1, SEQ_LEN, INPUT_DIM)
    strided = np.lib.stride_tricks.as_strided(all_states, shape=shape, strides=(strides[0],) + strides)
    
    seq_indices = np.arange(start_idx - SEQ_LEN + 1, end_idx - SEQ_LEN + 1)
    sequences = strided[seq_indices].copy()
    
    # Future returns
    sample_indices = np.arange(start_idx, end_idx)
    future_ret = (closes[sample_indices + 1] - closes[sample_indices]) / (closes[sample_indices] + 1e-10)
    
    # Actions & rewards
    actions = np.full(n_samples, 2, dtype=np.int64)   # Hold
    rewards = np.full(n_samples, 0.01, dtype=np.float64)
    
    buy_mask = future_ret > 0.001
    sell_mask = future_ret < -0.001
    
    actions[buy_mask] = 0
    rewards[buy_mask] = future_ret[buy_mask] * 100
    
    actions[sell_mask] = 1
    rewards[sell_mask] = -future_ret[sell_mask] * 100
    
    logger.info(f'  Actions: Buy={buy_mask.sum()}, Sell={sell_mask.sum()}, Hold={(~buy_mask & ~sell_mask).sum()}')
    
    # Build memory tuples
    log_prob = torch.tensor(-1.0)
    value = torch.tensor(0.0)
    
    memory = []
    for i in range(n_samples):
        ts_ms = int((start_idx + i) * 300000)
        memory.append((ts_ms, sequences[i], int(actions[i]), float(rewards[i]), 0.0, log_prob, value))
    
    logger.info(f'  Generated {len(memory)} experiences ({time.time()-t0:.1f}s total)')
    
    del strided, sequences, features
    gc.collect()
    
    return memory

# ========== TRAINING ==========

def get_weights_path(symbol):
    if PPO_PER_SYMBOL:
        return Path(PPO_WEIGHTS_DIR) / symbol.replace('/', '_') / 'ppo.pt'
    return Path(PPO_WEIGHTS_PATH)

def _remove_incompatible_weights(weights_path):
    """Remove old weights if input dimension doesn't match."""
    if not weights_path.exists():
        return
    try:
        old_state = torch.load(str(weights_path), map_location='cpu', weights_only=True)
        model_dict = old_state.get('model_state_dict', {})
        first_key = [k for k in model_dict if 'input_proj.weight' in k]
        if first_key:
            old_dim = model_dict[first_key[0]].shape[-1]
            if old_dim != INPUT_DIM:
                logger.info(f'  Removing old weights (dim={old_dim} != {INPUT_DIM})')
                weights_path.unlink()
    except Exception:
        weights_path.unlink(missing_ok=True)


def _run_ppo_updates(agent, all_memory):
    """Run NUM_UPDATES PPO update passes on the agent."""
    for update_i in range(NUM_UPDATES):
        agent.memory = list(all_memory)
        if update_i > 0:
            random.shuffle(agent.memory)
        initial_count = agent._update_count
        agent.update(clear_memory=False)
        if agent._update_count <= initial_count:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: No update — stopping')
            break
        if (update_i + 1) % 10 == 0 or update_i == 0:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: OK (count={agent._update_count})')


def train_symbol(symbol, df):
    logger.info(f'\n{"="*60}')
    logger.info(f'DEEP TRAINING {symbol}')
    logger.info(f'{"="*60}')
    
    all_memory = generate_experiences(symbol, df)
    if len(all_memory) < 128:
        logger.warning(f'Too few experiences ({len(all_memory)}). Skipping.')
        return False
    
    if len(all_memory) > MAX_SAMPLES:
        all_memory = all_memory[-MAX_SAMPLES:]
    
    logger.info(f'Training with {len(all_memory)} samples, {NUM_UPDATES} updates')
    
    weights_path = get_weights_path(symbol)
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_incompatible_weights(weights_path)
    
    agent = QuantumAgent(
        input_dim=INPUT_DIM,
        action_dim=3,
        autosave_path=str(weights_path),
        autosave_every_updates=5,
        db_url=DATABASE_URL,
        symbol=symbol,
    )
    logger.info(f'  Device: {agent.device}, input_dim={INPUT_DIM}')
    
    _run_ppo_updates(agent, all_memory)
    
    agent.save(str(weights_path))
    sz = weights_path.stat().st_size / 1024
    logger.info(f'  Saved: {weights_path} ({sz:.1f} KB)')
    
    del agent
    gc.collect()
    torch.cuda.empty_cache()
    
    return True

# ========== MAIN ==========

def _load_or_download(symbol, data_dir):
    """Load cached parquet or download fresh from BingX. Returns DataFrame."""
    sym_file = symbol.replace('-', '_')
    parquet_18m = data_dir / f'{sym_file}_5m_18m.parquet'
    if parquet_18m.exists():
        age_h = (time.time() - parquet_18m.stat().st_mtime) / 3600
        if age_h < 12:
            logger.info(f'Using cached {parquet_18m.name} ({age_h:.1f}h old)')
            return pd.read_parquet(parquet_18m)
    df = download_candles_bingx(symbol, MONTHS_BACK)
    if len(df) > 0:
        df.to_parquet(parquet_18m, index=False)
    return df


def _log_final_report(results, elapsed):
    """Print final training report with weight file sizes."""
    logger.info(f'\n{"="*60}')
    logger.info(f'DEEP TRAINING COMPLETE - {elapsed:.1f}s')
    for sym, status in results.items():
        logger.info(f'  {sym}: {status}')
    logger.info('\nWeight files:')
    for sym in ALL_SYMBOLS:
        p = get_weights_path(sym)
        size_info = f'{p.stat().st_size/1024:.1f} KB' if p.exists() else 'MISSING'
        logger.info(f'  {p}: {size_info}')
    logger.info('='*60)


def main():
    logger.info('='*60)
    logger.info('DEEP TRAINING V3 - 56 FEATURES, 18 MONTHS, 50 UPDATES')
    logger.info(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"}')
    logger.info(f'Tokens: {ALL_SYMBOLS}')
    logger.info(f'Input dim: {INPUT_DIM}, Seq len: {SEQ_LEN}')
    logger.info(f'Max samples: {MAX_SAMPLES}, Updates: {NUM_UPDATES}')
    logger.info('='*60)
    
    data_dir = Path('/srv/profitlab_quantum/data/historical')
    data_dir.mkdir(parents=True, exist_ok=True)
    
    start_total = time.time()
    results = {}
    
    for symbol in ALL_SYMBOLS:
        try:
            df = _load_or_download(symbol, data_dir)
            if len(df) < 1000:
                logger.error(f'{symbol}: Only {len(df)} candles, skipping')
                results[symbol] = 'FAILED: insufficient data'
                continue
            
            t0 = time.time()
            ok = train_symbol(symbol, df)
            dt = time.time() - t0
            results[symbol] = f'OK ({dt:.1f}s, {len(df)} candles)' if ok else 'SKIPPED'
            
            del df
            gc.collect()
            
        except Exception as e:
            logger.error(f'FAILED {symbol}: {e}')
            import traceback; traceback.print_exc()
            results[symbol] = f'FAILED: {e}'
    
    _log_final_report(results, time.time() - start_total)

if __name__ == '__main__':
    main()
