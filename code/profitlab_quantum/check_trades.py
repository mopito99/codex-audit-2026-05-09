from app.db import get_db
from sqlalchemy import text

db = get_db()
try:
    # Check recent trades
    result = db.execute(text("SELECT * FROM paper_trades ORDER BY timestamp DESC LIMIT 5"))
    trades = result.fetchall()
    print(f"Recent Trades: {len(trades)}")
    for t in trades:
        print(f" - {t.timestamp} {t.symbol} {t.action} Size: {t.size}")

    # Check decision logs for the 100% short
    result = db.execute(text("SELECT * FROM decision_logs ORDER BY timestamp DESC LIMIT 1"))
    log = result.fetchone()
    if log:
        print(f"Latest Log: {log.symbol} Probs: {log.agent_probs}")

except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
