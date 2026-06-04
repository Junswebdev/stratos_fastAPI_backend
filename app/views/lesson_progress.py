from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime

class LessonProgressRead(BaseModel):
    id: UUID
    student_id: UUID
    lesson_id: UUID
    completed_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LessonProgressResponse(BaseModel):
    lesson_id: UUID
    is_completed: bool
    completed_at: datetime | None = None
