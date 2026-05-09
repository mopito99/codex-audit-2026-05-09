"""
Backtester: Simula trades con diferentes configuraciones de parámetros
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple
import sys
sys.path.insert(0, "/srv/profitlab_quantum")
from app.features.smc_features import SMCFeatureCalculator as SMCFeatures

@dataclass
class Config:
    name: str
    floor_pct: float
    cppi_mult: float
    max_leverage: float
    risk_target: float
    sl_buffer_pct: float
    slippage_bps: float
    fvg_threshold: float
    ob_lookback: int
    confluence_min: int

# Configuraciones a probar
CONFIGS = [
    Config("VIEJO", 0.97, 3.5, 20.0, 0.185, 0.001, 2.5, 0.5, 20, 2),
    Config("NUEVO", 0.90, 2.5, 10.0, 0.12, 0.005, 7.5, 0.75, 50, 3),
    Config("CONSERVADOR", 0.85, 2.0, 5.0, 0.08, 0.008, 10.0, 1.0, 50, 3),
    Config("AGRESIVO", 0.80, 3.0, 10.0, 0.15, 0.003, 5.0, 0.5, 30, 2),
]

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = pd.concat([high - low, abs(high - close), abs(low - close)], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def generate_signals(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Genera señales SMC simplificadas para backtesting"""
    smc = SMCFeatures()
    
    # Calcular features SMC
    df = smc.detect_fair_value_gaps(df.copy(), threshold_atr_mult=config.fvg_threshold)
    df = smc.detect_order_blocks(df.copy(), lookback=config.ob_lookback)
    df["atr"] = calculate_atr(df)
    
    # Señal simple: FVG + OB + trend
    df["ema_fast"] = df["close"].ewm(span=20).mean()
    df["ema_slow"] = df["close"].ewm(span=50).mean()
    df["trend"] = np.where(df["ema_fast"] > df["ema_slow"], 1, -1)
    
    # Señales
    df["signal"] = 0
    
    # LONG: trend up + near bullish OB or FVG
    long_cond = (
        (df["trend"] == 1) & 
        ((df["is_fvg_bull"] == 1) | (df["is_ob_bull"] == 1))
    )
    
    # SHORT: trend down + near bearish OB or FVG  
    short_cond = (
        (df["trend"] == -1) & 
        ((df["is_fvg_bear"] == 1) | (df["is_ob_bear"] == 1))
    )
    
    df.loc[long_cond, "signal"] = 1
    df.loc[short_cond, "signal"] = -1
    
    return df

