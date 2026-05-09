import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd

class QuantumFuturesEnv(gym.Env):
    metadata = {'render_modes': ['human']}
    LEVERAGE = 5

    def __init__(self, df: pd.DataFrame, initial_balance=1000.0, fee=0.0005, window_size=20):
        super(QuantumFuturesEnv, self).__init__()
        self.df = df.dropna().reset_index(drop=True)
        self.initial_balance = initial_balance
        self.fee = fee
        self.window_size = window_size

        self.features = self.df.drop(
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'], errors='ignore'
        ).values.astype(np.float32)
        self.close_prices = self.df['close'].values.astype(np.float64)

        self.action_space = spaces.Discrete(3)

        self.num_tech_features = self.features.shape[1]
        self.total_features = self.num_tech_features + 3

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.window_size, self.total_features),
            dtype=np.float32
        )

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.current_step = self.window_size
        self.position = 0
        self.entry_price = 0.0
        self.idle_steps = 0
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

        port_state = np.array([self.position, unrealized, balance_ratio], dtype=np.float32)
        port_matrix = np.tile(port_state, (self.window_size, 1))

        obs_final = np.hstack((obs, port_matrix))
        return obs_final.astype(np.float32)

    def _close_position(self, current_price):
        if self.position == 1:
            raw_pnl = (current_price - self.entry_price) / self.entry_price
        elif self.position == -1:
            raw_pnl = (self.entry_price - current_price) / self.entry_price
        else:
            return 0.0

        leveraged_pnl = raw_pnl * self.LEVERAGE
        net_pnl = leveraged_pnl - self.fee
        self.balance *= (1 + net_pnl)
        self.position = 0
        self.entry_price = 0.0
        return net_pnl

    def step(self, action):
        current_price = self.close_prices[self.current_step]
        reward = 0.0
        done = False
        trade_closed = False

        if action == 1:
            if self.position == -1:
                pnl = self._close_position(current_price)
                reward += pnl * 20
                trade_closed = True
            if self.position == 0:
                self.entry_price = current_price
                self.balance *= (1 - self.fee)
                self.position = 1
                self.idle_steps = 0
                reward -= 0.05

        elif action == 2:
            if self.position == 1:
                pnl = self._close_position(current_price)
                reward += pnl * 20
                trade_closed = True
            if self.position == 0:
                self.entry_price = current_price
                self.balance *= (1 - self.fee)
                self.position = -1
                self.idle_steps = 0
                reward -= 0.05

        elif action == 0:
            if self.position != 0:
                pnl = self._close_position(current_price)
                reward += pnl * 20
                trade_closed = True
                self.idle_steps = 0
            else:
                self.idle_steps += 1
                if self.idle_steps > 12:
                    reward -= 0.01 * (self.idle_steps - 12)

        if self.position != 0 and not trade_closed:
            reward -= 0.005

        balance_ratio = self.balance / self.initial_balance

        if balance_ratio < 1.0:
            reward -= (1.0 - balance_ratio) * 0.5

        if self.balance < self.initial_balance * 0.85:
            reward -= 100.0
            done = True

        self.current_step += 1

        if self.current_step >= len(self.df) - 1:
            done = True
            if self.balance > self.initial_balance:
                reward += (balance_ratio - 1.0) * 100.0

        info = {'balance': round(self.balance, 2), 'position': self.position, 'step': self.current_step}
        return self._get_observation(), reward, done, False, info
