"""
Models Layer (The 'M' in MVC)
This package contains all SQLAlchemy declarative base models representing database tables.
"""
from app.database import Base
from .user import User
from .course import Course, Module
from .enrollment import Enrollment
from .lesson import Lesson
from .message import Message
from .message_read_state import MessageReadState
from .announcement import Announcement
from .lesson_progress import LessonProgress
from .quiz import Quiz, QuizQuestion, QuizAttempt