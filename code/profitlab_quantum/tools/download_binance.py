import requests
import pandas as pd
import time
from pathlib import Path
from datetime import datetime, timedelta

# Config
# Top ~30 liquid tokens (excluding stables)
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", 
    "TRXUSDT", "AVAXUSDT", "SHIBUSDT", "DOTUSDT", "LINKUSDT", "BCHUSDT", "NEARUSDT", 
    "MATICUSDT", "LTCUSDT", "UNIUSDT", "ICPUSDT", "APTUSDT", "ETCUSDT", "FILUSDT", 
    "HBARUSDT", "ARBUSDT", "VETUSDT", "OPUSDT", "RNDRUSDT", "INJUSDT", "GRTUSDT", 
    "STXUSDT", "XLMUSDT"
]
INTERVAL = "5m"
DAYS = 180
DATA_DIR = Path("/srv/profitlab_quantum/data/historical")
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.binance.com/api/v3/klines"

def download_symbol(symbol):
    print(f"Downloading {symbol}...")
    all_klines = []
    end_ts = int(time.time() * 1000)
    start_ts = int((datetime.now() - timedelta(days=DAYS)).timestamp() * 1000)
    
    current_start = start_ts
    
    while True:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": current_start,
            "limit": 1000
        }
        
        try:
            resp = requests.get(BASE_URL, params=params, timeout=10)
            data = resp.json()
            
            if not isinstance(data, list) or len(data) == 0:
                break
                
            all_klines.extend(data)
            
            last_close_time = data[-1][6]
            current_start = last_close_time + 1
            
            if current_start > end_ts:
                break
                
            # Progress
            dt_current = datetime.fromtimestamp(current_start / 1000)
            print(f"  Fetched up to {dt_current} ({len(all_klines)} candles)")
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            
    # Convert to DataFrame
    if not all_klines:
        print(f"No data for {symbol}")
        return

    df = pd.DataFrame(all_klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades", 
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    
    # Clean types
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
        
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    
    # Save
    filename = DATA_DIR / f"{symbol.replace('USDT', '_USDT')}_{INTERVAL}_6m.parquet"
    df.to_parquet(filename)
    print(f"Saved {len(df)} rows to {filename}")

def main():
    for s in SYMBOLS:
        download_symbol(s)

if __name__ == "__main__":
    main()
