"""
Quantum PPO V4.1 - Scalper Paranoico MEJORADO
GPU: A100 80GB FULL UTILIZATION
"""
import pandas as pd
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback, BaseCallback
from stable_baselines3.common.monitor import Monitor
from env_v41 import QuantumFuturesEnvV41
import torch
import sys
import os

print(f'🔥 PyTorch CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'💻 GPU: {torch.cuda.get_device_name(0)}')
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f'💾 VRAM Total: {vram:.1f} GB')

# ── DATA ──
print('Cargando Big Data Parquet...')
df = pd.read_parquet('/srv/quantum_ppo/data/sol_usdt_5m.parquet')
print(f'Datos: {df.shape[0]:,} velas x {df.shape[1]} features')

split = int(len(df) * 0.8)
df_train = df.iloc[:split].copy()
df_eval = df.iloc[split:].copy()
print(f'Train: {len(df_train):,} velas | Eval: {len(df_eval):,} velas')

# ── CURRICULUM CALLBACK ──
class CurriculumCallback(BaseCallback):
    """Increases difficulty as training progresses."""
    def __init__(self, total_timesteps, verbose=0):
        super().__init__(verbose)
        self.total_timesteps = total_timesteps
    
    def _on_step(self):
        progress = self.num_timesteps / self.total_timesteps
        # Log progress for dashboard
        if self.num_timesteps % 131072 == 0:
            info = self.locals.get('infos', [{}])
            if info:
                balances = [i.get('balance', 0) for i in info if isinstance(i, dict)]
                win_rates = [i.get('win_rate', 0) for i in info if isinstance(i, dict)]
                if balances:
                    avg_bal = np.mean(balances)
                    avg_wr = np.mean(win_rates) * 100
                    print(f'📊 Curriculum {progress*100:.1f}% | avg_balance= | avg_wr={avg_wr:.1f}%')
                    sys.stdout.flush()
        return True

# ── ENV FACTORY ──
def make_env(dataframe, curriculum_step=0):
    def _init():
        env = QuantumFuturesEnvV41(
            df=dataframe, 
            initial_balance=1000.0, 
            fee=0.0005,
            window_size=50,
            curriculum_step=curriculum_step
        )
        return Monitor(env)
    return _init

if __name__ == '__main__':
    # ── A100 OPTIMIZED: max parallel envs ──
    num_envs = 64  # Doubled from V4's 64
    
    total_timesteps = 100_000_000
    
    # ── CURRICULUM PHASES ──
    phases = [
        {'steps': 30_000_000,  'curriculum': 0, 'lr': 0.0005,  'label': 'EASY (low fees)'},
        {'steps': 40_000_000,  'curriculum': 1, 'lr': 0.0003,  'label': 'MEDIUM (real fees)'},
        {'steps': 30_000_000,  'curriculum': 2, 'lr': 0.0001,  'label': 'HARD (high fees + slippage)'},
    ]
    
    MODELS_DIR = '/srv/quantum_ppo/models_v41/'
    os.makedirs(MODELS_DIR, exist_ok=True)
    
    model = None
    cumulative_steps = 0
    
    for phase_idx, phase in enumerate(phases):
        print(f"\n{'='*60}")
        print(f"🧠 FASE {phase_idx+1}/3: {phase['label']}")
        print(f"   Steps: {phase['steps']:,} | LR: {phase['lr']} | Curriculum: {phase['curriculum']}")
        print(f"{'='*60}\n")
        sys.stdout.flush()
        
        # Create env with current curriculum
        train_env = SubprocVecEnv([make_env(df_train, phase['curriculum']) for _ in range(num_envs)])
        eval_env = QuantumFuturesEnvV41(df=df_eval, initial_balance=1000.0, fee=0.0005, 
                                         window_size=50, curriculum_step=phase['curriculum'])
        eval_env = Monitor(eval_env)
        
        if model is None:
            # ── A100 OPTIMIZED ARCHITECTURE ──
            policy_kwargs = dict(
                net_arch=dict(
                    pi=[1024, 512, 256],  # Bigger policy network
                    vf=[1024, 512, 256]   # Bigger value network
                ),
            )
            
            model = PPO(
                'MlpPolicy',
                train_env,
                verbose=1,
                learning_rate=phase['lr'],
                n_steps=2048,         # rollout per env
                batch_size=32768,     # 2x V4: A100 can handle it
                n_epochs=10,
                gamma=0.995,          # More patient (V4 was 0.99)
                gae_lambda=0.95,
                ent_coef=0.005,       # Less entropy: more exploitation
                vf_coef=0.5,
                max_grad_norm=0.5,
                clip_range=0.2,
                tensorboard_log='/srv/quantum_ppo/tensorboard_logs_v41/',
                policy_kwargs=policy_kwargs,
                device='cuda'
            )
        else:
            model.set_env(train_env)
            model.learning_rate = phase['lr']
        
        params = sum(p.numel() for p in model.policy.parameters())
        buffer_size = model.n_steps * num_envs
        print(f'🖥️  Parámetros del modelo: {params:,}')
        print(f'🔢 Rollout buffer size: {buffer_size:,} samples')
        print(f'📦 Batch size GPU: {model.batch_size:,} samples')
        print(f'🎮 Envs paralelos: {num_envs}')
        sys.stdout.flush()
        
        checkpoint_cb = CheckpointCallback(
            save_freq=500_000,
            save_path=MODELS_DIR,
            name_prefix=f'qppo_v41_phase{phase_idx}'
        )
        eval_cb = EvalCallback(
            eval_env,
            best_model_save_path=MODELS_DIR,
            log_path='/srv/quantum_ppo/eval_logs_v41/',
            eval_freq=500_000,
            n_eval_episodes=5,
            deterministic=True,
            render=False
        )
        curriculum_cb = CurriculumCallback(total_timesteps=phase['steps'])
        
        model.learn(
            total_timesteps=phase['steps'],
            callback=[checkpoint_cb, eval_cb, curriculum_cb],
            reset_num_timesteps=(phase_idx == 0)
        )
        
        # Save phase model
        phase_path = f'{MODELS_DIR}/qppo_v41_phase{phase_idx}_complete'
        model.save(phase_path)
        print(f'\n✅ Fase {phase_idx+1} completada — Guardado en {phase_path}.zip')
        sys.stdout.flush()
        
        cumulative_steps += phase['steps']
        
        # Close envs
        train_env.close()
    
    # Final save
    model.save(f'{MODELS_DIR}/agent_ppo_v41_final')
    print(f'\n🏆 ENTRENAMIENTO V4.1 COMPLETO — 100M pasos en 3 fases')
    print(f'   Modelo final: {MODELS_DIR}/agent_ppo_v41_final.zip')
