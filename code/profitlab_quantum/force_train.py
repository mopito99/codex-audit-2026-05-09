#!/usr/bin/env python3
"""
Force-train PPO for all symbols using ALL available memory from DB.
v2: Handles mixed state shapes (34,) vs (32,34) by padding 1D to sequences.
"""
import os, sys, time, pickle, logging
import numpy as np
import torch
import psycopg2
from pathlib import Path

os.chdir('/srv/profitlab_quantum')
sys.path.insert(0, '/srv/profitlab_quantum')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('force_train')

from app.config import DATABASE_URL, PPO_WEIGHTS_DIR, PPO_WEIGHTS_PATH, PPO_PER_SYMBOL
from app.models.agent import QuantumAgent

SYMBOLS = ['BTC-USDT', 'SOL-USDT', 'ADA-USDT', 'AVAX-USDT', 'TRX-USDT']
NUM_UPDATES = 5
MAX_SAMPLES = 8192
SEQ_LEN = 32

def load_all_memory(db_url, symbol, max_samples=8192):
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute('''SELECT ts_ms, state, action, reward, done, log_prob, value
        FROM ppo_memory WHERE symbol = %s ORDER BY ts_ms DESC LIMIT %s''',
        (symbol, max_samples))
    rows = cur.fetchall()
    conn.close()
    memory = []
    for row in reversed(rows):
        ts_ms, state_bytes, action, reward, done, log_prob, value = row
        state = pickle.loads(state_bytes)
        arr = np.asarray(state, dtype=np.float32)
        # Normalize to (SEQ_LEN, input_dim) for transformer
        if arr.ndim == 1:
            # Pad 1D state to sequence by repeating
            arr = np.tile(arr, (SEQ_LEN, 1))  # (32, 34)
        elif arr.ndim == 2 and arr.shape[0] != SEQ_LEN:
            # Wrong sequence length - pad or truncate
            if arr.shape[0] < SEQ_LEN:
                pad = np.zeros((SEQ_LEN - arr.shape[0], arr.shape[1]), dtype=np.float32)
                arr = np.vstack([pad, arr])
            else:
                arr = arr[-SEQ_LEN:]
        memory.append((int(ts_ms), arr, int(action), float(reward), float(done),
                       torch.tensor(log_prob), torch.tensor(value)))
    return memory

def get_weights_path(symbol):
    if PPO_PER_SYMBOL:
        return Path(PPO_WEIGHTS_DIR) / symbol.replace('/', '_') / 'ppo.pt'
    return Path(PPO_WEIGHTS_PATH)

def force_train_symbol(symbol):
    logger.info(f'\n{"="*60}')
    logger.info(f'TRAINING {symbol}')
    logger.info(f'{"="*60}')
    memory = load_all_memory(DATABASE_URL, symbol, MAX_SAMPLES)
    logger.info(f'Loaded {len(memory)} experiences from DB')
    if len(memory) < 128:
        logger.warning(f'Insufficient data ({len(memory)} < 128). Skipping.')
        return False
    first_state = memory[0][1]
    logger.info(f'State shape (normalized): {first_state.shape}')
    input_dim = first_state.shape[-1]
    weights_path = get_weights_path(symbol)
    agent = QuantumAgent(input_dim=input_dim, action_dim=3,
        autosave_path=str(weights_path), autosave_every_updates=1,
        db_url=DATABASE_URL, symbol=symbol)
    if weights_path.exists():
        try:
            agent.load(str(weights_path))
            logger.info(f'Loaded existing weights from {weights_path}')
        except Exception as e:
            logger.warning(f'Could not load weights: {e}')
    else:
        legacy = Path(PPO_WEIGHTS_PATH)
        if legacy.exists():
            try:
                agent.load(str(legacy))
                logger.info(f'Bootstrapped from legacy weights {legacy}')
            except Exception as e:
                logger.warning(f'Could not load legacy weights: {e}')
    logger.info(f'Training on device: {agent.device}')
    for update_i in range(NUM_UPDATES):
        agent.memory = list(memory)
        if update_i > 0:
            import random
            random.shuffle(agent.memory)
        initial_count = agent._update_count
        agent.update(clear_memory=False)
        if agent._update_count > initial_count:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: OK (count={agent._update_count})')
        else:
            logger.info(f'  Update {update_i+1}/{NUM_UPDATES}: No update')
            break
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    agent.save(str(weights_path))
    logger.info(f'Weights saved to {weights_path}')
    logger.info(f'Final update_count: {agent._update_count}')
    return True

def main():
    logger.info('='*60)
    logger.info('FORCE TRAINING - ALL SYMBOLS')
    logger.info(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"}')
    logger.info(f'Symbols: {SYMBOLS}')
    logger.info(f'Updates per symbol: {NUM_UPDATES}')
    logger.info('='*60)
    start = time.time()
    results = {}
    for symbol in SYMBOLS:
        try:
            ok = force_train_symbol(symbol)
            results[symbol] = "OK" if ok else "SKIPPED"
        except Exception as e:
            logger.error(f'FAILED {symbol}: {e}')
            import traceback; traceback.print_exc()
            results[symbol] = f'FAILED: {e}'
    elapsed = time.time() - start
    logger.info(f'\n{"="*60}')
    logger.info('TRAINING COMPLETE')
    logger.info(f'Time: {elapsed:.1f}s')
    for sym, status in results.items():
        logger.info(f'  {sym}: {status}')
    logger.info(f'\nWeight files:')
    for sym in SYMBOLS:
        p = get_weights_path(sym)
        if p.exists():
            logger.info(f'  {p}: {p.stat().st_size/1024:.1f} KB')
        else:
            logger.info(f'  {p}: MISSING')
    logger.info('='*60)

if __name__ == '__main__':
    main()
