from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re
from app.views.user import UserRead

class Token(BaseModel):
    access_token: str
    token_type: str
    user: Optional[UserRead] = None

class TokenPayload(BaseModel):
    sub: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class GoogleLogin(BaseModel):
    id_token: str
