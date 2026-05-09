import pandas as pd
import numpy as np
import talib
import os
import zipfile
import urllib.request

def download_binance_vision(symbol="HBARUSDT", interval="5m", start_year=2021, end_year=2024):
    print(f"⏳ Iniciando descarga directa de {symbol} desde Binance Vision...")
    base_url = "https://data.binance.vision/data/spot/monthly/klines"
    all_dfs = []

    os.makedirs("/tmp/kline_data_hbar", exist_ok=True)

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            file_name = f"{symbol}-{interval}-{year}-{month:02d}.zip"
            url       = f"{base_url}/{symbol}/{interval}/{file_name}"
            zip_path  = f"/tmp/kline_data_hbar/{file_name}"

            try:
                urllib.request.urlretrieve(url, zip_path)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    csv_name = zip_ref.namelist()[0]
                    zip_ref.extract(csv_name, "/tmp/kline_data_hbar/")

                df = pd.read_csv(f"/tmp/kline_data_hbar/{csv_name}", header=None)
                all_dfs.append(df)
                print(f"  ✅ {year}-{month:02d}")

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                else:
                    print(f"  ⚠️ Error HTTP {e.code} en {year}-{month:02d}")
            except Exception:
                pass

    if not all_dfs:
        return pd.DataFrame()

    print("🔄 Consolidando histórico de Hedera...")
    full_df = pd.concat(all_dfs, ignore_index=True)
    full_df = full_df.iloc[:, 0:6]
    full_df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    full_df['timestamp'] = pd.to_datetime(full_df['timestamp'], unit='ms')
    full_df.set_index('timestamp', inplace=True)
    full_df.sort_index(inplace=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        full_df[col] = pd.to_numeric(full_df[col], errors='coerce')
    full_df.dropna(inplace=True)
    return full_df


def engineer_features(df):
    if df.empty:
        print("Dataset vacío, cancelando.")
        return df
    print("🧠 Calculando features técnicos idénticos al V4.2 Tensor Shape...")

    close  = df['close'].values.astype(float)
    high   = df['high'].values.astype(float)
    low    = df['low'].values.astype(float)

    # RSI
    df['RSI_14'] = talib.RSI(close, timeperiod=14)

    # MACD
    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['MACD']        = macd
    df['MACD_signal'] = macd_signal
    df['MACD_hist']   = macd_hist

    # ATR
    df['ATR_14'] = talib.ATR(high, low, close, timeperiod=14)

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['BB_upper'] = bb_upper
    df['BB_mid']   = bb_mid
    df['BB_lower'] = bb_lower
    df['BB_width'] = (bb_upper - bb_lower) / bb_mid

    # SMAs y distancias
    for ma in [10, 20, 50, 200]:
        sma = talib.SMA(close, timeperiod=ma)
        df[f'SMA_{ma}']      = sma
        df[f'dist_SMA_{ma}'] = (df['close'] - sma) / sma

    # Volumen relativo
    df['Vol_SMA_20'] = df['volume'].rolling(20).mean()
    df['Vol_Ratio']  = df['volume'] / df['Vol_SMA_20']

    # Log Return
    df['Log_Return'] = np.log(df['close'] / df['close'].shift(1))

    df.dropna(inplace=True)
    print(f"✅ Features Hedera listos — {df.shape[0]:,} velas × {df.shape[1]} columnas")
    return df


if __name__ == '__main__':
    df = download_binance_vision(start_year=2021, end_year=2024)
    df = engineer_features(df)

    # Ensure output directory exists or save straight
    path = '/srv/quantum_ppo/data/hbar_usdt_5m.parquet'
    if not df.empty:
        df.to_parquet(path)
        print(f"💾 Parquet de Hedera guardado → {path}  ({len(df):,} velas)")
