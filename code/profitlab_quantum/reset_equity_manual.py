from sqlalchemy import create_engine, text
import os

DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "4366037.Cabeza")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "profitlab_quantum_db"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    print("Resetting equity for all active tokens to $200.00...")
    # Reset all to 200
    conn.execute(text("UPDATE paper_equity SET balance = 200.0"))
    conn.commit()
    
    # Verify
    result = conn.execute(text("SELECT * FROM paper_equity"))
    for row in result:
        print(row)
