import pandas as pd
import numpy as np
from typing import Tuple, List, Optional

class SMCFeatureCalculator:
    """
    Calculates Smart Money Concepts (SMC) features:
    - Order Blocks (OB)
    - Fair Value Gaps (FVG)
    - Liquidity Sweeps
    """

    def __init__(self):
        pass

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        V2.0: Applies all SMC calculations + technical indicators.
        Expects columns: 'open', 'high', 'low', 'close', 'volume'.
        """
        df = df.copy()
        df = self.detect_fair_value_gaps(df)
        df = self.detect_order_blocks(df)
        df = self.detect_liquidity_sweeps(df)
        df = self.calculate_technical_indicators(df)  # V2.0 - Technical indicators
        return df

    def detect_fair_value_gaps(self, df: pd.DataFrame, threshold_atr_mult: float = 0.75) -> pd.DataFrame:
        """
        Detects Fair Value Gaps (FVG).
        Bullish FVG: Low[i-2] > High[i]
        Bearish FVG: High[i-2] < Low[i]
        """
        high = df['high']
        low = df['low']
        
        # Shifted series for comparison
        # i is current candle (completed). We look at i (current), i-1 (middle), i-2 (first)
        # In pandas, shift(1) is i-1.
        
        # Bullish FVG condition: Low of candle i-2 > High of candle i
        # We want to mark this on candle i.
        # low.shift(2) > high
        
        bull_fvg = (low.shift(2) > high)
        bear_fvg = (high.shift(2) < low)
        
        # Calculate Gap Size
        df['fvg_bull_size'] = np.where(bull_fvg, low.shift(2) - high, 0.0)
        df['fvg_bear_size'] = np.where(bear_fvg, low - high.shift(2), 0.0)

        # Store FVG levels at detection point (top/bottom of imbalance)
        # Bullish FVG: gap between high[i] (bottom) and low[i-2] (top)
        df['fvg_bull_top'] = np.where(bull_fvg, low.shift(2), np.nan)
        df['fvg_bull_bottom'] = np.where(bull_fvg, high, np.nan)
        # Bearish FVG: gap between high[i-2] (bottom) and low[i] (top)
        df['fvg_bear_top'] = np.where(bear_fvg, low, np.nan)
        df['fvg_bear_bottom'] = np.where(bear_fvg, high.shift(2), np.nan)
        
        # Boolean flags
        df['is_fvg_bull'] = bull_fvg.astype(int)
        df['is_fvg_bear'] = bear_fvg.astype(int)

        # Active/latest FVG context (forward-fill last detected levels)
        df['active_fvg_bull_top'] = df['fvg_bull_top'].ffill()
        df['active_fvg_bull_bottom'] = df['fvg_bull_bottom'].ffill()
        df['active_fvg_bear_top'] = df['fvg_bear_top'].ffill()
        df['active_fvg_bear_bottom'] = df['fvg_bear_bottom'].ffill()

        # Age since last FVG detection (bars)
        idx_s = pd.Series(np.arange(len(df), dtype=float), index=df.index)
        last_bull_s = pd.Series(np.where(bull_fvg.values, idx_s.values, np.nan), index=df.index).ffill()
        last_bear_s = pd.Series(np.where(bear_fvg.values, idx_s.values, np.nan), index=df.index).ffill()

        df['fvg_bull_age'] = (idx_s - last_bull_s).where(last_bull_s.notna(), 0.0)
        df['fvg_bear_age'] = (idx_s - last_bear_s).where(last_bear_s.notna(), 0.0)

        # Touch/mitigation: price traded into the gap range
        close = df['close']
        high_ = df['high']
        low_ = df['low']

        bull_top = df['active_fvg_bull_top']
        bull_bot = df['active_fvg_bull_bottom']
        bear_top = df['active_fvg_bear_top']
        bear_bot = df['active_fvg_bear_bottom']

        bull_in_range = (low_ <= bull_top) & (high_ >= bull_bot)
        bear_in_range = (high_ >= bear_bot) & (low_ <= bear_top)

        # Do not count the detection candle as a "test" (the gap is formed on that candle by definition).
        bull_in_range = bull_in_range & (df['is_fvg_bull'] == 0)
        bear_in_range = bear_in_range & (df['is_fvg_bear'] == 0)

        df['fvg_bull_tests'] = bull_in_range.astype(int).groupby((df['fvg_bull_top'].notna()).cumsum()).cumsum().fillna(0)
        df['fvg_bear_tests'] = bear_in_range.astype(int).groupby((df['fvg_bear_top'].notna()).cumsum()).cumsum().fillna(0)

        df['fvg_bull_mitigated'] = (df['fvg_bull_tests'] > 0).astype(int)
        df['fvg_bear_mitigated'] = (df['fvg_bear_tests'] > 0).astype(int)

        # Proximity: distance from close to the active gap (0 if inside).
        # Important: if no active gap exists, keep NaN (do not treat as distance=0).
        bull_active = bull_top.notna() & bull_bot.notna() & np.isfinite(bull_top) & np.isfinite(bull_bot)
        bear_active = bear_top.notna() & bear_bot.notna() & np.isfinite(bear_top) & np.isfinite(bear_bot)

        bull_dist = np.where(
            bull_active,
            np.where(
                close < bull_bot,
                (bull_bot - close),
                np.where(close > bull_top, (close - bull_top), 0.0),
            ),
            np.nan,
        )
        bear_dist = np.where(
            bear_active,
            np.where(
                close > bear_top,
                (close - bear_top),
                np.where(close < bear_bot, (bear_bot - close), 0.0),
            ),
            np.nan,
        )
        df['fvg_bull_distance'] = bull_dist.astype(float)
        df['fvg_bear_distance'] = bear_dist.astype(float)
        
        return df

    def detect_order_blocks(self, df: pd.DataFrame, lookback: int = 50) -> pd.DataFrame:
        """
        Detects Order Blocks (OB).
        Simplified logic: 
        - Bullish OB: Bearish candle followed by strong bullish move that breaks structure (local high).
        - Bearish OB: Bullish candle followed by strong bearish move that breaks structure (local low).
        """
        close = df['close']
        open_ = df['open']
        high = df['high']
        low = df['low']
        
        # Identify candle color
        is_green = close > open_
        is_red = close < open_
        
        # Identify Swing Highs/Lows (Fractals)
        # A simple 5-candle fractal: High[i] is highest of i-2...i+2
        # Since we are causal, we can only know it was a high after 2 candles.
        # For OB detection, we look for a break of a *previous* swing high/low.
        
        # Rolling max/min for structure break detection
        roll_max = high.rolling(window=lookback).max().shift(1)
        roll_min = low.rolling(window=lookback).min().shift(1)
        
        # Break of Structure (BOS)
        bos_bull = (close > roll_max) & (close.shift(1) <= roll_max.shift(1))
        bos_bear = (close < roll_min) & (close.shift(1) >= roll_min.shift(1))
        
        # Initialize columns
        df['is_ob_bull'] = 0
        df['is_ob_bear'] = 0
        df['ob_top'] = np.nan
        df['ob_bottom'] = np.nan
        
        # Iterate to find the OB candle associated with the BOS
        # This is slow in pure python, but robust. Vectorizing "find the last opposite color candle" is tricky.
        # We will use a simplified vectorized approach:
        # If BOS Bull happens at index i, look back N candles for the last Red candle.
        
        # Vectorized approximation:
        # 1. Mark BOS events
        # 2. For each BOS, find the index of the last contrary candle within a window.
        
        # For now, let's stick to a simple heuristic for the "Eyes" visualization:
        # Mark the candle that *started* the move.
        
        # We will use a loop for precision as OB logic is path-dependent.
        # Optimization: Only loop when BOS is detected.
        
        ob_bull_indices = []
        ob_bear_indices = []
        
        # Convert to numpy for speed
        close_np = close.values
        open_np = open_.values
        high_np = high.values
        low_np = low.values
        bos_bull_np = bos_bull.values
        bos_bear_np = bos_bear.values
        
        n = len(df)
        
        # Arrays to store OB levels
        ob_bull_top = np.full(n, np.nan)
        ob_bull_bottom = np.full(n, np.nan)
        ob_bear_top = np.full(n, np.nan)
        ob_bear_bottom = np.full(n, np.nan)

        for i in range(lookback, n):
            # Bullish BOS: Price broke up. Look for last Red candle.
            if bos_bull_np[i]:
                for k in range(1, lookback):
                    idx = i - k
                    if idx < 0: break
                    # Check if candle is Red (Close < Open)
                    if close_np[idx] < open_np[idx]:
                        # Found the OB
                        ob_bull_indices.append(idx)
                        # Store the OB levels (High/Low of that candle)
                        # Usually OB is the body, but let's take High/Low for safety zone
                        ob_bull_top[i] = high_np[idx]
                        ob_bull_bottom[i] = low_np[idx]
                        break
            
            # Bearish BOS: Price broke down. Look for last Green candle.
            if bos_bear_np[i]:
                for k in range(1, lookback):
                    idx = i - k
                    if idx < 0: break
                    # Check if candle is Green (Close > Open)
                    if close_np[idx] > open_np[idx]:
                        # Found the OB
                        ob_bear_indices.append(idx)
                        ob_bear_top[i] = high_np[idx]
                        ob_bear_bottom[i] = low_np[idx]
                        break
        
        df['ob_bull_top'] = ob_bull_top
        df['ob_bull_bottom'] = ob_bull_bottom
        df['ob_bear_top'] = ob_bear_top
        df['ob_bear_bottom'] = ob_bear_bottom

        # Active/latest OB context (forward-fill last detected levels)
        df['active_ob_bull_top'] = df['ob_bull_top'].ffill()
        df['active_ob_bull_bottom'] = df['ob_bull_bottom'].ffill()
        df['active_ob_bear_top'] = df['ob_bear_top'].ffill()
        df['active_ob_bear_bottom'] = df['ob_bear_bottom'].ffill()

        # Age since last OB detection (bars)
        idx_s = pd.Series(np.arange(len(df), dtype=float), index=df.index)
        last_bull_s = pd.Series(
            np.where(np.isfinite(df['ob_bull_top'].values), idx_s.values, np.nan),
            index=df.index,
        ).ffill()
        last_bear_s = pd.Series(
            np.where(np.isfinite(df['ob_bear_top'].values), idx_s.values, np.nan),
            index=df.index,
        ).ffill()

        df['bull_ob_age'] = (idx_s - last_bull_s).where(last_bull_s.notna(), 0.0)
        df['bear_ob_age'] = (idx_s - last_bear_s).where(last_bear_s.notna(), 0.0)

        # Touch count (tests) and mitigation flags
        high_ = df['high']
        low_ = df['low']
        close_ = df['close']

        bull_top = df['active_ob_bull_top']
        bull_bot = df['active_ob_bull_bottom']
        bear_top = df['active_ob_bear_top']
        bear_bot = df['active_ob_bear_bottom']

        bull_in_zone = (low_ <= bull_top) & (high_ >= bull_bot)
        bear_in_zone = (high_ >= bear_bot) & (low_ <= bear_top)

        df['bull_ob_tests'] = bull_in_zone.astype(int).groupby((df['ob_bull_top'].notna()).cumsum()).cumsum().fillna(0)
        df['bear_ob_tests'] = bear_in_zone.astype(int).groupby((df['ob_bear_top'].notna()).cumsum()).cumsum().fillna(0)

        df['bull_ob_mitigated'] = (df['bull_ob_tests'] > 0).astype(int)
        df['bear_ob_mitigated'] = (df['bear_ob_tests'] > 0).astype(int)

        # Proximity: distance from close to active OB zone (0 if inside).
        # Important: if no active OB exists, keep NaN (do not treat as distance=0).
        bull_active = bull_top.notna() & bull_bot.notna() & np.isfinite(bull_top) & np.isfinite(bull_bot)
        bear_active = bear_top.notna() & bear_bot.notna() & np.isfinite(bear_top) & np.isfinite(bear_bot)

        bull_dist = np.where(
            bull_active,
            np.where(
                close_ < bull_bot,
                (bull_bot - close_),
                np.where(close_ > bull_top, (close_ - bull_top), 0.0),
            ),
            np.nan,
        )
        bear_dist = np.where(
            bear_active,
            np.where(
                close_ > bear_top,
                (close_ - bear_top),
                np.where(close_ < bear_bot, (bear_bot - close_), 0.0),
            ),
            np.nan,
        )
        df['bull_ob_distance'] = bull_dist.astype(float)
        df['bear_ob_distance'] = bear_dist.astype(float)
        
        # Fill forward OB levels to show them "active" until mitigated?
        # For now, just marking the detection point is enough for the Feature Vector.
        # The Transformer will learn "Time since last OB detected".
        
        return df

    def detect_liquidity_sweeps(self, df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
        """
        Detects Liquidity Sweeps (Turtle Soups).
        Sweep High: High > Prev Swing High AND Close < Prev Swing High
        Sweep Low: Low < Prev Swing Low AND Close > Prev Swing Low
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Previous Swing High/Low (excluding current candle)
        # We use a rolling max of the *previous* N candles.
        prev_highs = high.shift(1).rolling(window=lookback).max()
        prev_lows = low.shift(1).rolling(window=lookback).min()
        
        # Sweep Conditions
        sweep_high = (high > prev_highs) & (close < prev_highs)
        sweep_low = (low < prev_lows) & (close > prev_lows)
        
        df['is_sweep_high'] = sweep_high.astype(int)
        df['is_sweep_low'] = sweep_low.astype(int)
        
        return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        V2.0: Añade indicadores técnicos adicionales para mejorar el aprendizaje.
        - RSI (14)
        - ATR (14)
        - EMA distances (20, 50, 200)
        - Volume ratio
        - Momentum
        """
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi_normalized'] = (df['rsi'] - 50) / 50  # Normalizado [-1, 1]
        
        # ATR (14)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        df['atr_pct'] = df['atr'] / close  # ATR como % del precio
        
        # EMAs
        df['ema_20'] = close.ewm(span=20, adjust=False).mean()
        df['ema_50'] = close.ewm(span=50, adjust=False).mean()
        df['ema_200'] = close.ewm(span=200, adjust=False).mean()
        
        # Distancia a EMAs (normalizada)
        df['ema_20_dist'] = (close - df['ema_20']) / close
        df['ema_50_dist'] = (close - df['ema_50']) / close
        df['ema_200_dist'] = (close - df['ema_200']) / close
        
        # Volume ratio (vs media de 20 periodos)
        vol_ma = volume.rolling(window=20).mean()
        df['volume_ratio'] = volume / (vol_ma + 1e-10)
        df['volume_ratio'] = df['volume_ratio'].clip(0, 5)  # Cap at 5x
        
        # Momentum (cambio % en últimas 5 velas)
        df['momentum_5'] = close.pct_change(periods=5)
        df['momentum_10'] = close.pct_change(periods=10)
        
        # Trend strength (pendiente de EMA20)
        df['trend_strength'] = df['ema_20'].pct_change(periods=5) * 100
        
        return df
    
