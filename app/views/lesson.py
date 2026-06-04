from pydantic import BaseModel, ConfigDict
from uuid import UUID
from typing import Optional
from app.models.lesson import ContentType

class LessonBase(BaseModel):
    title: str
    content_type: ContentType = ContentType.TEXT
    content_data: Optional[str] = None
    file_url: Optional[str] = None # New field for uploaded files
    order: int = 0
    is_preview: bool = False

class LessonCreate(LessonBase):
    module_id: UUID

class LessonUpdate(BaseModel):
    title: Optional[str] = None
    content_type: Optional[ContentType] = None
    content_data: Optional[str] = None
    file_url: Optional[str] = None # New field for uploaded files
    order: Optional[int] = None
    is_preview: Optional[bool] = None

class LessonRead(LessonBase):
    id: UUID
    module_id: UUID

    model_config = ConfigDict(from_attributes=True)
