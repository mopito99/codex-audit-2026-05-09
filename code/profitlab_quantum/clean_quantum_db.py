from app.db import get_db
from sqlalchemy import text


def list_tables(db):
    rows = db.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    ).fetchall()
    return [r[0] for r in rows]


def truncate_all_public_tables(db):
    # Truncate every table in public schema, restart IDs, cascade FKs.
    db.execute(
        text(
            """
            DO $$
            DECLARE r RECORD;
            BEGIN
              FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
              END LOOP;
            END $$;
            """
        )
    )


def main():
    db = get_db()
    try:
        tables = list_tables(db)
        print("Public tables:")
        for t in tables:
            print(" -", t)

        if not tables:
            print("No tables found in public schema; nothing to clean.")
            return

        print("\nTruncating all public tables (RESTART IDENTITY CASCADE)...")
        truncate_all_public_tables(db)
        db.commit()
        print("Done.")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
