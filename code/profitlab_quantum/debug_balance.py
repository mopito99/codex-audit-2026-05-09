from app.db import get_db
from sqlalchemy import text

db = get_db()
try:
    # List tables (PostgreSQL)
    result = db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"))
    tables = result.fetchall()
    print("Tables:", [t[0] for t in tables])

    # Check columns of paper_trades
    print("\n--- Columns of paper_trades ---")
    result = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'paper_trades';"))
    columns = result.fetchall()
    print([c[0] for c in columns])

    # Check columns of paper_equity
    print("\n--- Columns of paper_equity ---")
    result = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'paper_equity';"))
    columns = result.fetchall()
    print([c[0] for c in columns])

    # Check paper_equity (generic)
    print("\n--- Paper Equity Data ---")
    result = db.execute(text("SELECT * FROM paper_equity LIMIT 5"))
    for row in result.fetchall():
        print(row)

    # Check trades with PnL and Leverage
    print("\n--- Recent Trades with PnL and Leverage ---")
    result = db.execute(text("SELECT timestamp, symbol, action, size, leverage, pnl_usd FROM paper_trades ORDER BY timestamp DESC LIMIT 20"))
    trades = result.fetchall()
    for t in trades:
        print(f"{t.timestamp} | {t.symbol} {t.action} | Size: {t.size} | Lev: {t.leverage} | PnL: {t.pnl_usd}")
            
except Exception as e:
    print(f"Error: {e}")