def backtest(df: pd.DataFrame, config: Config, capital: float = 5000) -> Dict:
    """Ejecuta backtest con una configuración"""
    df = generate_signals(df.copy(), config)
    
    # Estado
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0
    entry_idx = 0
    sl_price = 0
    tp_price = 0
    
    trades = []
    equity = [capital]
    current_capital = capital
    
    floor = capital * config.floor_pct
    
    for i in range(50, len(df)):  # Skip warmup
        row = df.iloc[i]
        price = row["close"]
        high = row["high"]
        low = row["low"]
        
        # Check SL/TP if in position
        if position != 0:
            hit_sl = False
            hit_tp = False
            
            if position == 1:  # LONG
                if low <= sl_price:
                    hit_sl = True
                    exit_price = sl_price
                elif high >= tp_price:
                    hit_tp = True
                    exit_price = tp_price
            else:  # SHORT
                if high >= sl_price:
                    hit_sl = True
                    exit_price = sl_price
                elif low <= tp_price:
                    hit_tp = True
                    exit_price = tp_price
            
            if hit_sl or hit_tp:
                # Calculate PnL
                if position == 1:
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price
                
                # Apply slippage
                pnl_pct -= config.slippage_bps / 10000
                
                # Calculate actual PnL
                cushion = max(0, current_capital - floor)
                margin = min(config.cppi_mult * cushion, current_capital * 0.5)
                leverage = min(config.max_leverage, 5.0)  # Cap for safety
                pnl_usd = margin * leverage * pnl_pct
                
                current_capital += pnl_usd
                
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "side": "LONG" if position == 1 else "SHORT",
                    "entry": entry_price,
                    "exit": exit_price,
                    "sl": sl_price,
                    "tp": tp_price,
                    "pnl_pct": pnl_pct,
                    "pnl_usd": pnl_usd,
                    "result": "TP" if hit_tp else "SL",
                    "margin": margin,
                    "leverage": leverage,
                })
                
                position = 0
        
        # Check for new signal if flat
        if position == 0 and current_capital > floor:
            signal = row["signal"]
            atr = row["atr"] if pd.notna(row["atr"]) else price * 0.02
            
            if signal != 0:
                position = signal
                entry_price = price
                entry_idx = i
                
                sl_dist = max(price * config.sl_buffer_pct, atr * 0.5)
                tp_dist = sl_dist * 2.0  # 2:1 RR
                
                if position == 1:
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + tp_dist
                else:
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - tp_dist
        
        equity.append(current_capital)
    
    # Metrics
    if not trades:
        return {"config": config.name, "trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0, "max_dd": 0}
    
    wins = sum(1 for t in trades if t["pnl_usd"] > 0)
    total_pnl = sum(t["pnl_usd"] for t in trades)
    
    # Max drawdown
    equity_arr = np.array(equity)
    peak = np.maximum.accumulate(equity_arr)
    dd = (peak - equity_arr) / peak
    max_dd = dd.max() * 100
    
    # Sharpe (simplified)
    returns = np.diff(equity_arr) / equity_arr[:-1]
    sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252 * 288)  # 288 = 5min candles per day
    
    return {
        "config": config.name,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": wins / len(trades) * 100,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(trades),
        "sharpe": sharpe,
        "max_dd": max_dd,
        "final_equity": current_capital,
    }

def main():
    print("=" * 80)
    print("BACKTESTING: Comparando configuraciones de parámetros")
    print("=" * 80)
    
    # Cargar datos
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    all_results = []
    
    for symbol in symbols:
        filepath = f"/srv/profitlab_quantum/data/historical/{symbol}_5m.parquet"
        try:
            df = pd.read_parquet(filepath)
            print(f"\n📊 {symbol}: {len(df)} velas")
        except:
            print(f"❌ {symbol}: No encontrado")
            continue
        
        for config in CONFIGS:
            result = backtest(df, config)
            result["symbol"] = symbol
            all_results.append(result)
    
    # Agregar por configuración
    print("\n" + "=" * 80)
    print("RESULTADOS AGREGADOS")
    print("=" * 80)
    
    for config in CONFIGS:
        config_results = [r for r in all_results if r["config"] == config.name]
        total_trades = sum(r["trades"] for r in config_results)
        total_pnl = sum(r["total_pnl"] for r in config_results)
        avg_win_rate = np.mean([r["win_rate"] for r in config_results if r["trades"] > 0])
        avg_dd = np.mean([r["max_dd"] for r in config_results if r["trades"] > 0])
        avg_sharpe = np.mean([r["sharpe"] for r in config_results if r["trades"] > 0])
        
        print(f"\n🔹 {config.name}:")
        print(f"   Trades: {total_trades}")
        print(f"   Win Rate: {avg_win_rate:.1f}%")
        print(f"   Total PnL: ${total_pnl:+.2f}")
        print(f"   Max DD: {avg_dd:.1f}%")
        print(f"   Sharpe: {avg_sharpe:.2f}")
    
    # Mejor configuración
    best = max(all_results, key=lambda x: x["total_pnl"] if x["trades"] > 0 else -9999)
    print(f"\n{'='*80}")
    print(f"🏆 MEJOR: {best['config']} en {best['symbol']}")
    print(f"   PnL: ${best['total_pnl']:+.2f} | Win Rate: {best['win_rate']:.1f}% | Trades: {best['trades']}")

if __name__ == "__main__":
    main()
