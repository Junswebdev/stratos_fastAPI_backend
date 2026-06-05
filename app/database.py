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
    pool_size=5,           # Reduced for Neon free tier (max 10 connections)
    max_overflow=5,        # Allow 5 more if needed, total 10
    pool_timeout=30,       
    pool_recycle=300       # Refresh connections every 5 minutes to avoid Neon idle timeouts
)

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create the base class for ORM models
Base = declarative_base()

# Dependency to get a database session for each FastAPI request
def get_db():
    from sqlalchemy.exc import OperationalError
    from fastapi import HTTPException, status
    
    try:
        db = SessionLocal()
        yield db
    except OperationalError as e:
        # Catch connection/DNS issues (common with serverless DBs like Neon)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed: {str(e)}"
        )
    finally:
        # Use a safe close that doesn't crash if db was never initialized
        try:
            if 'db' in locals():
                db.close()
        except:
            pass