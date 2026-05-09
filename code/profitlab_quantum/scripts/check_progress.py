#!/usr/bin/env python3
import psycopg2
from datetime import datetime

DB_URL = "postgresql://postgres:4366037.Cabeza@localhost/profitlab_quantum_db"

def check():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    print("\n" + "="*60)
    print("QUANTUM V2.0 - TRAINING PROGRESS")
    print("="*60)
    
    cur.execute("SELECT symbol, MAX(update_count), MAX(samples_used) FROM ppo_training_log GROUP BY symbol")
    rows = cur.fetchall()
    print("\nPPO Training:")
    for r in rows:
        print(f"  {r[0]}: {r[1]} updates, {r[2]} samples")
    
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END), ROUND(SUM(pnl_usd)::numeric, 2) FROM paper_trades WHERE event = 'CLOSE'")
    stats = cur.fetchone()
    print(f"\nTrades: {stats[0] or 0}, Wins: {stats[1] or 0}, PnL: ${stats[2] or 0}")
    
    cur.execute("SELECT symbol, ROUND(balance::numeric, 2) FROM paper_equity")
    for r in cur.fetchall():
        print(f"  {r[0]}: ${r[1]}")
    
    conn.close()

if __name__ == "__main__":
    check()
