import enum
from sqlalchemy import Column, ForeignKey, DateTime, Float, Boolean, UniqueConstraint, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class EnrollmentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True)
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.PENDING, nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    progress = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True, index=True)

    # Relationships
    student = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")

    # A student can only enroll in a course once
    __table_args__ = (UniqueConstraint('student_id', 'course_id', name='_student_course_uc'),)
