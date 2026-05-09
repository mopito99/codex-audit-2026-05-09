from app.db import get_db
from sqlalchemy import text

def reset_db():
    db = get_db()
    try:
        print("Resetting database...")
        db.execute(text("TRUNCATE TABLE paper_trades RESTART IDENTITY;"))
        db.execute(text("TRUNCATE TABLE decision_logs RESTART IDENTITY;"))
        db.commit()
        print("Database reset successfully.")
    except Exception as e:
        print(f"Error resetting database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_db()
