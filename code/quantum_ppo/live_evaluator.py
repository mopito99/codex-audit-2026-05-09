import numpy as np
import pandas as pd
import pandas_ta as ta
import ccxt
from stable_baselines3 import PPO

# Variables
SYMBOL     = 'SOL/USDT'
TIMEFRAME  = '5m'
MODEL_PATH = '/srv/quantum_ppo/models/agent_ppo_vfinal.zip'
WINDOW_SIZE = 20

# ── [FIX 3] Usar BingX como fuente de datos de mercado en producción ──────────
# BingX NO bloquea IPs de USA. Binance daba error 451 (restricción geográfica).
def get_live_data():
    """Descarga las últimas 300 velas de 5m desde BingX."""
    exchange = ccxt.bingx({
        'enableRateLimit': True,
    })
    print(f"📡 Consultando pulso en vivo {SYMBOL} ({TIMEFRAME}) en BingX...")
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)

    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def shape_state(df):
    """Aplica exactamente los mismos Features que se usaron en el entrenamiento."""
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.atr(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)

    for ma in [10, 20, 50, 200]:
        df.ta.sma(length=ma, append=True)
        df[f'dist_SMA_{ma}'] = (df['close'] - df[f'SMA_{ma}']) / df[f'SMA_{ma}']

    df['Vol_SMA_20'] = df['volume'].rolling(20).mean()
    df['Vol_Ratio'] = df['volume'] / df['Vol_SMA_20']
    df['Log_Return'] = np.log(df['close'] / df['close'].shift(1))

    try:
        df['BB_Width'] = (df['BBU_20_2.0'] - df['BBL_20_2.0']) / df['BBM_20_2.0']
    except Exception:
        df['BB_Width'] = 0.0

    df.dropna(inplace=True)
    return df

def ask_the_oracle():
    print("🤖 Despertando al Agente PPO (v2 corregido)...")
    try:
        model = PPO.load(MODEL_PATH)
    except Exception as e:
        print(f"❌ Modelo no encontrado aún: {e}")
        return

    df      = get_live_data()
    obs_df  = shape_state(df)

    # Excluir columnas OHLCV bruto — solo features matemáticos
    features = obs_df.drop(
        columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore'
    ).values

    if len(features) < WINDOW_SIZE:
        print("⚠️ No hay suficientes datos para el estado de observación.")
        return

    current_obs = features[-WINDOW_SIZE:].astype(np.float32)
    action, _   = model.predict(current_obs, deterministic=True)
    price       = obs_df['close'].iloc[-1]

    labels = {
        0: "⏸️  [CERRAR / HOLD]  — Nada claro o orden de salida.",
        1: "🟢 [COMPRA LONG]     — Subida prevista. Entrar Long en BingX.",
        2: "🔴 [SELL SHORT]      — Caída prevista. Entrar Short en BingX."
    }

    print("\n" + "=" * 55)
    print(f"  📊 {SYMBOL} Precio actual: ${price:,.4f}")
    print(f"  🧠 DECISIÓN AI (A100 PPO v2):\n  ➜  {labels[int(action)]}")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    ask_the_oracle()
