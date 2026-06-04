from pydantic import BaseModel
from uuid import UUID

class AIQuestionRequest(BaseModel):
    course_id: UUID
    question: str

class AIAnswerResponse(BaseModel):
    answer: str
