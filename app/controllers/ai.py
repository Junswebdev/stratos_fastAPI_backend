from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.deps import get_current_active_user
from app.models.user import User
from app.views.ai import AIQuestionRequest, AIAnswerResponse
from app.services.ai_service import ai_service
from app.models.enrollment import Enrollment

router = APIRouter()

@router.post("/ask", response_model=AIAnswerResponse)
async def ask_ai(
    request: AIQuestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Ask the Mistral AI a question about a specific course.
    User must be enrolled in the course or be the instructor/admin.
    """
    # 1. Permission Check
    is_enrolled = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == request.course_id,
        Enrollment.is_active == True
    ).first() is not None
    
    if not is_enrolled and current_user.role != "admin":
        # Check if they are the instructor
        from app.models.course import Course
        course = db.query(Course).filter(Course.id == request.course_id).first()
        if not course or course.instructor_id != current_user.id:
             raise HTTPException(status_code=403, detail="You do not have access to this course's AI assistant")

    # 2. Get AI Answer
    answer = await ai_service.ask_question(db, str(request.course_id), request.question)
    
    return AIAnswerResponse(answer=answer)
