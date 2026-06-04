"""
Rate limiting utilities for the API.
Uses a simple in-memory sliding window approach.
For production, consider using Redis or a dedicated rate limiting service.
"""
from typing import Dict, Tuple
from collections import defaultdict, deque
from datetime import datetime, timedelta
from fastapi import status, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time

# Simple in-memory store: {key: deque of timestamps}
_rate_store: Dict[str, deque] = defaultdict(deque)

def _clean_old_requests(key: str, window_seconds: int):
    """Remove timestamps older than the window."""
    now = time.time()
    cutoff = now - window_seconds
    dq = _rate_store[key]
    while dq and dq[0] < cutoff:
        dq.popleft()

def is_rate_limited(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Check if a key exceeds the rate limit.
    Returns True if rate limited, False otherwise.
    """
    _clean_old_requests(key, window_seconds)
    dq = _rate_store[key]
    if len(dq) >= max_requests:
        return True
    dq.append(time.time())
    return False

def reset_rate_limit(key: str):
    """Clear rate limit for a key (useful for tests)."""
    if key in _rate_store:
        del _rate_store[key]

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that applies rate limiting per IP address.
    Configure limits via environment variables:
    - RATE_LIMIT_MAX_REQUESTS (default: 100)
    - RATE_LIMIT_WINDOW_SECONDS (default: 60)
    """
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._store: Dict[str, deque] = defaultdict(deque)
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Get client IP (X-Forwarded-For takes precedence)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        key = f"ip:{client_ip}"
        
        # Clean old requests
        cutoff = time.time() - self.window_seconds
        dq = self._store[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        
        # Check limit
        if len(dq) >= self.max_requests:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "status": "error",
                    "message": "Rate limit exceeded. Please try again later.",
                    "detail": f"Limit: {self.max_requests} requests per {self.window_seconds}s"
                }
            )
        
        dq.append(time.time())
        
        response = await call_next(request)
        return response

# Decorator for rate limiting specific endpoints
def rate_limit(max_requests: int, window_seconds: int, key_func=None):
    """
    Decorator to rate limit specific endpoints.
    Example:
        @router.post("/")
        @rate_limit(5, 60)  # 5 requests per minute
        def endpoint():
            ...
    """
    def decorator(func):
        import functools
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from FastAPI dependencies
            request: Request = kwargs.get('request')
            if not request:
                # Try to find Request in positional args (difficult, so best to pass request explicitly)
                raise RuntimeError("Rate limit decorator requires 'request: Request' parameter in endpoint")
            
            key = key_func(request) if key_func else request.client.host
            
            if is_rate_limited(key, max_requests, window_seconds):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
