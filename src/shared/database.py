from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

import os

class Base(DeclarativeBase):
    pass

engine = None
def get_db():
    global engine
    if not engine:
        # Check if DATABASE_URL is set (Render.com and other cloud providers)
        database_url = os.environ.get('DATABASE_URL')
        
        if database_url:
            # Use the full DATABASE_URL from environment (production)
            # Render.com provides this automatically
            DATABASE_URL = database_url
        else:
            # Build from individual components (local development)
            host = os.environ.get('DATABASE_HOST', 'localhost')
            username = os.environ.get('DATABASE_USER', 'postgres')
            password = os.environ.get('DATABASE_PASSWORD', '')
            database = os.environ.get('POSTGRES_DB', 'team13')
            
            DATABASE_URL = f"postgresql+psycopg2://{username}:{password}@{host}:5432/{database}"
        
        engine = create_engine(DATABASE_URL)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()