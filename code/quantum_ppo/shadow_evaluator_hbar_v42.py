import time
import json
import logging
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import talib
import ccxt
from stable_baselines3 import PPO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/srv/quantum_ppo/logs/shadow_hbar_v42.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ShadowDaemon")

SYMBOL      = 'HBAR/USDT'
TIMEFRAME   = '5m'
MODEL_PATH  = '/srv/quantum_ppo/models_hbar_v42/agent_ppo_hbar_phase3_complete.zip'
WINDOW_SIZE = 50
LEVERAGE    = 5
FEE         = 0.0005
SLIPPAGE    = 0.0002

class ShadowPortfolio:
    def __init__(self):
        self.initial_balance = 1000.0
        self.balance = 1000.0
        self.max_balance = 1000.0
        self.position = 0
        self.entry_price = 0.0
        self.position_age = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.consecutive_sls = 0
        self.phold_history = []
        self.closed_hold_times = []
        
    def step(self, current_price, action):
        trade_pnl = None
        
        # Actions: 0 = HOLD/CLOSE, 1 = LONG, 2 = SHORT
        if action == 1: 
            if self.position == -1:
                trade_pnl = self._close_position(current_price)
            elif self.position == 0:
                self.entry_price = current_price * (1 + SLIPPAGE)
                self.balance *= (1 - FEE)
                self.position = 1

        elif action == 2: 
            if self.position == 1:
                trade_pnl = self._close_position(current_price)
            elif self.position == 0:
                self.entry_price = current_price * (1 - SLIPPAGE)
                self.balance *= (1 - FEE)
                self.position = -1

        elif action == 0: 
            if self.position != 0:
                trade_pnl = self._close_position(current_price)
                
        if self.position != 0:
            self.position_age += 1
            
        return trade_pnl
            
    def _close_position(self, current_price):
        if self.position == 0: return 0.0
        
        if self.position == 1:
            exit_price = current_price * (1 - SLIPPAGE)
            raw_pnl = (exit_price - self.entry_price) / self.entry_price
        else:
            exit_price = current_price * (1 + SLIPPAGE)
            raw_pnl = (self.entry_price - exit_price) / self.entry_price

        leveraged_pnl = raw_pnl * LEVERAGE
        net_pnl = leveraged_pnl - FEE
        self.balance *= (1 + net_pnl)
        
        self.total_trades += 1
        if net_pnl > 0:
            self.winning_trades += 1
            self.consecutive_sls = 0
        else:
            self.consecutive_sls += 1
            
        self.closed_hold_times.append(self.position_age)
        self.max_balance = max(self.max_balance, self.balance)
        self.position = 0
        self.entry_price = 0.0
        self.position_age = 0
        return net_pnl

    def get_state_metrics(self, current_price):
        unrealized = 0.0
        if self.position == 1:
            unrealized = (((current_price - self.entry_price) / self.entry_price) * LEVERAGE) - FEE
        elif self.position == -1:
            unrealized = (((self.entry_price - current_price) / self.entry_price) * LEVERAGE) - FEE

        balance_ratio = self.balance / self.initial_balance
        win_rate = self.winning_trades / max(self.total_trades, 1)
        position_age_norm = min(self.position_age / 100.0, 1.0)
        drawdown = (self.max_balance - self.balance) / max(self.max_balance, 1)

        return np.array([
            self.position, unrealized, balance_ratio,
            position_age_norm, win_rate, drawdown
        ], dtype=np.float32)

def shape_state(df):
    close  = df['close'].values.astype(float)
    high   = df['high'].values.astype(float)
    low    = df['low'].values.astype(float)

    df['RSI_14'] = talib.RSI(close, timeperiod=14)

    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['MACD']        = macd
    df['MACD_signal'] = macd_signal
    df['MACD_hist']   = macd_hist

    df['ATR_14'] = talib.ATR(high, low, close, timeperiod=14)

    bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['BB_upper'] = bb_upper
    df['BB_mid']   = bb_mid
    df['BB_lower'] = bb_lower
    
    # Prevenir division por cero en bb_width
    bb_mid_safe = np.where(bb_mid == 0, 1e-9, bb_mid)
    df['BB_width'] = (bb_upper - bb_lower) / bb_mid_safe

    for ma in [10, 20, 50, 200]:
        sma = talib.SMA(close, timeperiod=ma)
        df[f'SMA_{ma}']      = sma
        sma_safe = np.where(sma == 0, 1e-9, sma)
        df[f'dist_SMA_{ma}'] = (df['close'] - sma) / sma_safe

    df['Vol_SMA_20'] = df['volume'].rolling(20).mean()
    df['Vol_Ratio'] = df['volume'] / df['Vol_SMA_20']
    df['Log_Return'] = np.log(df['close'] / df['close'].shift(1))

    features_ordered = ['RSI_14', 'MACD', 'MACD_signal', 'MACD_hist', 'ATR_14', 'BB_upper', 'BB_mid', 'BB_lower', 'BB_width', 'SMA_10', 'dist_SMA_10', 'SMA_20', 'dist_SMA_20', 'SMA_50', 'dist_SMA_50', 'SMA_200', 'dist_SMA_200', 'Vol_SMA_20', 'Vol_Ratio', 'Log_Return']
    df.dropna(inplace=True)
    # Return DataFrame with only the explicitly required features and OHLCV base
    df = df[['open', 'high', 'low', 'close', 'volume'] + features_ordered]
    return df

