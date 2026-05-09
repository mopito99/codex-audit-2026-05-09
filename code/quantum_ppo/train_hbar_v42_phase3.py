import pandas as pd
import numpy as np
from stable_baselines3 import PPO
from env_v42 import QuantumFuturesEnvV42
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback, BaseCallback
import sys

class ClaudeEntropyCallback(BaseCallback):
    def __init__(self, verbose=1):
        super().__init__(verbose)
        self.milestone_10M_checked = False

    def _on_step(self) -> bool:
        # Check if we have recent episode stats
        if len(self.model.ep_info_buffer) > 0 and self.num_timesteps % 50_000 == 0:
            ep_len_mean = np.mean([ep_info["l"] for ep_info in self.model.ep_info_buffer])
            
            # 10M Milestone Check
            if self.num_timesteps >= 10_000_000 and not self.milestone_10M_checked:
                if ep_len_mean > 250:
                    self.model.ent_coef = 0.010
                    self.milestone_10M_checked = True
                    if self.verbose:
                        print(f"\n[CLAUDE PROTOCOL] 10M Steps Alcanzados. ep_len_mean = {ep_len_mean:.1f} (>250). Reduciendo entropia a 0.010\n")
                        sys.stdout.flush()
            
            # Alarm Condition - Auto Revert
            if self.num_timesteps > 5_000_000 and ep_len_mean < 150:
                if getattr(self.model, 'ent_coef', 0.0) < 0.015:
                    self.model.ent_coef = 0.015
                    self.milestone_10M_checked = False
                    if self.verbose:
                        print(f"\n[EMERGENCIA] ep_len_mean cayo a {ep_len_mean:.1f} (<150). Aumentando entropia a 0.015. Panico direccional detectado.\n")
                        sys.stdout.flush()

        return True

# Data loading
df = pd.read_parquet('/srv/quantum_ppo/data/hbar_usdt_5m.parquet')

# Time blocking
split = int(len(df) * 0.85)
df_train = df.iloc[:split].copy()
df_eval = df.iloc[split:].copy()

def make_env_phase3(dataframe):
    def _init():
        # Curriculum Target 2: Max Slippage, Max Fee. Real world friction.
        env = QuantumFuturesEnvV42(
            df=dataframe,
            initial_balance=1000.0,
            fee=0.0005,   # Phase 3 full fee
            window_size=50,
            curriculum_step=2 # SLIPPAGE AND FEE AT MAX (HARD)
        )
        return Monitor(env)
    return _init

if __name__ == '__main__':
    print('=======================================================')
    print('🪙 INICIANDO ENTRENAMIENTO HEDERA HASHGRAPH (HBAR/USDT)')
    print('   FASE 3 (CURRICULUM = 2) - CONDICIONES DE MERCADO REALES')
    print('=======================================================\n')

    num_envs = 64
    train_env = SubprocVecEnv([make_env_phase3(df_train) for _ in range(num_envs)])
    eval_env = Monitor(QuantumFuturesEnvV42(df=df_eval, initial_balance=1000.0, fee=0.0005, window_size=50, curriculum_step=2))
    
    # Load previously trained model from Phase 2
    model = PPO.load('/srv/quantum_ppo/models_hbar_v42/agent_ppo_hbar_phase2_complete.zip', 
                     env=train_env, 
                     custom_objects={'learning_rate': 0.0001, 'clip_range': 0.2})
    
    model.ent_coef = 0.015   
    
    # Explicitly enforce LR on optimizer group
    for param_group in model.policy.optimizer.param_groups:
        param_group['lr'] = 0.0001
        
    print(f'✅ Hyperparameters Phase 3: Gamma={model.gamma}, Entropy={model.ent_coef}, LR=0.0001')

    checkpoint_cb = CheckpointCallback(
        save_freq=2_000_000 // num_envs,
        save_path='/srv/quantum_ppo/models_hbar_v42/',
        name_prefix='qppo_hbar_v42_phase3'
    )

    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path='/srv/quantum_ppo/models_hbar_v42/',
        log_path='/srv/quantum_ppo/eval_logs_hbar_v42/',
        eval_freq=1_000_000 // num_envs,
        n_eval_episodes=5,
        deterministic=True,
        render=False
    )
    
    claude_cb = ClaudeEntropyCallback()

    model.learn(
        total_timesteps=30_000_000,
        reset_num_timesteps=False,
        callback=[checkpoint_cb, eval_cb, claude_cb]
    )

    model.save('/srv/quantum_ppo/models_hbar_v42/agent_ppo_hbar_phase3_complete')
    print('\n🏆 FASE 3 HEDERA FINALIZADA. LISTO PARA DESPLIEGUE.')
