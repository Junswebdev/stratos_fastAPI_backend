from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class MessageBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    recipient_id: Optional[UUID] = None
    course_id: Optional[UUID] = None

class MessageCreate(MessageBase):
    pass

class MessageRead(MessageBase):
    id: UUID
    sender_id: UUID
    sender_name: Optional[str] = None
    timestamp: datetime
    reply_to_id: Optional[UUID] = None
    is_edited: Optional[datetime] = None
    is_deleted: Optional[datetime] = None
    reply_to: Optional['MessageReply'] = None
    likes: List[str] = []
    dislikes: List[str] = []

    model_config = ConfigDict(from_attributes=True)

class MessageReply(BaseModel):
    id: UUID
    sender_id: UUID
    sender_name: Optional[str] = None
    content: str
    
    model_config = ConfigDict(from_attributes=True)
