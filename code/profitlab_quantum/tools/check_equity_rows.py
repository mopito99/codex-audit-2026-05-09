from app.db import get_db
from sqlalchemy import text

def check_equity():
    db = get_db()
    try:
        print("--- EQUITY TABLE ---")
        rows = db.execute(text("SELECT symbol, balance, peak, updated_at FROM paper_equity")).fetchall()
        for r in rows:
            print(r)
    finally:
        db.close()

if __name__ == "__main__":
    check_equity()