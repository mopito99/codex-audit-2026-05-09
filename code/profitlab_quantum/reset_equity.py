from app.db import get_db
from sqlalchemy import text
from app.config import TOKENS, INITIAL_CAPITAL

def reset_equity():
    db = get_db()
    try:
        print("Resetting paper equity...")
        # Clear existing equity records
        db.execute(text("TRUNCATE TABLE paper_equity RESTART IDENTITY;"))
        
        # Re-initialize with default capital split
        capital_per_token = INITIAL_CAPITAL / len(TOKENS)
        
        for token in TOKENS:
            print(f"Setting {token} to ${capital_per_token:.2f}")
            db.execute(text(
                "INSERT INTO paper_equity (symbol, balance, peak, updated_at) VALUES (:s, :b, :p, NOW())"
            ), {"s": token, "b": capital_per_token, "p": capital_per_token})
            
        db.commit()
        print("Equity reset successfully.")
    except Exception as e:
        print(f"Error resetting equity: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_equity()
