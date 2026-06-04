from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str
