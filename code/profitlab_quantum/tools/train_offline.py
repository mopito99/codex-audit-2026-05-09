#!/usr/bin/env python3
"""
Entrenamiento Offline del PPO usando datos históricos de decision_logs y paper_trades.
Reconstruye rewards basados en el PnL real de los trades.
"""
import os
import sys
import json
import pickle
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import torch
import psycopg2

# Setup path
sys.path.insert(0, '/srv/profitlab_quantum')

from app.models.agent import QuantumAgent
from app.state_schema import STATE_COLUMNS
from app.config import (
    DATABASE_URL,
    PPO_WEIGHTS_DIR,
    PPO_CHUNK_MIN_SAMPLES,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def load_decision_logs(conn, symbol: str, start_date: str = None, end_date: str = None):
    """Carga decision_logs para un símbolo."""
    cur = conn.cursor()
    
    query = '''
        SELECT id, timestamp, symbol, features, agent_probs
        FROM decision_logs
        WHERE symbol = %s
    '''
    params = [symbol]
    
    if start_date:
        query += ' AND timestamp >= %s'
        params.append(start_date)
    if end_date:
        query += ' AND timestamp <= %s'
        params.append(end_date)
    
    query += ' ORDER BY timestamp ASC'
    
    cur.execute(query, params)
    return cur.fetchall()


def load_trades(conn, symbol: str, start_date: str = None, end_date: str = None):
    """Carga trades cerrados para un símbolo."""
    cur = conn.cursor()
    
    query = '''
        SELECT id, timestamp, symbol, action, event, entry_price, exit_price, pnl_usd, margin
        FROM paper_trades
        WHERE symbol = %s AND event = 'CLOSE'
    '''
    params = [symbol]
    
    if start_date:
        query += ' AND timestamp >= %s'
        params.append(start_date)
    if end_date:
        query += ' AND timestamp <= %s'
        params.append(end_date)
    
    query += ' ORDER BY timestamp ASC'
    
    cur.execute(query, params)
    return cur.fetchall()


def extract_state_from_features(features: dict) -> np.ndarray:
    """Extrae el vector de estado de las features SMC."""
    state = []
    for col in STATE_COLUMNS:
        val = features.get(col, 0.0)
        if val is None:
            val = 0.0
        try:
            state.append(float(val))
        except Exception:
            state.append(0.0)
    
    return np.array(state, dtype=np.float32)


def compute_reward(pnl_usd: float, _action: int, margin: float = 50.0) -> float:
    """
    Calcula reward basado en PnL.
    - Positivo si ganó
    - Negativo si perdió
    - Pequeño negativo por HOLD cuando había oportunidad
    """
    if pnl_usd is None:
        return 0.0
    
    # Normalizar por margen para hacer comparable
    if margin and margin > 0:
        pnl_pct = pnl_usd / margin
    else:
        pnl_pct = pnl_usd / 50.0  # Default
    
    # Escalar reward
    reward = pnl_pct * 10.0  # Amplificar señal
    
    # Clamp para evitar extremos
    reward = max(-2.0, min(2.0, reward))
    
    return reward


def _build_trade_index(trades: list) -> dict:
    """Create a timestamp-keyed dict of trade rewards."""
    trade_rewards = {}
    for trade in trades:
        _, ts, _, action, _, _, _, pnl, margin = trade
        ts_key = ts.replace(second=0, microsecond=0)
        trade_rewards[ts_key] = {
            'pnl': pnl,
            'action': action,
            'margin': margin,
        }
    return trade_rewards


def _find_reward(ts_key, trade_rewards: dict, action: int) -> tuple:
    """Search ±5 min window for a matching trade reward. Returns (reward, done)."""
    for delta in range(6):
        for sign in (0, 1, -1):
            check_ts = ts_key + timedelta(minutes=delta * sign)
            if check_ts in trade_rewards:
                tr = trade_rewards[check_ts]
                reward = compute_reward(tr['pnl'], action, tr.get('margin', 50))
                done = 1.0 if abs(reward) > 0.1 else 0.0
                return reward, done
    return 0.0, 0.0


def _parse_decision(decision) -> tuple | None:
    """Parse a decision log row into (timestamp, features_dict, probs_list) or None."""
    _, ts, _, features_json, probs_json = decision
    try:
        features = json.loads(features_json) if isinstance(features_json, str) else features_json
        probs = json.loads(probs_json) if isinstance(probs_json, str) else probs_json
    except Exception:
        return None
    return ts, features, probs


def _action_from_probs(probs) -> tuple:
    """Derive (action, log_prob, value) from probability vector."""
    if probs and len(probs) >= 3:
        action = int(np.argmax(probs))
        log_prob = np.log(max(probs[action], 1e-8))
        value = sum(p * (i - 1) for i, p in enumerate(probs))
    else:
        action = 0
        log_prob = np.log(0.33)
        value = 0.0
    return action, log_prob, value


def build_training_data(conn, symbol: str, days_back: int = 17):
    """Construye datos de entrenamiento desde históricos."""
    logger.info("Building training data for %s (last %d days)", symbol, days_back)

    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    decisions = load_decision_logs(conn, symbol, start_date=start_date)
    trades = load_trades(conn, symbol, start_date=start_date)
    logger.info("  Found %d decisions, %d closed trades", len(decisions), len(trades))

    if not decisions:
        return []

    trade_rewards = _build_trade_index(trades)

    experiences = []
    seq_len = 32
    state_window = []

    for decision in decisions:
        parsed = _parse_decision(decision)
        if parsed is None:
            continue
        ts, features, probs = parsed

        state_raw = extract_state_from_features(features)
        state_window.append(state_raw)
        if len(state_window) > seq_len:
            state_window = state_window[-seq_len:]

        if len(state_window) < seq_len:
            pad = [np.zeros_like(state_raw)] * (seq_len - len(state_window))
            seq_state = np.stack(pad + list(state_window), axis=0)
        else:
            seq_state = np.stack(state_window, axis=0)

        action, log_prob, value = _action_from_probs(probs)

        ts_key = ts.replace(second=0, microsecond=0)
        reward, done = _find_reward(ts_key, trade_rewards, action)

        # Anti-stagnation penalty for continuous HOLD
        if action == 0 and reward == 0:
            reward = -0.001

        ts_ms = int(ts.timestamp() * 1000)
        experiences.append((
            ts_ms, seq_state, action, reward, done,
            torch.tensor(log_prob), torch.tensor(value),
        ))

    significant = [e for e in experiences if abs(e[3]) > 0.001]
    logger.info("  Built %d experiences (%d with significant rewards)", len(experiences), len(significant))
    return experiences


def train_agent_offline(symbol: str, experiences: list, epochs: int = 10):
    """Entrena el agente con experiencias offline."""
    if len(experiences) < PPO_CHUNK_MIN_SAMPLES:
        logger.warning("Not enough samples for %s: %d < %d", symbol, len(experiences), PPO_CHUNK_MIN_SAMPLES)
        return None
    
    # Cargar o crear agente
    weights_path = Path(PPO_WEIGHTS_DIR) / symbol / "ppo.pt"
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    
    agent = QuantumAgent(
        input_dim=len(STATE_COLUMNS),
        action_dim=3,
        autosave_path=str(weights_path),
        autosave_every_updates=1,
    )
    
    if weights_path.exists():
        try:
            agent.load(str(weights_path))
            logger.info("Loaded existing weights for %s", symbol)
        except Exception as e:
            logger.warning("Could not load weights for %s: %s", symbol, e)
    
    # Cargar experiencias en memoria
    agent.memory = experiences
    
    logger.info("Training %s with %d samples for %d epochs...", symbol, len(experiences), epochs)
    
    initial_count = agent._update_count
    
    for epoch in range(epochs):
        agent.update(clear_memory=False)
        logger.info("  Epoch %d/%d - Update count: %d", epoch + 1, epochs, agent._update_count)
    
    # Guardar
    agent.save(str(weights_path))
    
    final_count = agent._update_count
    logger.info("✅ %s: Trained %d updates, saved to %s", symbol, final_count - initial_count, weights_path)
    
    return agent


def main():
    logger.info("=" * 60)
    logger.info("ENTRENAMIENTO OFFLINE PPO - Recuperando 17 días de datos")
    logger.info("=" * 60)
    
    conn = get_connection()
    
    # Obtener símbolos únicos
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT symbol FROM decision_logs')
    symbols = [r[0] for r in cur.fetchall()]
    
    logger.info("Símbolos encontrados: %s", symbols)
    
    # Símbolos activos actuales
    active_symbols = ['BTC-USDT', 'SOL-USDT', 'ADA-USDT', 'AVAX-USDT', 'TRX-USDT']
    
    results = {}
    
    for symbol in active_symbols:
        if symbol not in symbols:
            logger.warning("No data for %s, skipping", symbol)
            continue
        
        logger.info("\n%s", '='*40)
        logger.info("Processing %s", symbol)
        logger.info('='*40)
        
        # Construir datos
        experiences = build_training_data(conn, symbol, days_back=17)
        
        if len(experiences) < 32:
            logger.warning("Not enough experiences for %s: %d", symbol, len(experiences))
            continue
        
        # Entrenar
        agent = train_agent_offline(symbol, experiences, epochs=10)
        
        if agent:
            results[symbol] = {
                'samples': len(experiences),
                'updates': agent._update_count,
            }
    
    conn.close()
    
    logger.info("\n" + "=" * 60)
    logger.info("RESUMEN DE ENTRENAMIENTO")
    logger.info("=" * 60)
    
    for symbol, data in results.items():
        logger.info("  %s: %d samples, %d updates", symbol, data['samples'], data['updates'])
    
    logger.info("\n✅ Entrenamiento offline completado!")


if __name__ == '__main__':
    main()
