from datetime import timedelta
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional

from app.database import get_db
from app.utils.security import create_access_token, verify_password, ACCESS_TOKEN_EXPIRE_MINUTES, get_password_hash
from app.models.user import User
from app.views.auth import Token, UserLogin
from app.views.user import UserCreate, UserRead

router = APIRouter()

# Simple in-memory rate limiter: {email: [(timestamp, count), ...]}
_auth_attempts: dict[str, list[tuple[float, int]]] = {}

def _check_rate_limit(email: str, max_attempts: int = 5, window_seconds: int = 300) -> None:
    """Raise HTTPException if too many failed attempts for this email within window."""
    now = time.time()
    attempts = _auth_attempts.get(email, [])
    # Remove expired attempts
    cutoff = now - window_seconds
    attempts = [(ts, cnt) for ts, cnt in attempts if ts > cutoff]
    total_attempts = sum(cnt for _, cnt in attempts)
    if total_attempts >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later."
        )
    _auth_attempts[email] = attempts

def _record_attempt(email: str, success: bool = False) -> None:
    now = time.time()
    attempts = _auth_attempts.get(email, [])
    cutoff = now - 300  # 5 minute window
    attempts = [(ts, cnt) for ts, cnt in attempts if ts > cutoff]
    if success:
        # On success, clear attempts
        _auth_attempts[email] = []
    else:
        # Increment count for current window
        if attempts and attempts[-1][0] > now - 60:
            # Aggregate within last minute
            attempts[-1] = (attempts[-1][0], attempts[-1][1] + 1)
        else:
            attempts.append((now, 1))
    _auth_attempts[email] = attempts

@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Public registration endpoint.
    """
    logging.info(f"Registration attempt for email: {user_in.email}")
    # Rate limiting by email
    _check_rate_limit(user_in.email, max_attempts=10, window_seconds=3600)  # 10 per hour
    
    # Check if user with this email already exists
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        logging.warning(f"Registration failed: User with email {user_in.email} already exists.")
        _record_attempt(user_in.email, success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )
    
    # Create new user
    db_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        edu_level=user_in.edu_level,
        is_active=user_in.is_active,
    )
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logging.error(f"Registration failed due to IntegrityError for email: {user_in.email}")
        _record_attempt(user_in.email, success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )
    db.refresh(db_user)
    logging.info(f"Registration successful for email: {user_in.email}")
    _record_attempt(user_in.email, success=True)
    return db_user

@router.post("/login", response_model=Token)
def login_json(
    login_in: UserLogin, 
    db: Session = Depends(get_db)
):
    """
    JSON compatible login, get an access token for future requests.
    """
    logging.info(f"Login attempt for email: {login_in.email}")
    
    # Rate limiting by email
    _check_rate_limit(login_in.email, max_attempts=5, window_seconds=300)  # 5 per 5 minutes
    
    user = db.query(User).filter(User.email == login_in.email).first()
    if not user or not verify_password(login_in.password, user.hashed_password):
        logging.warning(f"Login failed: Incorrect email or password for {login_in.email}")
        _record_attempt(login_in.email, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    elif not user.is_active:
        logging.warning(f"Login failed: Inactive user {login_in.email}")
        _record_attempt(login_in.email, success=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    logging.info(f"Login successful for email: {login_in.email}")
    _record_attempt(login_in.email, success=True)
    
    # Explicit conversion to Pydantic model to avoid serialization recursion issues
    user_read = UserRead.model_validate(user)
    
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
        "user": user_read,
    }

@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    Used mainly by Swagger UI and other OAuth2 clients.
    """
    _check_rate_limit(form_data.username, max_attempts=5, window_seconds=300)
    
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        _record_attempt(form_data.username, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    elif not user.is_active:
        _record_attempt(form_data.username, success=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    _record_attempt(form_data.username, success=True)
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
        "user": user,
    }
