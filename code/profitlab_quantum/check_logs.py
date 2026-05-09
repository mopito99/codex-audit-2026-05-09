from app.db import get_db
from sqlalchemy import text

db = get_db()
try:
    result = db.execute(text("SELECT COUNT(*) FROM decision_logs"))
    count = result.scalar()
    print(f"Decision Logs Count: {count}")
    
    if count > 0:
        row = db.execute(text("SELECT * FROM decision_logs ORDER BY timestamp DESC LIMIT 1")).fetchone()
        print(f"Latest Log: {row.symbol} at {row.timestamp}")
        print(f"Features: {row.features}")
except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
