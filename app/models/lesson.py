from sqlalchemy import Column, String, Text, ForeignKey, Integer, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import enum
from app.database import Base

class ContentType(str, enum.Enum):
    VIDEO = "video"
    TEXT = "text"
    QUIZ = "quiz"
    FILE = "file"

class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    module_id = Column(UUID(as_uuid=True), ForeignKey("modules.id"), nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    content_type = Column(Enum(ContentType), default=ContentType.TEXT, nullable=False)
    content_data = Column(Text) # URL, Markdown, or JSON
    file_url = Column(Text, nullable=True)
    order = Column(Integer, default=0)
    is_preview = Column(Boolean, default=False, index=True)

    # Relationships
    module = relationship("Module", back_populates="lessons")
    quiz = relationship("Quiz", back_populates="lesson", uselist=False, cascade="all, delete-orphan")
    lesson_progress = relationship("LessonProgress", back_populates="lesson", cascade="all, delete-orphan")
