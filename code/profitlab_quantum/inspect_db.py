from app.db import get_db
from sqlalchemy import text

def inspect_columns():
    db = get_db()
    try:
        result = db.execute(text("SELECT * FROM paper_trades LIMIT 1"))
        print("Columns:", result.keys())
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    inspect_columns()
