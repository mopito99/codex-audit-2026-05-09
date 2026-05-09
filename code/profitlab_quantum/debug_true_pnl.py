from app.db import get_db
from sqlalchemy import text

db = get_db()
INITIAL_CAPITAL = 1000.0

try:
    # 1. Realized PnL from closed trades
    # Note: pnl_usd is recorded for closed trades
    result = db.execute(text("SELECT SUM(pnl_usd) FROM paper_trades WHERE pnl_usd IS NOT NULL"))
    realized_pnl = result.scalar() or 0.0
    
    print(f"Initial Capital: {INITIAL_CAPITAL}")
    print(f"Total Realized PnL: {realized_pnl}")
    
    # 2. Unrealized PnL from open positions
    # We need current prices to calculate this accurately, but let's see if we can estimate or if there are open positions.
    result = db.execute(text("SELECT * FROM paper_positions"))
    positions = result.fetchall()
    print(f"Open Positions: {len(positions)}")
    
    unrealized_pnl = 0.0
    # For now, assume 0 unrealized if we can't easily fetch live price here, 
    # or use the 'pnl' column if it's being updated (unlikely in this table structure usually).
    # The web app calculates unrealized pnl dynamically.
    
    total_equity = INITIAL_CAPITAL + realized_pnl
    print(f"Calculated True Equity (Realized): {total_equity}")
    
    # Compare with paper_equity sum
    result = db.execute(text("SELECT SUM(balance) FROM paper_equity"))
    equity_table_sum = result.scalar() or 0.0
    print(f"Sum of paper_equity table: {equity_table_sum}")

except Exception as e:
    print(f"Error: {e}")
