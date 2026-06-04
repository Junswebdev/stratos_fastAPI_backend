from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional
import re
from app.models.user import UserRole, EduLevel

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole = UserRole.STUDENT
    edu_level: EduLevel = EduLevel.HIGHER_ED
    is_active: Optional[bool] = True

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    
    
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

class UserRead(UserBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
