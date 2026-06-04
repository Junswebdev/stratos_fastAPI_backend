import enum
from sqlalchemy import Column, String, Text, ForeignKey, Integer, Boolean, Float, JSON, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class QuestionType(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_IN_THE_BLANKS = "fill_in_the_blanks"
    OBJECTIVE = "objective"
    ESSAY = "essay"

class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey("lessons.id"), nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lesson = relationship("Lesson", back_populates="quiz")
    questions = relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.order")
    attempts = relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(Enum(QuestionType), default=QuestionType.MULTIPLE_CHOICE, nullable=False)
    
    # Store options, correct answers, blanks, etc. in a flexible JSON field
    # For MULTIPLE_CHOICE: {"options": ["A", "B"], "correct_index": 0}
    # For FILL_IN_THE_BLANKS: {"blanks": ["answer1", "answer2"]}
    # For OBJECTIVE: {"answer": "Paris"}
    # For ESSAY: {"rubric": "Describe the theme..."}
    question_data = Column(JSON, nullable=False)
    
    explanation = Column(Text) # AI generated explanation
    order = Column(Integer, default=0)

    quiz = relationship("Quiz", back_populates="questions")

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    quiz_id = Column(UUID(as_uuid=True), ForeignKey("quizzes.id"), nullable=False, index=True)
    score = Column(Float, default=0.0)
    total_points = Column(Integer, default=0)
    
    # List of user answers: [{"question_id": "...", "answer": "...", "is_correct": true}]
    answers = Column(JSON, default=list)
    instructor_feedback = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship("User")
    quiz = relationship("Quiz", back_populates="attempts")
