import pandas as pd
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.monitor import Monitor
from env import QuantumFuturesEnv
import torch
import sys
import glob
import os

print(f"🔥 PyTorch CUDA: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"💻 GPU: {torch.cuda.get_device_name(0)}")
    print(f"💾 VRAM Total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

print("Cargando Big Data Parquet...")
df = pd.read_parquet('/srv/quantum_ppo/data/sol_usdt_5m.parquet')
print(f"Datos: {df.shape[0]:,} velas x {df.shape[1]} features")

split    = int(len(df) * 0.8)
df_train = df.iloc[:split].copy()
df_eval  = df.iloc[split:].copy()
print(f"Train: {len(df_train):,} velas | Eval: {len(df_eval):,} velas")

def make_env(dataframe):
    def _init():
        env = QuantumFuturesEnv(df=dataframe, initial_balance=1000.0, fee=0.0005)
        return Monitor(env)
    return _init

if __name__ == '__main__':
    num_envs = 64
    print(f"Creando {num_envs} entornos paralelos...")
    train_env = SubprocVecEnv([make_env(df_train) for _ in range(num_envs)])

    eval_env = QuantumFuturesEnv(df=df_eval, initial_balance=1000.0, fee=0.0005)
    eval_env = Monitor(eval_env)

    policy_kwargs = dict(
        net_arch=dict(pi=[512, 512, 256], vf=[512, 512, 256]),
    )

    MODELS_DIR = '/srv/quantum_ppo/models/'
    list_of_files = glob.glob(f'{MODELS_DIR}/*.zip')
    
    if list_of_files:
        latest_file = max(list_of_files, key=os.path.getctime)
        print(f"\n🧠 REANUDANDO MEMORIA: Archivo encontrado -> {os.path.basename(latest_file)}")
        model = PPO.load(latest_file, env=train_env, device="cuda")
    else:
        print("\n🧠 INICIANDO CEREBRO VIRGEN V4 (Scalper): No hay memoria anterior...")
        model = PPO(
            "MlpPolicy",
            train_env,
            verbose        = 1,
            learning_rate  = 0.0003,
            n_steps        = 2048,
            batch_size     = 16384,
            n_epochs       = 10,
            gamma          = 0.99,
            ent_coef       = 0.01,
            vf_coef        = 0.5,
            max_grad_norm  = 0.5,
            tensorboard_log= "/srv/quantum_ppo/tensorboard_logs/",
            policy_kwargs  = policy_kwargs,
            device         = "cuda"
        )

    print(f"\n🖥️  Parámetros del modelo: {sum(p.numel() for p in model.policy.parameters()):,}")
    print(f"🔢 Rollout buffer size: {model.n_steps * num_envs:,} samples")
    print(f"📦 Batch size GPU: {model.batch_size} samples\n")

    checkpoint_cb = CheckpointCallback(
        save_freq  = 500_000,
        save_path  = '/srv/quantum_ppo/models/',
        name_prefix= 'qppo_v4_scalper'
    )
    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path = '/srv/quantum_ppo/models/',
        log_path             = '/srv/quantum_ppo/eval_logs/',
        eval_freq            = 500_000,
        n_eval_episodes      = 5,
        deterministic        = True,
        render               = False
    )

    total_timesteps = 100_000_000
    print(f"🚀 INICIANDO MEGA-MARATÓN v4 (100 Millones Pasos) — {total_timesteps:,} timesteps\n")
    sys.stdout.flush()

    model.learn(
        total_timesteps     = total_timesteps,
        callback            = [checkpoint_cb, eval_cb],
        reset_num_timesteps = False
    )

    model.save("/srv/quantum_ppo/models/agent_ppo_v4_final")
    print("\n✅ Entrenamiento v4 MEGA Completado — Modelo guardado en /srv/quantum_ppo/models/agent_ppo_v4_final.zip")
