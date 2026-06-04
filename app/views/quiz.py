from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Any
from app.models.quiz import QuestionType

class QuizQuestionBase(BaseModel):
    question_text: str
    question_type: QuestionType
    question_data: dict # flexible for options, answers, etc.
    explanation: Optional[str] = None
    order: int = 0

class QuizQuestionCreate(QuizQuestionBase):
    pass

class QuizQuestionRead(QuizQuestionBase):
    id: UUID
    quiz_id: UUID

    model_config = ConfigDict(from_attributes=True)

class QuizBase(BaseModel):
    lesson_id: UUID
    title: str
    description: Optional[str] = None

class QuizCreate(QuizBase):
    questions: List[QuizQuestionCreate] = []

class QuizAIRequest(BaseModel):
    lesson_id: UUID
    num_questions: int = 5

class QuizRead(QuizBase):
    id: UUID
    questions: List[QuizQuestionRead] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserAnswer(BaseModel):
    question_id: UUID
    answer: Any # index for MC, string for others

class QuizSubmitRequest(BaseModel):
    quiz_id: UUID
    answers: List[UserAnswer]

class QuizAttemptRead(BaseModel):
    id: UUID
    student_id: UUID
    quiz_id: UUID
    score: float
    total_points: int
    answers: List[dict]
    instructor_feedback: Optional[str] = None
    completed_at: datetime

    model_config = ConfigDict(from_attributes=True)

class QuizAttemptGrade(BaseModel):
    score: float
    instructor_feedback: Optional[str] = None

class QuizAttemptWithStudent(QuizAttemptRead):
    student_name: str
    student_email: str

    model_config = ConfigDict(from_attributes=True)
