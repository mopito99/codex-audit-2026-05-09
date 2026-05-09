import pandas as pd
import numpy as np
from stable_baselines3 import PPO
from env_v42 import QuantumFuturesEnvV42
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback, BaseCallback
import sys

# Data loading
df = pd.read_parquet('/srv/quantum_ppo/data/hbar_usdt_5m.parquet')
split = int(len(df) * 0.8)
df_train = df.iloc[:split].copy()
df_eval = df.iloc[split:].copy()

def make_env_phase1(dataframe):
    def _init():
        # Curriculm Target 0: No Slippage, Base Fee. Soft introduction to market.
        env = QuantumFuturesEnvV42(
            df=dataframe, 
            initial_balance=1000.0, 
            fee=0.0002,   # Phase 1 fee
            window_size=50,
            curriculum_step=0 # NO SLIPPAGE
        )
        return Monitor(env)
    return _init

if __name__ == '__main__':
    num_envs = 64
    
    print('\\n=======================================================')
    print('🪙 INICIANDO ENTRENAMIENTO HEDERA HASHGRAPH (HBAR/USDT)')
    print('   FASE 1 (CURRICULUM = 0) - ENTORNO V4.2')
    print('=======================================================\\n')
    sys.stdout.flush()

    train_env = SubprocVecEnv([make_env_phase1(df_train) for _ in range(num_envs)])
    eval_env = Monitor(QuantumFuturesEnvV42(df=df_eval, initial_balance=1000.0, fee=0.0002, window_size=50, curriculum_step=0))
    
    # Starting from scratch for HBAR
    model = PPO("MlpPolicy", train_env, verbose=1, tensorboard_log="/srv/quantum_ppo/tensorboard_logs/",
                learning_rate=0.0003, # standard starting LR
                n_steps=2048,
                batch_size=8192,
                n_epochs=10,
                gamma=0.999,          # Long sight for phase 1
                gae_lambda=0.95,
                clip_range=0.2,
                ent_coef=0.01)        # Standard starting exploration
    
    print(f'✅ Hyperparameters Phase 1: Gamma={model.gamma}, Entropy={model.ent_coef}')
    sys.stdout.flush()

    checkpoint_cb = CheckpointCallback(
        save_freq=500_000,
        save_path='/srv/quantum_ppo/models_hbar_v42/',
        name_prefix='qppo_hbar_v42_phase1'
    )

    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path='/srv/quantum_ppo/models_hbar_v42/',
        log_path='/srv/quantum_ppo/eval_logs_hbar_v42/',
        eval_freq=500_000,
        n_eval_episodes=5,
        deterministic=True,
        render=False
    )

    # First milestone: train for 40M steps to grasp directionality
    model.learn(
        total_timesteps=40_000_000,
        callback=[checkpoint_cb, eval_cb]
    )
    
    model.save('/srv/quantum_ppo/models_hbar_v42/agent_ppo_hbar_phase1_complete')
    print('\\n🏆 FASE 1 HEDERA FINALIZADA. LISTO PARA FASE 2.')
