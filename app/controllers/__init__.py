"""
Controllers Layer (The 'C' in MVC)
This package contains FastAPI APIRouters that handle incoming HTTP requests,
execute business logic, and return standard Views (Pydantic schemas).
"""
import logging
from fastapi import APIRouter

from . import user, course, auth, enrollment, lesson, chat, announcement, stats, quiz, ai, schedule

# Initialize the main API router that will aggregate all other controllers
api_router = APIRouter()


@api_router.get("/", tags=["System"])
def api_root():
    """
    API root endpoint.
    """
    return {"message": "Welcome to the Stratos API v1"}


@api_router.get("/health", tags=["System"])
def health_check():
    """
    Basic health check route to verify the API is running.
    """
    return {"status": "ok", "message": "Stratos API is up and running."}


# Register individual controllers
api_router.include_router(auth.router, prefix="/auth",
                           tags=["Authentication"])
api_router.include_router(user.router, prefix="/users", tags=["Users"])
api_router.include_router(course.router, prefix="/courses", tags=["Courses"])
api_router.include_router(enrollment.router, prefix="/enrollments",
                           tags=["Enrollments"])
api_router.include_router(lesson.router, prefix="/lessons", tags=["Lessons"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(announcement.router, prefix="/announcements", tags=["Announcements"])
api_router.include_router(stats.router, prefix="/stats", tags=["Stats"])
api_router.include_router(quiz.router, prefix="/quiz", tags=["Quiz"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["Schedule"])
