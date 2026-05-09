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
        self.milestone_80M_checked = False
        self.milestone_85M_checked = False

    def _on_step(self) -> bool:
        # Check if we have recent episode stats
        if len(self.model.ep_info_buffer) > 0 and self.num_timesteps % 50_000 == 0:
            ep_len_mean = np.mean([ep_info["l"] for ep_info in self.model.ep_info_buffer])
            
            # Start of Phase 3 is at 70M total_timesteps in curriculum
            # self.num_timesteps tracks relative steps in this learn() call
            current_total_steps = 70_000_000 + self.num_timesteps
            
            # 80M Milestone Check
            if current_total_steps >= 80_000_000 and not self.milestone_80M_checked:
                if ep_len_mean > 200:
                    self.model.ent_coef = 0.015
                    self.milestone_80M_checked = True
                    if self.verbose:
                        print(f"\\n[CLAUDE PROTOCOL] 80M Steps Alcanzados. ep_len_mean = {ep_len_mean:.1f} (>200). Reduciendo entropia a 0.015\\n")
                        sys.stdout.flush()
                # If < 200, we do not mark checked, meaning it will keep trying to reduce entropy once it crosses 200
                
            # 85M Milestone Check
            if current_total_steps >= 85_000_000 and not self.milestone_85M_checked and self.milestone_80M_checked:
                if ep_len_mean > 250:
                    self.model.ent_coef = 0.010
                    self.milestone_85M_checked = True
                    if self.verbose:
                        print(f"\\n[CLAUDE PROTOCOL] 85M Steps Alcanzados. ep_len_mean = {ep_len_mean:.1f} (>250). Reduciendo entropia a 0.010\\n")
                        sys.stdout.flush()
            
            # Alarm Condition - Auto Revert
            if current_total_steps > 85_000_000 and ep_len_mean < 150:
                if self.model.ent_coef < 0.025:
                    self.model.ent_coef = 0.025
                    self.milestone_80M_checked = False
                    self.milestone_85M_checked = False
                    if self.verbose:
                        print(f"\\n[EMERGENCIA] ep_len_mean cayo a {ep_len_mean:.1f} (<150). Revirtiendo entropia a 0.025. Panico direccional detectado.\\n")
                        sys.stdout.flush()

        return True

df = pd.read_parquet('/srv/quantum_ppo/data/sol_usdt_5m.parquet')
split = int(len(df) * 0.8)
df_train = df.iloc[:split].copy()
df_eval = df.iloc[split:].copy()

def make_env_phase3(dataframe):
    def _init():
        env = QuantumFuturesEnvV42(
            df=dataframe, 
            initial_balance=1000.0, 
            fee=0.0005,
            window_size=50,
            curriculum_step=2
        )
        return Monitor(env)
    return _init

if __name__ == '__main__':
    num_envs = 64
    
    print('\\n=======================================================')
    print('🧠 INICIANDO PHASE 3 (HARD) - V4.2 AUTONOMO')
    print('=======================================================\\n')
    sys.stdout.flush()

    train_env = SubprocVecEnv([make_env_phase3(df_train) for _ in range(num_envs)])
    eval_env = Monitor(QuantumFuturesEnvV42(df=df_eval, initial_balance=1000.0, fee=0.0005, window_size=50, curriculum_step=2))
    
    model = PPO.load('/srv/quantum_ppo/models_v41/qppo_v41_phase1_complete.zip', custom_objects={'learning_rate': 0.0001, 'clip_range': 0.2})
    
    model.set_env(train_env)
    
    model.gamma = 0.990      
    model.ent_coef = 0.025   # Start with highest entropy (Claude's Panic Protocol)
    
    for param_group in model.policy.optimizer.param_groups:
        param_group['lr'] = 0.0001
        
    print(f"✅ Patches Aplicados: Gamma={model.gamma}, Entropy={model.ent_coef}, LR={model.policy.optimizer.param_groups[0]['lr']}")
    sys.stdout.flush()

    checkpoint_cb = CheckpointCallback(
        save_freq=500_000,
        save_path='/srv/quantum_ppo/models_v42/',
        name_prefix='qppo_v42_phase3'
    )
    
    claude_cb = ClaudeEntropyCallback()

    model.learn(
        total_timesteps=30_000_000,
        reset_num_timesteps=False,
        callback=[checkpoint_cb, claude_cb]
    )
    
    model.save('/srv/quantum_ppo/models_v42/agent_ppo_v42_final')
    print('\\n🏆 ENTRENAMIENTO FINALIZADO - V4.2 LISTO')
