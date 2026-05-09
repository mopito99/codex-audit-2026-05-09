from sqlalchemy import create_engine, text
import pandas as pd
import os

DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "4366037.Cabeza")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "profitlab_quantum_db"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    print(f"--- Recent Decision Logs (BTC-USDT) ---")
    query_logs = text("""
        SELECT timestamp, agent_probs, risk_metrics
        FROM decision_logs
        WHERE symbol = 'BTC-USDT'
        ORDER BY timestamp DESC
        LIMIT 5
    """)
    for row in conn.execute(query_logs):
        print(f"Time: {row.timestamp} | Probs: {row.agent_probs}")
