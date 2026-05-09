"""
Descarga datos históricos de BingX para backtesting
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import json

# Load active tokens from config
try:
    with open(os.path.join(os.path.dirname(__file__), "../active_tokens.json"), "r") as f:
        config = json.load(f)
        # Combine active and candidates
        active = config.get("active_tokens", [])
        candidates = config.get("candidates", [])
        
        symbols_set = set()
        
        # Process active
        if active and isinstance(active[0], dict):
            for t in active: symbols_set.add(t["symbol"])
        else:
            for t in active: symbols_set.add(t)
            
        # Process candidates
        for t in candidates: symbols_set.add(t)
            
        SYMBOLS = list(symbols_set)
        
except Exception as e:
    print(f"Warning: Could not load active_tokens.json ({e}), using defaults.")
    SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "BNB-USDT"]

INTERVAL = "5m"
DAYS_BACK = 90  # 3 meses

def download_klines(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Descarga velas de BingX"""
    base_url = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
    
    all_data = []
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    
    print(f"  Descargando {symbol}...")
    
    current_end = end_time
    while current_end > start_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 1000,
            "endTime": current_end
        }
        
        try:
            resp = requests.get(base_url, params=params, timeout=10)
            data = resp.json()
            
            if "data" not in data or not data["data"]:
                break
                
            klines = data["data"]
            all_data.extend(klines)
            
            # Mover al batch anterior
            oldest_time = min(int(k["time"]) for k in klines)
            current_end = oldest_time - 1
            
            time.sleep(0.2)  # Rate limit
            
        except Exception as e:
            print(f"    Error: {e}")
            break
    
    if not all_data:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_data)
    df["time"] = pd.to_datetime(df["time"].astype(int), unit="ms")
    df = df.rename(columns={
        "time": "timestamp",
        "open": "open",
        "high": "high", 
        "low": "low",
        "close": "close",
        "volume": "volume"
    })
    
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    
    df = df.sort_values("timestamp").drop_duplicates("timestamp")
    
    return df[["timestamp", "open", "high", "low", "close", "volume"]]

def main():
    os.makedirs("/srv/profitlab_quantum/data/historical", exist_ok=True)
    
    print(f"Descargando {DAYS_BACK} días de datos históricos...")
    print("=" * 50)
    
    for symbol in SYMBOLS:
        df = download_klines(symbol, INTERVAL, DAYS_BACK)
        
        if df.empty:
            print(f"  ❌ {symbol}: Sin datos")
            continue
            
        filepath = f"/srv/profitlab_quantum/data/historical/{symbol.replace('-', '_')}_{INTERVAL}.parquet"
        df.to_parquet(filepath, index=False)
        
        print(f"  ✅ {symbol}: {len(df)} velas ({df['timestamp'].min()} → {df['timestamp'].max()})")
    
    print("=" * 50)
    print("Descarga completada.")

if __name__ == "__main__":
    main()
