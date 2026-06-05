from pydantic import BaseModel, ConfigDict
from pydantic import Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from app.models.user import EduLevel
from app.views.lesson import LessonRead
from app.views.user import UserRead

class ModuleBase(BaseModel):
    title: str
    description: Optional[str] = None
    order: int = 0

class ModuleCreate(ModuleBase):
    course_id: UUID

class ModuleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None

class ModuleRead(ModuleBase):
    id: UUID
    course_id: UUID
    lessons: List[LessonRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

class CourseBase(BaseModel):
    title: str
    description: Optional[str] = None
    edu_level: EduLevel = EduLevel.HIGHER_ED
    instructor_id: UUID
    image_url: Optional[str] = None

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    edu_level: Optional[EduLevel] = None
    instructor_id: Optional[UUID] = None
    image_url: Optional[str] = None

class CourseRead(CourseBase):
    id: UUID
    join_code: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    modules: List[ModuleRead] = Field(default_factory=list)
    instructor: Optional[UserRead] = None
    is_enrolled: bool = False
    enrollment_status: Optional[str] = None
    announcements_count: int = 0
    modules_count: int = 0
    lessons_count: int = 0
    instructor_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class CourseShort(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    instructor_id: UUID
    image_url: Optional[str] = None
    instructor: Optional[UserRead] = None

    model_config = ConfigDict(from_attributes=True)
