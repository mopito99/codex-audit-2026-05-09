import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,          # detect stale connections
    pool_size=5,
    max_overflow=3,
    pool_recycle=1800,           # recycle connections every 30 min
    pool_timeout=10,             # wait max 10s for a connection
    connect_args={
        "options": "-c statement_timeout=30000"   # 30s max per query
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    return db

def init_db():
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
