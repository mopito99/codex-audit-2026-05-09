#!/usr/bin/env python3
"""
Patch engine.py to add V3 PRO 48-dim features.
Run on the GPU server.
"""
import re

ENGINE_PATH = '/srv/profitlab_quantum/app/engine.py'

with open(ENGINE_PATH, 'r') as f:
    content = f.read()

# ============================================================
# PATCH 1: Replace state_columns (34 → 48)
# ============================================================
old_state_columns = """        self.state_columns = [
            # OHLCV básicos (5)
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
            'is_golden_hour',
            'liquidity_score',
            # V2.0: Technical Indicators (10) - NUEVOS
            'rsi_normalized',    # RSI normalizado [-1, 1]
            'atr_pct',           # ATR como % del precio
            'ema_20_dist',       # Distancia a EMA20
            'ema_50_dist',       # Distancia a EMA50
            'ema_200_dist',      # Distancia a EMA200
            'volume_ratio',      # Volume vs media
            'momentum_5',        # Momentum 5 velas
            'momentum_10',       # Momentum 10 velas
            'trend_strength',    # Fuerza de la tendencia
        ]
        self.input_dim = len(self.state_columns)"""

new_state_columns = """        self.state_columns = [
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
            # V2: Technical Indicators (9)
            'rsi_normalized', 'atr_pct',
            'ema_20_dist', 'ema_50_dist', 'ema_200_dist',
            'volume_ratio', 'momentum_5', 'momentum_10', 'trend_strength',
            # V3 PRO: Institutional Indicators (14) - NEW
            'macd_signal_dist',    # MACD - Signal normalized
            'macd_histogram',      # MACD histogram
            'bb_position',         # Bollinger position [0,1]
            'bb_width',            # Bollinger width (volatility)
            'stoch_k',             # Stochastic %K [-1,1]
            'stoch_d',             # Stochastic %D [-1,1]
            'adx_normalized',      # ADX [0,1]
            'obv_slope',           # OBV momentum
            'vwap_dist',           # VWAP distance
            'price_change_1h',     # 1h return
            'price_change_4h',     # 4h return
            'high_low_ratio',      # Candle range / close
            'close_position',      # Close in H-L range [0,1]
            'volume_momentum',     # Volume change rate
        ]
        self.input_dim = len(self.state_columns)  # 48"""

assert old_state_columns in content, "Could not find old state_columns block"
content = content.replace(old_state_columns, new_state_columns)

# ============================================================
# PATCH 2: Add V3 indicator computation before state vector build
# ============================================================
# Insert after row['liquidity_score'] = ... and before state_values = []
old_state_build = """        row['liquidity_score'] = float(liquidity_score)
        state_values = []"""

