import asyncio, pandas as pd, sys
sys.path.insert(0, '/srv/profitlab_quantum')
from app.data.bingx import BingXReader
from app.features.smc_features import SMCFeatureCalculator
from app.engine import match_playbook_rules

async def debug():
    bingx = BingXReader()
    df = await bingx.get_klines('BTC-USDT', interval='1h', limit=500)
    df = SMCFeatureCalculator.add_all(df)
    
    matches = 0
    for i in range(50, len(df)):
        row = df.iloc[i].to_dict()
        rsi = float(row.get('rsi', 50))
        vol = float(row.get('volume_ratio', 1.0))
        
        # Exact mock from engine.py
        playbook_features = {
            "rsi": rsi, "vol_ratio": vol, "bb_position": 0.5, "squeeze": 0.0,
            "adx": 30.0, "htf_trend": 1.0, "swing_low": 1.0, "swing_high": 0.0,
            "fvg_bull": 0.0, "fvg_bear": 0.0, "macd_cross_up": 0.0, "macd_cross_down": 0.0,
            "rsi_oversold": rsi, "rsi_deep_os": rsi, "vol_spike": vol, "vol_big_spike": vol,
            "bb_low": 0.2, "bb_high": 0.8, "squeeze_fire": 1.0, "htf_up": 1.0,
            "htf_down": -1.0, "adx_trending": 30.0, "ema_below": 0.0, "ema_above": 0.0,
            "hour_utc": 12.0, "liquidity": 1.0, "btc_momentum": 0.0, "funding_rate": 0.01,
        }
        
        pb_match = match_playbook_rules(playbook_features)
        if pb_match.get('action') == 1:
            print(f"MATCH FOUND! Index {i} | RSI={rsi:.1f} | VOL={vol:.1f} | Rule={pb_match.get('rule_id')}")
            matches += 1
            if matches >= 5: break
            
    if matches == 0:
        print("NO MATCHES FOUND IN ENTIRE DATASET! Let's check why...")
        print(f"Min RSI: {df['rsi'].min():.1f}")
        print(f"Max VOL: {df['volume_ratio'].max():.1f}")

asyncio.run(debug())
