"""
Backtester con filtros mejorados
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict
import sys
sys.path.insert(0, "/srv/profitlab_quantum")

@dataclass
class Config:
    name: str
    sl_buffer_pct: float
    rr_ratio: float
    volume_filter: bool
    session_filter: bool
    confirmation_bars: int  # Esperar N barras después de señal

CONFIGS = [
    Config("SIN_FILTROS", 0.005, 2.0, False, False, 0),
    Config("VOLUMEN", 0.005, 2.0, True, False, 0),
    Config("SESION", 0.005, 2.0, False, True, 0),
    Config("CONFIRMACION", 0.005, 2.0, False, False, 1),
    Config("TODOS_FILTROS", 0.005, 2.0, True, True, 1),
    Config("TODOS+RR3", 0.005, 3.0, True, True, 1),
]

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores para señales"""
    df = df.copy()
    
    # EMAs para trend
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["trend"] = np.where(df["ema20"] > df["ema50"], 1, -1)
    
    # ATR
    high, low, close = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, abs(high - close), abs(low - close)], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    
    # Volumen relativo
    df["vol_sma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_sma"]
    
    # Estructura de mercado simple (swing highs/lows)
    df["swing_high"] = df["high"].rolling(5, center=True).max() == df["high"]
    df["swing_low"] = df["low"].rolling(5, center=True).min() == df["low"]
    
    # BOS (Break of Structure) - precio rompe swing anterior
    df["prev_swing_high"] = df.loc[df["swing_high"], "high"].reindex(df.index, method="ffill")
    df["prev_swing_low"] = df.loc[df["swing_low"], "low"].reindex(df.index, method="ffill")
    
    df["bos_bull"] = (df["close"] > df["prev_swing_high"].shift(1)) & (df["trend"] == 1)
    df["bos_bear"] = (df["close"] < df["prev_swing_low"].shift(1)) & (df["trend"] == -1)
    
    # Hora del día (para filtro de sesión)
    df["hour"] = df["timestamp"].dt.hour
    
    return df

def is_good_session(hour: int) -> bool:
    """Sesiones de alta liquidez (UTC)"""
    # London: 7-16, NY: 13-22, evitar Asia baja: 22-7
    return 7 <= hour <= 22

