"""
PPO Memory Persistence - Guarda/carga memoria del agente en PostgreSQL
para que sobreviva reinicios del proceso.
"""
import pickle
import numpy as np
import psycopg2
from psycopg2.extras import execute_batch
from typing import List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class PPOMemoryPersistence:
    """Maneja la persistencia de memoria PPO en PostgreSQL."""
    
    def __init__(self, db_url: str, symbol: str):
        self.db_url = db_url
        self.symbol = symbol
        self._conn = None
    
    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.db_url)
        return self._conn
    
    def save_experience(
        self,
        ts_ms: int,
        state: np.ndarray,
        action: int,
        reward: float,
        done: float,
        log_prob: float,
        value: float
    ) -> None:
        """Guarda una experiencia individual en la DB."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # Serializar state como bytes
            state_bytes = pickle.dumps(state)
            
            cur.execute('''
                INSERT INTO ppo_memory (symbol, ts_ms, state, action, reward, done, log_prob, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (self.symbol, ts_ms, state_bytes, action, reward, done, log_prob, value))
            
            conn.commit()
        except Exception as e:
            logger.error("Error saving PPO experience: %s", e)
            if self._conn:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
    
    def save_batch(self, experiences: List[Tuple]) -> None:
        """Guarda múltiples experiencias de forma eficiente."""
        if not experiences:
            return
            
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # Formato: (ts_ms, state, action, reward, done, log_prob, value)
            data = []
            for exp in experiences:
                if len(exp) == 7:
                    ts_ms, state, action, reward, done, log_prob, value = exp
                else:
                    # Legacy format sin timestamp
                    state, action, reward, done, log_prob, value = exp
                    ts_ms = 0
                
                # Convertir tensores a floats si es necesario
                lp = float(log_prob.item()) if hasattr(log_prob, 'item') else float(log_prob)
                v = float(value.item()) if hasattr(value, 'item') else float(value)
                
                state_bytes = pickle.dumps(state)
                data.append((self.symbol, int(ts_ms), state_bytes, int(action), float(reward), float(done), lp, v))
            
            execute_batch(cur, '''
                INSERT INTO ppo_memory (symbol, ts_ms, state, action, reward, done, log_prob, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', data)
            
            conn.commit()
            logger.info("Saved %d PPO experiences for %s", len(data), self.symbol)
        except Exception as e:
            logger.error("Error saving PPO batch: %s", e)
            if self._conn:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
    
    def load_memory(self, window_hours: float = 72.0, max_samples: int = 4096) -> List[Tuple]:
        """Carga memoria desde DB para el símbolo, limitado por ventana de tiempo."""
        try:
            import time
            conn = self._get_conn()
            cur = conn.cursor()
            
            # Calcular timestamp mínimo
            now_ms = int(time.time() * 1000)
            min_ts_ms = now_ms - int(window_hours * 3600 * 1000)
            
            cur.execute('''
                SELECT ts_ms, state, action, reward, done, log_prob, value
                FROM ppo_memory
                WHERE symbol = %s AND ts_ms >= %s
                ORDER BY ts_ms DESC
                LIMIT %s
            ''', (self.symbol, min_ts_ms, max_samples))
            
            rows = cur.fetchall()
            
            memory = []
            for row in reversed(rows):  # Ordenar cronológicamente
                ts_ms, state_bytes, action, reward, done, log_prob, value = row
                state = pickle.loads(state_bytes)
                
                # Reconstruir como tensores detached (se convertirán en el agente)
                import torch
                log_prob_t = torch.tensor(log_prob)
                value_t = torch.tensor(value)
                
                memory.append((int(ts_ms), state, int(action), float(reward), float(done), log_prob_t, value_t))
            
            logger.info("Loaded %d PPO experiences for %s", len(memory), self.symbol)
            return memory
        except Exception as e:
            logger.error("Error loading PPO memory: %s", e)
            return []
    
    def prune_old(self, window_hours: float = 72.0) -> int:
        """Elimina experiencias más antiguas que la ventana."""
        try:
            import time
            conn = self._get_conn()
            cur = conn.cursor()
            
            now_ms = int(time.time() * 1000)
            min_ts_ms = now_ms - int(window_hours * 3600 * 1000)
            
            cur.execute('''
                DELETE FROM ppo_memory
                WHERE symbol = %s AND ts_ms < %s
            ''', (self.symbol, min_ts_ms))
            
            deleted = cur.rowcount
            conn.commit()
            
            if deleted > 0:
                logger.info("Pruned %d old PPO experiences for %s", deleted, self.symbol)
            return deleted
        except Exception as e:
            logger.error("Error pruning PPO memory: %s", e)
            return 0
    
    def log_training(self, update_count: int, samples_used: int, loss: float = None) -> None:
        """Registra un evento de entrenamiento."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            cur.execute('''
                INSERT INTO ppo_training_log (symbol, update_count, samples_used, loss)
                VALUES (%s, %s, %s, %s)
            ''', (self.symbol, update_count, samples_used, loss))
            
            conn.commit()
        except Exception as e:
            logger.error("Error logging PPO training: %s", e)
    
    def get_last_update_count(self) -> int:
        """Obtiene el último update_count registrado."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            
            cur.execute('''
                SELECT update_count FROM ppo_training_log
                WHERE symbol = %s
                ORDER BY trained_at DESC
                LIMIT 1
            ''', (self.symbol,))
            
            row = cur.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error("Error getting last update count: %s", e)
            return 0
    
    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
