import asyncio
import pandas as pd
from datetime import timezone
import os, sys

sys.path.insert(0, '/srv/profitlab_quantum')

from app.data.bingx import BingXReader
from app.features.smc_features import SMCFeatureCalculator

async def run_backtest():
    print("--- CORRIGIENDO EL BUG: BACKTEST VERDADERO GEMMA 4 (500h) ---")
    tokens = ['BTC-USDT', 'ETH-USDT', 'XRP-USDT']
    bingx = BingXReader()
    
    total_pnl = 0.0
    
    for token in tokens:
        df = await bingx.get_klines(token, interval='1h', limit=500)
        if df is None or df.empty:
            continue
            
        calc = SMCFeatureCalculator()
        df = calc.calculate_all(df)
            
        trades = 0
        wins = 0
        pnl = 0.0
        in_position = False
        entry_price = 0.0
        
        from app.engine import match_playbook_rules
        
        for i in range(50, len(df)):
            row = df.iloc[i].to_dict()
            current_price = float(row.get('close', 0))
            
            # Map correctly from calculate_all output
            rsi_val = float(row.get('rsi', 50))
            vol_val = float(row.get('volume_ratio', 1.0) or 1.0)
            ema_9 = float(row.get('ema_9_dist', 0.0))
            bb_pos = float(row.get('keltner_position', 0.5))
            adx_val = float(row.get('adx', 0) or 0)
            sq_val = float(row.get('squeeze_on', 0) or 0)
            
            playbook_features = {
                "rsi": rsi_val,
                "ema_dist": ema_9,
                "vol_ratio": vol_val,
                "bb_position": bb_pos,
                "squeeze": sq_val,
                "adx": adx_val * 50 if adx_val < 2 else adx_val, # Handle normalization 
                "htf_trend": 1.0,
                "swing_low": 1.0 if float(row.get("is_sweep_low", 0) or 0) > 0 else 0.0,
                "swing_high": 1.0 if float(row.get("is_sweep_high", 0) or 0) > 0 else 0.0,
                "fvg_bull": 1.0 if float(row.get("fvg_bull_distance", 999) or 999) < 0.01 else 0.0,
                "fvg_bear": 1.0 if float(row.get("fvg_bear_distance", 999) or 999) < 0.01 else 0.0,
                "macd_cross_up": 1.0 if float(row.get("macd_line", 0) or 0) > 0 else 0.0,
                "macd_cross_down": 1.0 if float(row.get("macd_line", 0) or 0) < 0 else 0.0,
                "rsi_oversold": rsi_val,
                "rsi_deep_os": rsi_val,
                "vol_spike": vol_val,
                "vol_big_spike": vol_val,
                "bb_low": bb_pos,
                "bb_high": bb_pos,
                "squeeze_fire": sq_val,
                "htf_up": 1.0,
                "htf_down": -1.0,
                "adx_trending": adx_val,
                "ema_below": ema_9,
                "ema_above": ema_9,
                "hour_utc": 12.0,
                "liquidity": 1.0,
                "btc_momentum": 0.0,
                "funding_rate": 0.01,
            }
            
            pb_match = match_playbook_rules(playbook_features)
            
            if in_position:
                if current_price >= entry_price * 1.02: # TP
                    pnl += (current_price - entry_price) / entry_price * 1000.0
                    wins += 1
                    in_position = False
                elif current_price <= entry_price * 0.985: # SL
                    pnl += (current_price - entry_price) / entry_price * 1000.0
                    in_position = False
            else:
                if pb_match:
                    if pb_match.get('action') == 1:
                        in_position = True
                        entry_price = current_price
                        trades += 1
            
        print(f"-> RESULTADOS {token}: Trades={trades} | Wins={wins} | PnL=")
        total_pnl += pnl
        
    print("\n======================================")
    print(f"TOTAL BACKTEST GEMMA4 (500 vel x 1H): ")

if __name__ == '__main__':
    asyncio.run(run_backtest())
