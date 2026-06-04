import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# SQLAlchemy requires "postgresql://" instead of "postgres://"
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Create the database engine
if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")
    
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_pre_ping=True,
    pool_size=20,          # Maintain up to 20 connections in the pool
    max_overflow=10,       # Allow up to 10 additional connections if the pool is full
    pool_timeout=30,       # Wait up to 30 seconds for an available connection before timing out
    pool_recycle=1800      # Recycle connections after 30 minutes to prevent stale connections
)

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create the base class for ORM models
Base = declarative_base()

# Dependency to get a database session for each FastAPI request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()