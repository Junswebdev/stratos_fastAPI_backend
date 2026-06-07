from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
import logging
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

from app.database import engine, Base, SessionLocal
from app.controllers import api_router
from app.controllers.chat import websocket_endpoint
from app.models.announcement import Announcement
from app.models.schedule import ScheduleItem
from app.utils.limiter import limiter, _rate_limit_exceeded_handler
import asyncio
from datetime import datetime, timezone

# Initialize the FastAPI application
app = FastAPI(
    title="Class IQ API",
    description="Backend API for the Class IQ Learning Management System, built with a strict MVC pattern.",
    version="0.1.0"
)

# Register CORSMiddleware FIRST to ensure it wraps everything
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False, # Use False when using allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Register the Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

async def cleanup_expired_announcements():
    """Periodically delete expired announcements from the database."""
    while True:
        try:
            db = SessionLocal()
            now = datetime.now(timezone.utc)
            expired = db.query(Announcement).filter(
                Announcement.expires_at != None,
                Announcement.expires_at <= now
            ).all()
            
            if expired:
                for a in expired:
                    db.delete(a)
                db.commit()
                logging.info(f"Cleaned up {len(expired)} expired announcements.")
            db.close()
        except Exception as e:
            logging.error(f"Error during announcement cleanup: {e}")
        
        await asyncio.sleep(3600) # Run every hour

@app.on_event("startup")
async def startup_event():
    # Ensure all database tables are created
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(cleanup_expired_announcements())

app.debug = True

# Mount static files for uploads
os.makedirs("uploads/lessons", exist_ok=True)
os.makedirs("uploads/courses", exist_ok=True)
os.makedirs("uploads/avatars", exist_ok=True)
os.makedirs("uploads/chat", exist_ok=True)

app.mount("/static/lessons", StaticFiles(directory="uploads/lessons"), name="static_lessons")
app.mount("/static/courses", StaticFiles(directory="uploads/courses"), name="static_courses")
app.mount("/static/avatars", StaticFiles(directory="uploads/avatars"), name="static_avatars")
app.mount("/static/chat", StaticFiles(directory="uploads/chat"), name="static_chat")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Register all routes via the main API router
app.include_router(api_router, prefix="/api/v1")

# Top-level WebSocket registration to bypass potential prefixing issues
app.add_api_websocket_route("/ws/{user_id}", websocket_endpoint)

@app.websocket("/ws-test")
async def websocket_test(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"message": "WebSocket connection successful"})
    await websocket.close()

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled request error: %s %s", request.method, request.url)
    
    # Very robust CORS header handling for errors
    origin = request.headers.get("origin", "*")
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Credentials": "false",
    }
    
    return JSONResponse(
        status_code=500,
        headers=headers,
        content={
            "status": "error",
            "message": "An internal server error occurred.",
            "detail": str(exc) if app.debug else "Please contact support."
        },
    )
