from app.db import get_db
from sqlalchemy import text
import pandas as pd

def check_positions():
    db = get_db()
    try:
        # Check paper_positions
        try:
            result = db.execute(text("SELECT * FROM paper_positions"))
            positions = result.fetchall()
            print(f"Open Positions: {len(positions)}")
            for pos in positions:
                print(pos)
        except Exception as e:
            print(f"Error reading paper_positions: {e}")

        # Check paper_trades to see if any new trades happened
        try:
            result = db.execute(text("SELECT * FROM paper_trades ORDER BY timestamp DESC LIMIT 5"))
            trades = result.fetchall()
            print(f"\nRecent Trades: {len(trades)}")
            for trade in trades:
                print(trade)
        except Exception as e:
            print(f"Error reading paper_trades: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    check_positions()
