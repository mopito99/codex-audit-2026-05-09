#!/usr/bin/env python3
"""
DEEP TRAIN V3 PRO — 48 features, 18 months, direct on GPU server.
Downloads from open-api.bingx.com (works from USA datacenter).
Trains all 10 tokens with expanded V3 PRO indicators.
"""
import os, sys, time, json, logging, math
import requests
import numpy as np
import pandas as pd
import torch

os.chdir('/srv/profitlab_quantum')
sys.path.insert(0, '/srv/profitlab_quantum')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('deep_train_v3')

from pathlib import Path
from app.models.agent import QuantumAgent
from app.features.smc_features import SMCFeatureCalculator

# ── Config ─────────────────────────────────────────────────
SYMBOLS = ['BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 'XRP-USDT',
           'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'TRX-USDT', 'DOT-USDT']
TIMEFRAME = '5m'
MONTHS_BACK = 3  # BingX REST v3 limit: ~90 days
NUM_UPDATES = 50
MAX_SAMPLES = 8192
SEQ_LEN = 32
INPUT_DIM = 56
ACTION_DIM = 3
WEIGHTS_DIR = Path('/srv/profitlab_quantum/artifacts/ppo/by_symbol')
DATA_DIR = Path('/srv/profitlab_quantum/data/historical')
DATA_DIR.mkdir(parents=True, exist_ok=True)

BINGX_BASE = "https://open-api.bingx.com"

# ── Download from BingX REST (open-api.bingx.com) ─────────
def _fetch_candle_batch_v3(url, params):
    """Fetch a single batch of candles with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            if data.get('code') == 0 and data.get('data'):
                return [
                    {'time': int(c.get('time', 0)), 'open': float(c['open']),
                     'high': float(c['high']), 'low': float(c['low']),
                     'close': float(c['close']), 'volume': float(c.get('volume', 0))}
                    for c in data['data']
                ]
            msg = data.get('msg', 'unknown')
            if attempt == 2:
                logger.warning(f'  API error: {msg}')
            time.sleep(0.5)
        except Exception as e:
            if attempt == 2:
                logger.warning(f'  Failed batch: {e}')
            time.sleep(1)
    return []


def download_candles_bingx(symbol: str, months: int = 18) -> pd.DataFrame:
    """Download 5m candles from BingX v3 public REST API."""
    url = f"{BINGX_BASE}/openApi/swap/v3/quote/klines"
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (months * 30 * 24 * 3600 * 1000)
    batch_size_ms = 3 * 24 * 3600 * 1000  # 3 days per batch

    all_candles = []
    current_start = start_ms
    batch_num = 0

    while current_start < now_ms:
        batch_end = min(current_start + batch_size_ms, now_ms)
        params = {
            'symbol': symbol, 'interval': TIMEFRAME,
            'startTime': current_start, 'endTime': batch_end, 'limit': 1440,
        }
        all_candles.extend(_fetch_candle_batch_v3(url, params))
        current_start = batch_end
        batch_num += 1
        if batch_num % 20 == 0:
            logger.info(f'  {symbol}: {len(all_candles)} candles, batch {batch_num}...')
        time.sleep(0.12)

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    df = df.drop_duplicates(subset='time').sort_values('time').reset_index(drop=True)
    return df

# ── Feature Engineering (48 dims) ─────────────────────────
def add_golden_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Add London/NY session overlap features."""
    if 'time' not in df.columns:
        df['gh_active'] = 0.0
        df['gh_volume_ratio'] = 1.0
        df['gh_volatility_ratio'] = 1.0
        df['gh_momentum'] = 0.0
        return df
    
    hours = pd.to_datetime(df['time'], unit='ms').dt.hour
    df['gh_active'] = ((hours >= 13) & (hours < 17)).astype(float)
    
    vol_mean = df['volume'].rolling(48, min_periods=1).mean()
    df['gh_volume_ratio'] = np.where(vol_mean > 0, df['volume'] / vol_mean, 1.0)
    
    hl = df['high'] - df['low']
    hl_mean = hl.rolling(48, min_periods=1).mean()
    df['gh_volatility_ratio'] = np.where(hl_mean > 0, hl / hl_mean, 1.0)
    
    df['gh_momentum'] = df['close'].pct_change(12).fillna(0)
    return df

def add_v2_technical(df: pd.DataFrame) -> pd.DataFrame:
    """Add 9 V2 technical features."""
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']
    
    # RSI (14)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    rs = np.where(loss > 0, gain / loss, 50.0)
    df['rsi_14'] = (100 - 100 / (1 + rs)) / 100.0
    
    # EMA cross (8/21)
    ema8 = c.ewm(span=8, adjust=False).mean()
    ema21 = c.ewm(span=21, adjust=False).mean()
    df['ema_cross'] = np.where(ema21 > 0, (ema8 - ema21) / ema21, 0.0)
    
    # ATR (14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=1).mean()
    df['atr_norm'] = np.where(c > 0, atr / c, 0.0)
    
    # Volume SMA ratio
    vol_sma = v.rolling(20, min_periods=1).mean()
    df['vol_sma_ratio'] = np.where(vol_sma > 0, v / vol_sma, 1.0)
    
    # Momentum (10-bar)
    df['momentum_10'] = c.pct_change(10).fillna(0)
    
    # Price position in range
    h20 = h.rolling(20, min_periods=1).max()
    l20 = l.rolling(20, min_periods=1).min()
    rng = h20 - l20
    df['price_position'] = np.where(rng > 0, (c - l20) / rng, 0.5)
    
    # Candle body ratio
    body = (c - df['open']).abs()
    wick = h - l
    df['candle_body_ratio'] = np.where(wick > 0, body / wick, 0.5)
    
    # Volume trend
    v5 = v.rolling(5, min_periods=1).mean()
    v20 = v.rolling(20, min_periods=1).mean()
    df['volume_trend'] = np.where(v20 > 0, v5 / v20, 1.0)
    
    # Volatility (20-bar std)
    ret = c.pct_change().fillna(0)
    df['volatility_20'] = ret.rolling(20, min_periods=1).std().fillna(0)
    
    return df

def add_v3_pro_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add 14 V3 PRO institutional indicators."""
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df['macd_signal_dist'] = np.where(c > 0, (macd_line - signal_line) / c, 0.0)
    df['macd_histogram'] = np.where(c > 0, (macd_line - signal_line) / c, 0.0)
    
    # Bollinger Bands
    sma20 = c.rolling(20, min_periods=1).mean()
    std20 = c.rolling(20, min_periods=1).std().fillna(1e-8)
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    bb_width = upper - lower
    df['bb_position'] = np.where(bb_width > 0, (c - lower) / bb_width, 0.5)
    df['bb_width'] = np.where(c > 0, bb_width / c, 0.0)
    
    # Stochastic
    l14 = l.rolling(14, min_periods=1).min()
    h14 = h.rolling(14, min_periods=1).max()
    rng14 = h14 - l14
    k = np.where(rng14 > 0, (c - l14) / rng14, 0.5)
    df['stoch_k'] = k
    df['stoch_d'] = pd.Series(k).rolling(3, min_periods=1).mean().values
    
    # ADX
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=1).mean()
    plus_dm = np.where((h.diff() > 0) & (h.diff() > -l.diff()), h.diff(), 0.0)
    minus_dm = np.where((l.diff() < 0) & (-l.diff() > h.diff()), -l.diff(), 0.0)
    plus_di = pd.Series(plus_dm).rolling(14, min_periods=1).mean() / atr14.clip(lower=1e-8)
    minus_di = pd.Series(minus_dm).rolling(14, min_periods=1).mean() / atr14.clip(lower=1e-8)
    dx = np.where((plus_di + minus_di) > 0,
                  np.abs(plus_di - minus_di) / (plus_di + minus_di), 0.0)
    df['adx_norm'] = pd.Series(dx).rolling(14, min_periods=1).mean().values
    
    # OBV slope
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    obv_sma = obv.rolling(20, min_periods=1).mean()
    df['obv_slope'] = np.where(obv_sma.abs() > 0,
                               (obv - obv_sma) / obv_sma.abs().clip(lower=1e-8), 0.0)
    
    # VWAP distance
    cum_vol = v.cumsum()
    cum_vp = (c * v).cumsum()
    vwap = np.where(cum_vol > 0, cum_vp / cum_vol, c)
    df['vwap_dist'] = np.where(c > 0, (c - vwap) / c, 0.0)
    
    # Multi-TF returns
    df['price_change_1h'] = c.pct_change(12).fillna(0)
    df['price_change_4h'] = c.pct_change(48).fillna(0)
    
    # Volatility metrics
    df['high_low_ratio'] = np.where(l > 0, h / l - 1, 0.0)
    df['close_position'] = np.where((h - l) > 0, (c - l) / (h - l), 0.5)
    df['volume_momentum'] = v.pct_change(5).fillna(0).clip(-5, 5)
    
    return df


def _add_v4_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add 8 V4 PPO learning indicators (must match engine.py V4 columns)."""
    c = df['close'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    v = df['volume'].astype(float)

    # RSI(14) normalized [-1,1]
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
    loss_s = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=1).mean()
    rs = gain / (loss_s + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    df['rsi_14'] = (rsi - 50) / 50

    # Williams %R(14) normalized [-1,1]
    h14 = h.rolling(14, min_periods=1).max()
    l14 = l.rolling(14, min_periods=1).min()
    rng14 = h14 - l14
    wr = np.where(rng14 > 0, -100 * (h14 - c) / rng14, -50.0)
    df['williams_r'] = (np.array(wr) + 50) / 50

    # CCI(20) normalized
    tp = (h + l + c) / 3
    sma_tp = tp.rolling(20, min_periods=1).mean()
    mad = tp.rolling(20, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma_tp) / (0.015 * mad + 1e-10)
    df['cci_normalized'] = (cci / 200).clip(-1, 1)

    # MFI(14) normalized [-1,1]
    tp_v = tp * v
    pos_flow = tp_v.where(tp.diff() > 0, 0.0).rolling(14, min_periods=1).sum()
    neg_flow = tp_v.where(tp.diff() <= 0, 0.0).rolling(14, min_periods=1).sum()
    mfi = 100 - 100 / (1 + pos_flow / (neg_flow + 1e-10))
    df['mfi_normalized'] = (mfi - 50) / 50

    # ATR%(14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=1).mean()
    df['atr_pct_14'] = atr14 / (c + 1e-10)

    # Keltner Channel position [0,1]
    ema20 = c.ewm(span=20, adjust=False).mean()
    kc_upper = ema20 + 1.5 * atr14
    kc_lower = ema20 - 1.5 * atr14
    kc_width = kc_upper - kc_lower
    df['keltner_position'] = np.where(kc_width > 0, (c - kc_lower) / kc_width, 0.5).clip(0, 1)

    # Squeeze indicator (BB inside KC)
    sma20 = c.rolling(20, min_periods=1).mean()
    std20 = c.rolling(20, min_periods=1).std().fillna(1e-8)
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    df['squeeze_on'] = ((bb_lower > kc_lower) & (bb_upper < kc_upper)).astype(float)

    # EMA(9) distance
    ema9 = c.ewm(span=9, adjust=False).mean()
    df['ema_9_dist'] = (c - ema9) / (c + 1e-10)

    return df


def build_features(df: pd.DataFrame) -> np.ndarray:
    """Build full 48-dim feature matrix from OHLCV DataFrame."""
    # SMC features (8 SMC + 6 OB + 2 HTF = 16)
    smc = SMCFeatureCalculator()
    df_smc = smc.calculate_all(df)
    
    # Golden Hour (4)
    df_smc = add_golden_hour(df_smc)
    
    # V2 Technical (9)
    df_smc = add_v2_technical(df_smc)
    
    # V3 PRO (14)
    df_smc = add_v3_pro_indicators(df_smc)

    # V4 indicators (8)
    df_smc = _add_v4_indicators(df_smc)

    # State columns (must match engine.py exactly)
    state_columns = [
        # OHLCV (5)
        'open', 'high', 'low', 'close', 'volume',
        # SMC (8)
        'trend_direction', 'trend_strength', 'displacement_intensity',
        'premium_discount_zone', 'inducement_proximity', 'bos_signal',
        'choch_signal', 'smc_confluence_score',
        # Order Blocks (6)
        'nearest_ob_distance', 'nearest_ob_strength', 'nearest_ob_type_encoded',
        'ob_cluster_density', 'inside_ob_zone', 'ob_rejection_count',
        # HTF (2)
        'htf_trend_alignment', 'htf_key_level_proximity',
        # Golden Hour (4)
        'gh_active', 'gh_volume_ratio', 'gh_volatility_ratio', 'gh_momentum',
        # V2 Technical (9)
        'rsi_14', 'ema_cross', 'atr_norm', 'vol_sma_ratio', 'momentum_10',
        'price_position', 'candle_body_ratio', 'volume_trend', 'volatility_20',
        # V3 PRO (14)
        'macd_signal_dist', 'macd_histogram', 'bb_position', 'bb_width',
        'stoch_k', 'stoch_d', 'adx_norm', 'obv_slope', 'vwap_dist',
        'price_change_1h', 'price_change_4h', 'high_low_ratio',
        'close_position', 'volume_momentum',
        # V4: Additional PPO Learning (8)
        'rsi_14', 'williams_r', 'cci_normalized', 'mfi_normalized',
        'atr_pct_14', 'keltner_position', 'squeeze_on', 'ema_9_dist',
    ]
    
    assert len(state_columns) == INPUT_DIM, f"Expected {INPUT_DIM} columns, got {len(state_columns)}"
    
    # Fill missing columns with 0
    for col in state_columns:
        if col not in df_smc.columns:
            df_smc[col] = 0.0
    
    # Extract and clean
    matrix = df_smc[state_columns].values.astype(np.float32)
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=10.0, neginf=-10.0)
    matrix = np.clip(matrix, -100, 100)
    
    return matrix

# ── Vectorized Experience Generation ──────────────────────
def generate_experiences(features: np.ndarray, seq_len: int = 32) -> list:
    """Generate PPO-compatible experiences from feature matrix using stride tricks."""
    n = len(features)
    if n < seq_len + 2:
        return []
    
    experiences = []
    # Use stride tricks for efficient sequence creation
    stride = features.strides
    shape = (n - seq_len, seq_len, features.shape[1])
    strides = (stride[0], stride[0], stride[1])
    sequences = np.lib.stride_tricks.as_strided(features, shape=shape, strides=strides)
    
    # Compute returns for rewards
    close_idx = 3  # 'close' is index 3
    closes = features[:, close_idx]
    returns = np.diff(closes) / np.clip(closes[:-1], 1e-8, None)
    returns = np.clip(returns, -0.1, 0.1)
    
    # Sample uniformly (cap at MAX_SAMPLES)
    total = len(sequences) - 1
    if total <= 0:
        return []
    
    indices = np.linspace(0, total - 1, min(MAX_SAMPLES, total), dtype=int)
    
    for i in indices:
        state = sequences[i].copy()  # [seq_len, INPUT_DIM]
        ret = returns[i + seq_len - 1] if (i + seq_len - 1) < len(returns) else 0.0
        
        # Action: 0=Buy if positive return, 1=Sell if negative, 2=Hold if small
        if ret > 0.001:
            action = 0
            reward = ret * 10
        elif ret < -0.001:
            action = 1
            reward = -ret * 10
        else:
            action = 2
            reward = 0.01
        
        ts_ms = int(time.time() * 1000) - (total - i) * 300000
        log_prob = torch.tensor(-1.1)
        value = torch.tensor(reward * 0.5)
        
        experiences.append((ts_ms, state, action, float(reward), 0.0, log_prob, value))
    
    return experiences

# ── Training Loop ─────────────────────────────────────────
def _load_or_download_cached(symbol, cache_path):
    """Load cached parquet or download fresh from BingX."""
    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < 24:
            logger.info(f'Using cached data ({age_h:.1f}h old)')
            return pd.read_parquet(cache_path)
        logger.info(f'Cache stale ({age_h:.1f}h), re-downloading...')
    else:
        logger.info(f'Downloading {MONTHS_BACK} months from BingX...')
    df = download_candles_bingx(symbol, MONTHS_BACK)
    if len(df) > 0:
        df.to_parquet(cache_path, index=False)
    return df


def _load_or_init_agent(weights_path):
    """Initialize QuantumAgent and load compatible weights if available."""
    agent = QuantumAgent(
        input_dim=INPUT_DIM, action_dim=ACTION_DIM,
        autosave_path=str(weights_path), autosave_every_updates=5,
    )
    if not weights_path.exists():
        return agent
    try:
        ckpt = torch.load(str(weights_path), map_location='cpu', weights_only=False)
        old_dim = ckpt.get('model_state_dict', {}).get('input_proj.weight', None)
        if old_dim is not None and old_dim.shape[1] != INPUT_DIM:
            logger.warning(f'Old weights dim={old_dim.shape[1]}, need {INPUT_DIM}. Training fresh.')
        else:
            agent.load(str(weights_path))
            logger.info(f'Loaded compatible weights (update_count={agent._update_count})')
    except Exception as e:
        logger.warning(f'Cannot load old weights: {e}. Training fresh.')
    return agent


def _run_updates(agent, experiences):
    """Run NUM_UPDATES PPO update passes."""
    import random
    start_count = agent._update_count
    for update_i in range(NUM_UPDATES):
        agent.memory = list(experiences)
        if update_i > 0:
            random.shuffle(agent.memory)
        prev = agent._update_count
        agent.update(clear_memory=False)
        if agent._update_count <= prev:
            logger.warning(f'  Update {update_i+1}: no progress, stopping')
            break
        if (update_i + 1) % 10 == 0 or update_i == 0:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: count={agent._update_count}')
    return agent._update_count - start_count


def train_symbol(symbol: str) -> dict:
    """Download data, build features, train PPO for one symbol."""
    logger.info(f'\n{"="*60}')
    logger.info(f'TRAINING {symbol}')
    logger.info(f'{"="*60}')
    
    safe_name = symbol.replace('-', '_')
    cache_path = DATA_DIR / f'{safe_name}_5m_{MONTHS_BACK}m.parquet'
    df = _load_or_download_cached(symbol, cache_path)
    
    if df is None or len(df) < 500:
        logger.error(f'Insufficient data ({len(df) if df is not None else 0} candles)')
        return {'status': 'FAILED', 'reason': 'no data'}
    
    days = len(df) / 288
    logger.info(f'Data: {len(df)} candles ({days:.0f} days)')
    
    logger.info('Building features...')
    features = build_features(df)
    logger.info(f'Feature matrix: {features.shape}')
    
    logger.info('Generating experiences...')
    experiences = generate_experiences(features, SEQ_LEN)
    logger.info(f'Experiences: {len(experiences)}')
    
    if len(experiences) < 128:
        logger.error(f'Too few experiences ({len(experiences)})')
        return {'status': 'FAILED', 'reason': 'too few experiences'}
    
    weights_path = WEIGHTS_DIR / symbol.replace('/', '_') / 'ppo.pt'
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    
    agent = _load_or_init_agent(weights_path)
    logger.info(f'Device: {agent.device}')
    
    total_updates = _run_updates(agent, experiences)
    
    agent.save(str(weights_path))
    logger.info(f'Saved: {weights_path} ({weights_path.stat().st_size/1024:.1f} KB)')
    logger.info(f'Updates applied: {total_updates}, Total: {agent._update_count}')
    
    return {
        'status': 'OK', 'candles': len(df), 'experiences': len(experiences),
        'updates': total_updates, 'total_count': agent._update_count,
        'weight_kb': weights_path.stat().st_size / 1024,
    }

# ── Main ──────────────────────────────────────────────────
def main():
    logger.info('=' * 60)
    logger.info('DEEP TRAIN V3 PRO — 48 FEATURES, 18 MONTHS')
    logger.info(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"}')
    logger.info(f'Tokens: {SYMBOLS}')
    logger.info(f'Input dim: {INPUT_DIM}, Seq len: {SEQ_LEN}')
    logger.info(f'Max samples: {MAX_SAMPLES}, Updates: {NUM_UPDATES}')
    logger.info('=' * 60)
    
    start = time.time()
    results = {}
    
    for symbol in SYMBOLS:
        try:
            results[symbol] = train_symbol(symbol)
        except Exception as e:
            logger.error(f'FAILED {symbol}: {e}')
            import traceback; traceback.print_exc()
            results[symbol] = {'status': f'ERROR: {e}'}
    
    elapsed = time.time() - start
    
    logger.info(f'\n{"="*60}')
    logger.info('DEEP TRAINING V3 COMPLETE')
    logger.info(f'Time: {elapsed:.1f}s ({elapsed/60:.1f} min)')
    logger.info(f'{"="*60}')
    
    for sym, res in results.items():
        status = res.get('status', '?')
        if status == 'OK':
            logger.info(f'  {sym}: OK — {res["candles"]} candles, '
                       f'{res["updates"]} updates, {res["weight_kb"]:.1f} KB')
        else:
            logger.info(f'  {sym}: {status}')
    
    ok_count = sum(1 for r in results.values() if r.get('status') == 'OK')
    logger.info(f'\nSuccess: {ok_count}/{len(SYMBOLS)}')
    logger.info('=' * 60)

if __name__ == '__main__':
    main()