def fetch_data():
    exchange = ccxt.bingx({'enableRateLimit': True})
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=1000)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def run_shadow_reactor():
    logger.info("🤖 Iniciando Shadow Evaluator V4.2 - Cargando Matrix...")
    try:
        model = PPO.load(MODEL_PATH)
    except Exception as e:
        logger.error(f"❌ Error al cargar modelo V4.2: {e}")
        return

    portfolio = ShadowPortfolio()
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Esperar hasta que sea múltiplo de 5 min exacto
            if now.minute % 5 != 0 or now.second > 10:
                time.sleep(5)
                continue
                
            df = fetch_data()
            obs_df = shape_state(df)
            current_price = obs_df['close'].iloc[-1]
            
            # Extract Technical Features
            tech_features = obs_df.drop(
                columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore'
            ).values.astype(np.float32)
            
            if len(tech_features) < WINDOW_SIZE:
                logger.warning("No hay suficientes features calculadas aún.")
                time.sleep(60)
                continue
                
            # Construct Final V4.2 Tensor State (Tech + Port)
            tech_obs = tech_features[-WINDOW_SIZE:].copy()
            port_state = portfolio.get_state_metrics(current_price)
            port_matrix = np.tile(port_state, (WINDOW_SIZE, 1))
            
            final_obs = np.hstack((tech_obs, port_matrix)).astype(np.float32)
            
            # Prediction
            action, _ = model.predict(final_obs, deterministic=True)
            action = int(np.squeeze(action))
            
            # Action probabilities (P(hold))
            obs_tensor = model.policy.obs_to_tensor(final_obs[np.newaxis, ...])[0]
            distribution = model.policy.get_distribution(obs_tensor)
            probs = distribution.distribution.probs.detach().cpu().numpy()[0]
            p_hold = probs[0]
            
            portfolio.phold_history.append(p_hold)
            if len(portfolio.phold_history) > 50:
                portfolio.phold_history.pop(0)

            # Execution logic on Shadow Portfolio
            logger.info(f"== [TICK] Símbolo: {SYMBOL} | Precio: ${current_price:,.4f} ==")
            trade_pnl = portfolio.step(current_price, action)
            
            # === CLAUDE KPIs ===
            # KPI 1: P(hold)
            phold_avg = np.mean(portfolio.phold_history)
            danger_phold = (phold_avg < 0.30 and len(portfolio.phold_history) == 50)
            
            # KPI 2: Hold Time Promedio
            avg_hold_time = np.mean(portfolio.closed_hold_times[-20:]) if portfolio.closed_hold_times else 0
            
            # KPI 3: Circuit Breaker
            if portfolio.consecutive_sls >= 4:
                logger.error(f"🚨 CIRCUIT BREAKER! 4 Stop-Losses Consecutivos detectados. PnL actual simulado: {portfolio.balance}")
                time.sleep(1800)
                
            if danger_phold:
                logger.warning(f"⚠️ PELIGRO: P(hold) Movering Average a 50 velas cayó a {phold_avg:.2f}. Riesgo de Action Entropy Collapse!")
            
            log_msg = f"  ➜ Acción IA: {action} | Shadow Bal: ${portfolio.balance:.2f} | P(hold): {p_hold:.2%} | Avg Hold: {avg_hold_time:.1f} velas"
            if trade_pnl is not None:
                log_msg += f" | TRADE CLOSED! PnL: {trade_pnl:.2%}"
            logger.info(log_msg)

            # Rate limit para no operar multiples veces en la misma vela de minuto 0
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error en el ciclo asíncrono: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_shadow_reactor()
