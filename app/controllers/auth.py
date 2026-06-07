from datetime import timedelta
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional
from google.oauth2 import id_token
from google.auth.transport import requests

from app.database import get_db
from app.utils.security import create_access_token, verify_password, ACCESS_TOKEN_EXPIRE_MINUTES, get_password_hash
from app.models.user import User
from app.views.auth import Token, UserLogin, GoogleLogin
from app.views.user import UserCreate, UserRead

router = APIRouter()

GOOGLE_CLIENT_ID = "924562664956-n363u9htfvjvr5s49pvjekktgd0s9gbm.apps.googleusercontent.com"

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

@router.post("/register", response_model=UserRead)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Create a new user.
    """
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists",
        )
    
    new_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role or "student",
        is_active=True,
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logging.info(f"New user registered: {new_user.email}")
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists",
        )
    
    return new_user

@router.post("/login", response_model=Token)
def login(
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

@router.post("/login/google", response_model=Token)
def login_google(
    login_data: GoogleLogin,
    db: Session = Depends(get_db)
):
    """
    Verify Google ID Token and login/register the user.
    """
    try:
        # Verify the ID token
        idinfo = id_token.verify_oauth2_token(
            login_data.id_token, requests.Request(), GOOGLE_CLIENT_ID
        )

        # ID token is valid. Get the user's Google info.
        email = idinfo['email']
        full_name = idinfo.get('name', '')
        avatar_url = idinfo.get('picture', '')

        # Check if user exists
        user = db.query(User).filter(User.email == email).first()

        if not user:
            # Register new user
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=get_password_hash(f"google_{email}"), # Placeholder password
                role="student",
                is_active=True,
                avatar_url=avatar_url
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logging.info(f"New user registered via Google: {email}")
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        user_read = UserRead.model_validate(user)
        
        return {
            "access_token": create_access_token(
                user.id, expires_delta=access_token_expires
            ),
            "token_type": "bearer",
            "user": user_read,
        }

    except ValueError:
        # Invalid token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID Token",
        )
    except Exception as e:
        logging.error(f"Google login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during Google login",
        )

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
    
    user_read = UserRead.model_validate(user)
    
    return {
        "access_token": create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
        "user": user_read,
    }
