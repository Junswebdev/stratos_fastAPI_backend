from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.views.course import CourseShort
from app.models.enrollment import EnrollmentStatus

class EnrollmentBase(BaseModel):
    course_id: UUID

class EnrollmentCreate(EnrollmentBase):
    student_id: Optional[UUID] = None # Optional because it can be inferred from current user

class EnrollmentUpdate(BaseModel):
    progress: Optional[float] = None
    is_active: Optional[bool] = None
    status: Optional[EnrollmentStatus] = None

class EnrollmentRead(EnrollmentBase):
    id: UUID
    student_id: UUID
    status: EnrollmentStatus
    enrolled_at: datetime
    progress: float
    is_active: bool
    course: Optional[CourseShort] = None

    model_config = ConfigDict(from_attributes=True)
