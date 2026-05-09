"""Canonical PPO state vector schema — single source of truth.

Every script that builds or consumes state vectors (engine, offline training,
backtesting, portfolio manager) MUST import from here so dimensions never
drift out of sync.

Usage:
    from app.state_schema import STATE_COLUMNS, INPUT_DIM
"""

STATE_COLUMNS: list[str] = [
    # ── OHLCV (5) ───────────────────────────────────────────
    'open', 'high', 'low', 'close', 'volume',
    # ── SMC Features (8) ────────────────────────────────────
    'fvg_bull_size', 'fvg_bear_size', 'is_fvg_bull', 'is_fvg_bear',
    'is_sweep_high', 'is_sweep_low',
    'bull_ob_distance', 'bear_ob_distance',
    # ── OB Metadata (6) ────────────────────────────────────
    'bull_ob_age', 'bear_ob_age',
    'bull_ob_tests', 'bear_ob_tests',
    'bull_ob_mitigated', 'bear_ob_mitigated',
    # ── HTF Context (2) ────────────────────────────────────
    'htf_bias', 'htf_trend',
    # ── Golden Hour (4) ────────────────────────────────────
    'hour_sin', 'hour_cos',
    'is_golden_hour', 'liquidity_score',
    # ── V2: Technical Indicators (9) ───────────────────────
    'rsi_normalized', 'atr_pct',
    'ema_20_dist', 'ema_50_dist', 'ema_200_dist',
    'volume_ratio', 'momentum_5', 'momentum_10', 'trend_strength',
    # ── V3 PRO: Institutional Indicators (14) ──────────────
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
    # ── V4: Additional PPO Learning Indicators (8) ─────────
    'rsi_14',              # RSI(14) normalized [-1,1]
    'williams_r',          # Williams %R(14) normalized [-1,1]
    'cci_normalized',      # CCI(20) / 200 clamped [-1,1]
    'mfi_normalized',      # MFI(14) normalized [-1,1]
    'atr_pct_14',          # ATR(14) as % of price
    'keltner_position',    # Position in Keltner Channel [0,1]
    'squeeze_on',          # BB inside KC = squeeze (0 or 1)
    'ema_9_dist',          # Price dist from EMA(9) as % of price
]

INPUT_DIM: int = len(STATE_COLUMNS)  # 56

# Sub-groups for fallback filling (engine uses these when exceptions occur)
V3_INDICATOR_COLS: list[str] = STATE_COLUMNS[34:48]   # 14 V3 PRO columns
V4_INDICATOR_COLS: list[str] = STATE_COLUMNS[48:56]   # 8 V4 columns
