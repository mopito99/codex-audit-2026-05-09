"""
Reset PPO memory and weights, then pretrain with historical data.
V2.0 - 01/02/2026
"""
import sys
sys.path.insert(0, '/srv/profitlab_quantum')

import psycopg2
import os
import shutil
from pathlib import Path

DB_URL = "postgresql://postgres:4366037.Cabeza@localhost/profitlab_quantum_db"

def reset_ppo_memory():
    """Limpia la memoria PPO de la base de datos."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Borrar memoria PPO
    cur.execute("DELETE FROM ppo_memory")
    cur.execute("DELETE FROM ppo_training_log")
    
    conn.commit()
    print("✅ PPO memory and training logs cleared")
    conn.close()

def reset_ppo_weights():
    """Borra los pesos guardados para que el modelo inicie desde cero."""
    weights_dir = Path("/srv/profitlab_quantum/artifacts/ppo")
    by_symbol_dir = weights_dir / "by_symbol"
    
    if by_symbol_dir.exists():
        shutil.rmtree(by_symbol_dir)
        print(f"✅ Deleted {by_symbol_dir}")
    
    # Re-create directory
    by_symbol_dir.mkdir(parents=True, exist_ok=True)
    print("✅ PPO weights directory reset")

def reset_paper_trades():
    """Opcional: resetear los trades para empezar limpio."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Cerrar posiciones abiertas
    cur.execute("DELETE FROM paper_positions")
    
    # Resetear equity a inicial
    cur.execute("UPDATE paper_equity SET balance = 200, peak = 200")
    
    conn.commit()
    print("✅ Paper positions closed, equity reset to 00")
    conn.close()

if __name__ == "__main__":
    print("\n🔄 QUANTUM V2.0 - RESET AND PREPARE FOR TRAINING\n")
    
    reset_ppo_memory()
    reset_ppo_weights()
    reset_paper_trades()
    
    print("\n✅ Sistema reseteado. Listo para iniciar con V2.0")
    print("\n📊 Próximos pasos:")
    print("   1. Ejecutar: systemctl start profitlab_quantum_bot")
    print("   2. Monitorear: tail -f /srv/profitlab_quantum/quantum.log")
    print("   3. Esperar 24-48h de entrenamiento")
