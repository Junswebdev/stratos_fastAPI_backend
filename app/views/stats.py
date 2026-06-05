from pydantic import BaseModel, Field
from .user import UserRead
from .course import CourseRead
from .announcement import AnnouncementRead
from .enrollment import EnrollmentRead
from typing import Dict, Optional, List
from datetime import datetime

class ScheduleItemRead(BaseModel):
    id: str
    title: str
    time_str: str

class UserStats(BaseModel):
    # Student specific
    enrolled_courses: int = 0
    completed_lessons: int = 0
    pending_lessons: int = 0
    
    # Instructor specific
    courses_created: int = 0
    total_students: int = 0
    total_lessons_authored: int = 0
    
    # Common
    total_announcements: int = 0
    average_progress: float = 0.0 
    active_enrollments: int = 0
    unread_messages: int = 0
    courses_by_level: Dict[str, int] = Field(default_factory=dict)

class DashboardData(BaseModel):
    user: UserRead
    stats: UserStats
    courses: List[CourseRead]
    announcements: List[AnnouncementRead]
    enrollments: List[EnrollmentRead]
    schedule: List[ScheduleItemRead] = []
