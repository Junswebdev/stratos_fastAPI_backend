from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import uuid
import shutil
import os

from app.database import get_db
from app.models.lesson import Lesson
from app.models.course import Course, Module
from app.models.user import User, UserRole
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.lesson_progress import LessonProgress
from app.views.lesson import LessonCreate, LessonRead, LessonUpdate
from app.views.lesson_progress import LessonProgressResponse
from app.utils.deps import get_current_active_user

router = APIRouter()

# Define an upload directory (create this directory in your project root)
UPLOAD_DIR = "uploads/lessons"

@router.post("/", response_model=LessonRead, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    module_id: UUID = Form(...),
    title: str = Form(...),
    content_type: str = Form("text"),
    content_data: Optional[str] = Form(None),
    order: int = Form(0),
    is_preview: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new lesson within a module (supports atomic file uploads).
    Requires Course Owner (Instructor) or Admin.
    """
    import sys
    print(f"BACKEND CREATE LESSON: title={title}, file_received={file is not None}", file=sys.stdout)
    if file:
        print(f"BACKEND FILE DETAILS: filename={file.filename}, size={file.size if hasattr(file, 'size') else 'unknown'}", file=sys.stdout)
    sys.stdout.flush()
    # Verify module and course ownership
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
        
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    db_lesson = Lesson(
        module_id=module_id,
        title=title,
        content_type=content_type,
        content_data=content_data,
        order=order,
        is_preview=is_preview
    )

    if file and file.filename:
        # Ensure upload directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        # Generate a temporary ID for the file name since DB ID isn't set yet
        temp_id = str(uuid.uuid4())
        safe_filename = f"{temp_id}_{file.filename.replace(' ', '_')}"
        file_location = os.path.join(UPLOAD_DIR, safe_filename)

        try:
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            db_lesson.file_url = f"/{UPLOAD_DIR}/{safe_filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
        finally:
            file.file.close()

    db.add(db_lesson)
    db.commit()
    db.refresh(db_lesson)
    return db_lesson

@router.get("/{lesson_id}", response_model=LessonRead)
def read_lesson(
    lesson_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get a specific lesson. 
    If not a preview, requires enrollment or being the instructor/admin.
    """
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    if lesson.is_preview:
        return lesson
        
    # Check for enrollment/instructor/admin
    module = db.query(Module).filter(Module.id == lesson.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    is_instructor = course.instructor_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN
    is_enrolled = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == course.id,
        Enrollment.status == EnrollmentStatus.APPROVED
    ).first() is not None
    
    if not (is_instructor or is_admin or is_enrolled):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    return lesson

@router.patch("/{lesson_id}", response_model=LessonRead)
def update_lesson(
    lesson_id: UUID, 
    lesson_in: LessonUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update a lesson. Requires Course Owner or Admin.
    """
    db_lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not db_lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    module = db.query(Module).filter(Module.id == db_lesson.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    update_data = lesson_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_lesson, field, value)
    
    db.add(db_lesson)
    db.commit()
    db.refresh(db_lesson)
    return db_lesson

@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lesson(
    lesson_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a lesson. Requires Course Owner or Admin.
    """
    db_lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not db_lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    module = db.query(Module).filter(Module.id == db_lesson.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # Optional: Delete the file from disk if it exists
    if db_lesson.file_url:
        try:
            # Remove leading slash and construct path
            file_path = db_lesson.file_url.lstrip("/")
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error deleting file {db_lesson.file_url}: {e}")

    try:
        db.delete(db_lesson)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during deletion: {str(e)}")
        
    return None

@router.post("/{lesson_id}/upload-file", response_model=LessonRead)
async def upload_lesson_file(
    lesson_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload a file to an existing lesson.
    Requires Course Owner or Admin.
    """
    print(f"BACKEND: Received file upload for lesson {lesson_id}, filename: {file.filename}")
    
    db_lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not db_lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    module = db.query(Module).filter(Module.id == db_lesson.module_id).first()
    if not module: # Should not happen if lesson exists and has module_id
        raise HTTPException(status_code=500, detail="Associated module not found")
    
    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course: # Should not happen if module exists and has course_id
        raise HTTPException(status_code=500, detail="Associated course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to upload files to this lesson."
        )
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Sanitize filename (basic example)
    safe_filename = f"{lesson_id}_{file.filename.replace(' ', '_')}"
    file_location = os.path.join(UPLOAD_DIR, safe_filename)
    
    print(f"BACKEND: Saving file to {file_location}")
    # Save the file locally
    try:
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        print(f"BACKEND: File save error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")
    finally:
        file.file.close()
            
    # Update lesson with file URL/path
    db_lesson.file_url = f"/{UPLOAD_DIR}/{safe_filename}" # Store a relative path or a full URL if using cloud storage
    print(f"BACKEND: Saved lesson file url: {db_lesson.file_url}")
    db.add(db_lesson)
    db.commit()
    db.refresh(db_lesson)
    return db_lesson

def _recalculate_course_progress(db: Session, student_id: UUID, course_id: UUID):
    total_lessons = (
        db.query(Lesson)
        .join(Module)
        .filter(Module.course_id == course_id)
        .count()
    )
    if total_lessons == 0:
        return
    module_ids = [m.id for m in db.query(Module.id).filter(Module.course_id == course_id).all()]
    completed = (
        db.query(LessonProgress)
        .filter(
            LessonProgress.student_id == student_id,
            LessonProgress.lesson_id.in_(
                db.query(Lesson.id).filter(Lesson.module_id.in_(module_ids))
            ),
        )
        .count()
    )
    progress = (completed / total_lessons) * 100
    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == student_id,
        Enrollment.course_id == course_id
    ).first()
    if enrollment:
        enrollment.progress = progress
        db.add(enrollment)
        db.commit()

from app.controllers.stats import push_user_stats

@router.post("/{lesson_id}/complete", response_model=LessonProgressResponse)
async def complete_lesson(
    lesson_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = db.query(Module).filter(Module.id == lesson.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
        
    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == course.id,
        Enrollment.is_active == True,
    ).first()
    if not enrollment and current_user.role not in (UserRole.ADMIN, UserRole.INSTRUCTOR):
        raise HTTPException(status_code=403, detail="Not enrolled in this course")
    existing = db.query(LessonProgress).filter(
        LessonProgress.student_id == current_user.id,
        LessonProgress.lesson_id == lesson_id,
    ).first()
    if existing:
        return LessonProgressResponse(lesson_id=lesson_id, is_completed=True, completed_at=existing.completed_at)
    lp = LessonProgress(student_id=current_user.id, lesson_id=lesson_id)
    db.add(lp)
    db.commit()
    db.refresh(lp)
    if enrollment:
        _recalculate_course_progress(db, current_user.id, course.id)
    
    # Push real-time stats update
    await push_user_stats(db, UUID(str(current_user.id)))
    
    return LessonProgressResponse(lesson_id=lesson_id, is_completed=True, completed_at=lp.completed_at)

@router.delete("/{lesson_id}/complete", status_code=status.HTTP_200_OK)
async def uncomplete_lesson(
    lesson_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    lp = db.query(LessonProgress).filter(
        LessonProgress.student_id == current_user.id,
        LessonProgress.lesson_id == lesson_id,
    ).first()
    if not lp:
        return LessonProgressResponse(lesson_id=lesson_id, is_completed=False)
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = db.query(Module).filter(Module.id == lesson.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    db.delete(lp)
    db.commit()
    course = db.query(Course).filter(Course.id == module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    _recalculate_course_progress(db, current_user.id, course.id)
    
    # Push real-time stats update
    await push_user_stats(db, UUID(str(current_user.id)))
    
    return LessonProgressResponse(lesson_id=lesson_id, is_completed=False)

@router.get("/{lesson_id}/progress", response_model=LessonProgressResponse)
def get_lesson_progress(
    lesson_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    lp = db.query(LessonProgress).filter(
        LessonProgress.student_id == current_user.id,
        LessonProgress.lesson_id == lesson_id,
    ).first()
    return LessonProgressResponse(
        lesson_id=lesson_id,
        is_completed=lp is not None,
        completed_at=lp.completed_at if lp else None,
    )

@router.get("/course/{course_id}/progress", response_model=List[LessonProgressResponse])
def get_course_progress(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    lesson_ids = [
        r[0] for r in db.query(Lesson.id).join(Module).filter(Module.course_id == course_id).all()
    ]
    completed_lesson_ids = {
        r[0]
        for r in db.query(LessonProgress.lesson_id).filter(
            LessonProgress.student_id == current_user.id,
            LessonProgress.lesson_id.in_(lesson_ids),
        ).all()
    }
    return [
        LessonProgressResponse(
            lesson_id=lid,
            is_completed=lid in completed_lesson_ids,
            completed_at=None,
        )
        for lid in lesson_ids
    ]