new_state_build = """        row['liquidity_score'] = float(liquidity_score)

        # --- V3 PRO: Compute institutional indicators from market_data ---
        try:
            _close = market_data['close'].astype(float)
            _high = market_data['high'].astype(float)
            _low = market_data['low'].astype(float)
            _volume = market_data['volume'].astype(float)
            _n = len(_close)

            # MACD (12, 26, 9)
            _ema12 = _close.ewm(span=12).mean()
            _ema26 = _close.ewm(span=26).mean()
            _macd = _ema12 - _ema26
            _signal = _macd.ewm(span=9).mean()
            _px = float(_close.iloc[-1]) if _n > 0 else 1.0
            row['macd_signal_dist'] = float((_macd.iloc[-1] - _signal.iloc[-1]) / (_px + 1e-10)) if _n > 26 else 0.0
            row['macd_histogram'] = row['macd_signal_dist']

            # Bollinger Bands (20, 2)
            if _n >= 20:
                _bb_mid = _close.rolling(20).mean()
                _bb_std = _close.rolling(20).std()
                _bb_upper = _bb_mid + 2 * _bb_std
                _bb_lower = _bb_mid - 2 * _bb_std
                _bb_range = float(_bb_upper.iloc[-1] - _bb_lower.iloc[-1])
                row['bb_position'] = float((_px - _bb_lower.iloc[-1]) / (_bb_range + 1e-10))
                row['bb_width'] = float(_bb_range / (_bb_mid.iloc[-1] + 1e-10))
            else:
                row['bb_position'] = 0.5
                row['bb_width'] = 0.0

            # Stochastic (14, 3)
            if _n >= 14:
                _low14 = _low.rolling(14).min()
                _high14 = _high.rolling(14).max()
                _stoch_k = (_close - _low14) / (_high14 - _low14 + 1e-10)
                _stoch_d = _stoch_k.rolling(3).mean()
                row['stoch_k'] = float((_stoch_k.iloc[-1] - 0.5) * 2)
                row['stoch_d'] = float((_stoch_d.iloc[-1] - 0.5) * 2) if _n >= 16 else 0.0
            else:
                row['stoch_k'] = 0.0
                row['stoch_d'] = 0.0

            # ADX (14)
            if _n >= 28:
                _plus_dm = _high.diff().clip(lower=0)
                _minus_dm = (-_low.diff()).clip(lower=0)
                _tr = pd.concat([_high - _low, (_high - _close.shift(1)).abs(), (_low - _close.shift(1)).abs()], axis=1).max(axis=1)
                _atr14 = _tr.rolling(14).mean()
                _plus_di = (_plus_dm.rolling(14).mean() / (_atr14 + 1e-10)) * 100
                _minus_di = (_minus_dm.rolling(14).mean() / (_atr14 + 1e-10)) * 100
                _dx = (_plus_di - _minus_di).abs() / (_plus_di + _minus_di + 1e-10) * 100
                _adx = _dx.rolling(14).mean()
                row['adx_normalized'] = float(_adx.iloc[-1] / 100.0)
            else:
                row['adx_normalized'] = 0.0

            # OBV slope
            if _n >= 20:
                _obv = (np.sign(_close.diff()) * _volume).fillna(0).cumsum()
                _obv_ma = _obv.rolling(20).mean()
                row['obv_slope'] = float((_obv.iloc[-1] - _obv_ma.iloc[-1]) / (abs(_obv_ma.iloc[-1]) + 1e-10))
            else:
                row['obv_slope'] = 0.0

            # VWAP distance (rolling 288 = ~1 day)
            if _n >= 50:
                _tp = (_high + _low + _close) / 3
                _window = min(288, _n)
                _cum_vol = _volume.rolling(_window).sum()
                _cum_tpv = (_tp * _volume).rolling(_window).sum()
                _vwap = _cum_tpv / (_cum_vol + 1e-10)
                row['vwap_dist'] = float((_px - _vwap.iloc[-1]) / (_px + 1e-10))
            else:
                row['vwap_dist'] = 0.0

            # Multi-TF price changes
            row['price_change_1h'] = float(_close.pct_change(12).iloc[-1]) if _n > 12 else 0.0
            row['price_change_4h'] = float(_close.pct_change(48).iloc[-1]) if _n > 48 else 0.0

            # Volatility & structure
            row['high_low_ratio'] = float((_high.iloc[-1] - _low.iloc[-1]) / (_px + 1e-10))
            row['close_position'] = float((_px - _low.iloc[-1]) / (_high.iloc[-1] - _low.iloc[-1] + 1e-10))

            # Volume momentum
            row['volume_momentum'] = float(_volume.pct_change(5).iloc[-1]) if _n > 5 else 0.0

        except Exception:
            for _col in ['macd_signal_dist', 'macd_histogram', 'bb_position', 'bb_width',
                         'stoch_k', 'stoch_d', 'adx_normalized', 'obv_slope', 'vwap_dist',
                         'price_change_1h', 'price_change_4h', 'high_low_ratio',
                         'close_position', 'volume_momentum']:
                row[_col] = row.get(_col, 0.0)

        state_values = []"""

assert old_state_build in content, "Could not find old state_build block"
content = content.replace(old_state_build, new_state_build)

with open(ENGINE_PATH, 'w') as f:
    f.write(content)

print(f"PATCHED engine.py successfully")
print(f"  state_columns: 34 → 48")
print(f"  V3 PRO indicators added to step()")
