from app.db import get_db
from sqlalchemy import text

def dump_trades():
    db = get_db()
    try:
        result = db.execute(text("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 5"))
        rows = result.fetchall()
        if not rows:
            print("No trades found.")
        for row in rows:
            print(row)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    dump_trades()
