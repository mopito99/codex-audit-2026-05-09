import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd

class QuantumFuturesEnvV41(gym.Env):
    """
    V4.1 - Scalper Paranoico Mejorado
    
    Cambios vs V4:
    1. Reward shaping mejorado: recompensa PnL proporcional, no escalonada
    2. Drawdown gradual en vez de death penalty binaria
    3. Holding reward: premio por mantener posiciones ganadoras
    4. Spread realista + slippage
    5. Ventana de observación más amplia (50 velas)
    6. Red más grande aprovechando A100
    7. Curriculum: comisiones empiezan bajas y suben
    """
    metadata = {'render_modes': ['human']}
    LEVERAGE = 5

    def __init__(self, df: pd.DataFrame, initial_balance=1000.0, fee=0.0005, 
                 window_size=50, curriculum_step=0):
        super().__init__()
        self.df = df.dropna().reset_index(drop=True)
        self.initial_balance = initial_balance
        self.base_fee = fee
        self.window_size = window_size
        self.curriculum_step = curriculum_step  # 0=easy, 1=medium, 2=hard
        
        # Curriculum: fees increase with training progress
        fee_schedule = [0.0002, 0.0004, 0.0005]
        self.fee = fee_schedule[min(curriculum_step, 2)]
        
        # Slippage simulation
        self.slippage = 0.0001 * (1 + curriculum_step * 0.5)

        self.features = self.df.drop(
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'], errors='ignore'
        ).values.astype(np.float32)
        self.close_prices = self.df['close'].values.astype(np.float64)
        self.high_prices = self.df['high'].values.astype(np.float64) if 'high' in self.df.columns else self.close_prices
        self.low_prices = self.df['low'].values.astype(np.float64) if 'low' in self.df.columns else self.close_prices

        # Actions: 0=HOLD, 1=LONG, 2=SHORT
        self.action_space = spaces.Discrete(3)

        self.num_tech_features = self.features.shape[1]
        # Added: position_age, max_drawdown, win_streak
        self.total_features = self.num_tech_features + 6
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.window_size, self.total_features),
            dtype=np.float32
        )
        
        # Tracking stats
        self.total_trades = 0
        self.winning_trades = 0
        self.max_balance = initial_balance

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.current_step = self.window_size
        self.position = 0
        self.entry_price = 0.0
        self.idle_steps = 0
        self.position_age = 0
        self.peak_unrealized = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.max_balance = self.initial_balance
        self.consecutive_losses = 0
        return self._get_observation(), {}

    def _get_observation(self):
        obs = self.features[self.current_step - self.window_size: self.current_step].copy()
        
        current_price = self.close_prices[self.current_step]
        unrealized = 0.0
        if self.position == 1:
            unrealized = ((current_price - self.entry_price) / self.entry_price) * self.LEVERAGE
        elif self.position == -1:
            unrealized = ((self.entry_price - current_price) / self.entry_price) * self.LEVERAGE

        balance_ratio = self.balance / self.initial_balance
        win_rate = self.winning_trades / max(self.total_trades, 1)
        position_age_norm = min(self.position_age / 100.0, 1.0)
        drawdown = (self.max_balance - self.balance) / max(self.max_balance, 1)

        port_state = np.array([
            self.position, unrealized, balance_ratio,
            position_age_norm, win_rate, drawdown
        ], dtype=np.float32)
        
        port_matrix = np.tile(port_state, (self.window_size, 1))
        obs_final = np.hstack((obs, port_matrix))
        return obs_final.astype(np.float32)

    def _close_position(self, current_price):
        if self.position == 0:
            return 0.0
            
        # Apply slippage
        if self.position == 1:
            exit_price = current_price * (1 - self.slippage)
            raw_pnl = (exit_price - self.entry_price) / self.entry_price
        else:
            exit_price = current_price * (1 + self.slippage)
            raw_pnl = (self.entry_price - exit_price) / self.entry_price

        leveraged_pnl = raw_pnl * self.LEVERAGE
        net_pnl = leveraged_pnl - self.fee
        self.balance *= (1 + net_pnl)
        
        # Track stats
        self.total_trades += 1
        if net_pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        self.max_balance = max(self.max_balance, self.balance)
        self.position = 0
        self.entry_price = 0.0
        self.position_age = 0
        self.peak_unrealized = 0.0
        return net_pnl

    def step(self, action):
        current_price = self.close_prices[self.current_step]
        reward = 0.0
        done = False
        trade_pnl = None

        # ── ACTION EXECUTION ──
        if action == 1:  # GO LONG
            if self.position == -1:
                pnl = self._close_position(current_price)
                trade_pnl = pnl
            if self.position == 0:
                self.entry_price = current_price * (1 + self.slippage)
                self.balance *= (1 - self.fee)
                self.position = 1
                self.idle_steps = 0

        elif action == 2:  # GO SHORT
            if self.position == 1:
                pnl = self._close_position(current_price)
                trade_pnl = pnl
            if self.position == 0:
                self.entry_price = current_price * (1 - self.slippage)
                self.balance *= (1 - self.fee)
                self.position = -1
                self.idle_steps = 0

        elif action == 0:  # HOLD / CLOSE
            if self.position != 0:
                pnl = self._close_position(current_price)
                trade_pnl = pnl
            else:
                self.idle_steps += 1

        # ── REWARD SHAPING V4.1 ──
        
        # 1. Trade PnL reward (proporcional, no fixed multiplier)
        if trade_pnl is not None:
            if trade_pnl > 0:
                # Winner: reward scales with size, bonus for big wins
                reward += trade_pnl * 30 + 0.5  # bonus por ganar
            else:
                # Loser: penalización proporcional pero menos agresiva
                reward += trade_pnl * 15  # half the pain of gains
        
        # 2. Holding reward: premio por mantener posiciones ganadoras
        if self.position != 0:
            self.position_age += 1
            if self.position == 1:
                unrealized = ((current_price - self.entry_price) / self.entry_price) * self.LEVERAGE
            else:
                unrealized = ((self.entry_price - current_price) / self.entry_price) * self.LEVERAGE
            
            self.peak_unrealized = max(self.peak_unrealized, unrealized)
            
            if unrealized > 0:
                # Reward for holding winners (small but consistent)
                reward += 0.02 * min(unrealized, 0.5)
            elif unrealized < -0.02:
                # Punish for holding losers too long
                reward -= 0.01
            
            # Drawdown from peak: learned trailing stop behavior
            if self.peak_unrealized > 0.01 and unrealized < self.peak_unrealized * 0.5:
                reward -= 0.05  # you should have taken profit
        
        # 3. Idle penalty (gentle, only after 20 bars)
        if self.position == 0 and self.idle_steps > 20:
            reward -= 0.005 * min(self.idle_steps - 20, 20)
        
        # 4. Balance health (smooth gradient, not binary death)
        balance_ratio = self.balance / self.initial_balance
        if balance_ratio < 1.0:
            reward -= (1.0 - balance_ratio) * 0.2  # gentler than V4's 0.5
        
        # 5. Consecutive loss penalty (teaches risk management)
        if self.consecutive_losses >= 3:
            reward -= 0.1 * (self.consecutive_losses - 2)
        
        # 6. Death: gradual drawdown limit (not instant death at 15%)
        if self.balance < self.initial_balance * 0.80:  # 20% drawdown
            reward -= 50.0  # harsh but not as extreme as V4's -100
            done = True
        elif self.balance < self.initial_balance * 0.90:
            reward -= 0.5  # warning zone

        self.current_step += 1

        if self.current_step >= len(self.df) - 1:
            done = True
            # Survival bonus: made it through the whole dataset
            if self.balance > self.initial_balance:
                reward += 20.0  # significant bonus for profitability
            reward += (self.balance / self.initial_balance - 1) * 50  # PnL bonus

        obs = self._get_observation() if not done else np.zeros(
            (self.window_size, self.total_features), dtype=np.float32
        )
        
        return obs, reward, done, False, {
            "balance": self.balance,
            "trades": self.total_trades,
            "win_rate": self.winning_trades / max(self.total_trades, 1),
        }