def generate_signals(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Genera señales con filtros"""
    df = calculate_indicators(df)
    df["signal"] = 0
    df["signal_strength"] = 0
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        
        # Filtro de sesión
        if config.session_filter and not is_good_session(row["hour"]):
            continue
        
        # Filtro de volumen
        if config.volume_filter and row["vol_ratio"] < 1.0:
            continue
        
        # Señal LONG: BOS bullish + trend up
        if row["bos_bull"] and row["trend"] == 1:
            df.iloc[i, df.columns.get_loc("signal")] = 1
            df.iloc[i, df.columns.get_loc("signal_strength")] = row["vol_ratio"]
        
        # Señal SHORT: BOS bearish + trend down  
        elif row["bos_bear"] and row["trend"] == -1:
            df.iloc[i, df.columns.get_loc("signal")] = -1
            df.iloc[i, df.columns.get_loc("signal_strength")] = row["vol_ratio"]
    
    return df

def backtest(df: pd.DataFrame, config: Config, capital: float = 5000) -> Dict:
    """Ejecuta backtest"""
    df = generate_signals(df.copy(), config)
    
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    entry_idx = 0
    pending_signal = 0
    pending_countdown = 0
    
    trades = []
    current_capital = capital
    margin_pct = 0.10  # 10% del capital por trade
    leverage = 5.0
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        price = row["close"]
        high = row["high"]
        low = row["low"]
        
        # Check SL/TP
        if position != 0:
            hit_sl = hit_tp = False
            
            if position == 1:
                if low <= sl_price:
                    hit_sl, exit_price = True, sl_price
                elif high >= tp_price:
                    hit_tp, exit_price = True, tp_price
            else:
                if high >= sl_price:
                    hit_sl, exit_price = True, sl_price
                elif low <= tp_price:
                    hit_tp, exit_price = True, tp_price
            
            if hit_sl or hit_tp:
                if position == 1:
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price
                
                pnl_pct -= 0.001  # Fees + slippage
                margin = current_capital * margin_pct
                pnl_usd = margin * leverage * pnl_pct
                current_capital += pnl_usd
                
                trades.append({
                    "side": "LONG" if position == 1 else "SHORT",
                    "pnl_usd": pnl_usd,
                    "result": "TP" if hit_tp else "SL",
                    "bars_held": i - entry_idx,
                })
                position = 0
        
        # Confirmación: esperar N barras
        if pending_signal != 0:
            pending_countdown -= 1
            if pending_countdown <= 0:
                # Entrar ahora
                position = pending_signal
                entry_price = price
                entry_idx = i
                
                atr = row["atr"] if pd.notna(row["atr"]) else price * 0.02
                sl_dist = max(price * config.sl_buffer_pct, atr * 0.5)
                tp_dist = sl_dist * config.rr_ratio
                
                if position == 1:
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + tp_dist
                else:
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - tp_dist
                
                pending_signal = 0
        
        # Nueva señal
        if position == 0 and pending_signal == 0 and current_capital > 1000:
            signal = row["signal"]
            if signal != 0:
                if config.confirmation_bars > 0:
                    pending_signal = signal
                    pending_countdown = config.confirmation_bars
                else:
                    position = signal
                    entry_price = price
                    entry_idx = i
                    
                    atr = row["atr"] if pd.notna(row["atr"]) else price * 0.02
                    sl_dist = max(price * config.sl_buffer_pct, atr * 0.5)
                    tp_dist = sl_dist * config.rr_ratio
                    
                    if position == 1:
                        sl_price = entry_price - sl_dist
                        tp_price = entry_price + tp_dist
                    else:
                        sl_price = entry_price + sl_dist
                        tp_price = entry_price - tp_dist
    
    if not trades:
        return {"config": config.name, "trades": 0, "win_rate": 0, "total_pnl": 0}
    
    wins = sum(1 for t in trades if t["pnl_usd"] > 0)
    total_pnl = sum(t["pnl_usd"] for t in trades)
    
    return {
        "config": config.name,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": wins / len(trades) * 100,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(trades),
        "final_equity": current_capital,
    }

def main():
    print("=" * 80)
    print("BACKTESTING CON FILTROS MEJORADOS")
    print("=" * 80)
    
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    all_results = {c.name: [] for c in CONFIGS}
    
    for symbol in symbols:
        filepath = f"/srv/profitlab_quantum/data/historical/{symbol}_5m_6m.parquet"
        try:
            df = pd.read_parquet(filepath)
            print(f"\n📊 {symbol}: {len(df)} velas")
        except Exception as e:
            print(f"❌ {symbol}: {e}")
            continue
        
        for config in CONFIGS:
            result = backtest(df, config)
            result["symbol"] = symbol
            all_results[config.name].append(result)
            print(f"   {config.name}: {result['trades']} trades, WR {result['win_rate']:.1f}%, PnL ${result['total_pnl']:+.2f}")
    
    # Resumen
    print("\n" + "=" * 80)
    print("RESUMEN AGREGADO")
    print("=" * 80)
    print(f"{'Config':<20} {'Trades':>8} {'Win%':>8} {'PnL':>12} {'Avg':>10}")
    print("-" * 60)
    
    best_config = None
    best_pnl = -999999
    
    for config_name, results in all_results.items():
        total_trades = sum(r["trades"] for r in results)
        total_pnl = sum(r["total_pnl"] for r in results)
        avg_wr = np.mean([r["win_rate"] for r in results if r["trades"] > 0]) if any(r["trades"] > 0 for r in results) else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        
        print(f"{config_name:<20} {total_trades:>8} {avg_wr:>7.1f}% ${total_pnl:>+10.2f} ${avg_pnl:>+8.2f}")
        
        if total_pnl > best_pnl and total_trades > 10:
            best_pnl = total_pnl
            best_config = config_name
    
    print("-" * 60)
    if best_config:
        print(f"\n🏆 MEJOR CONFIGURACIÓN: {best_config} (PnL: ${best_pnl:+.2f})")
    else:
        print("\n⚠️ Ninguna configuración fue rentable")

if __name__ == "__main__":
    main()
