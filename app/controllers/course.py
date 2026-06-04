from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from sqlalchemy.exc import IntegrityError
import shutil
import os

from app.database import get_db
from app.models.course import Course, Module
from app.models.user import User, UserRole, EduLevel
from app.models.enrollment import Enrollment
from app.views.course import CourseRead, ModuleCreate, ModuleRead, ModuleUpdate
from app.utils.deps import get_current_active_user, get_current_user_optional
from app.utils.codes import generate_join_code
from app.services.ai_service import ai_service
from app.utils.cache import invalidate_cache

router = APIRouter()

UPLOAD_DIR = "uploads/courses"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Course Endpoints ---

@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
async def create_course(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    edu_level: EduLevel = Form(EduLevel.HIGHER_ED),
    instructor_id: Optional[UUID] = Form(None),
    image_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new course. Requires Instructor or Admin role.
    Generates a unique 6-digit join code and an AI-selected thumbnail if none provided.
    """
    if current_user.role not in [UserRole.INSTRUCTOR, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only instructors and admins can create courses"
        )
    
    actual_instructor_id = current_user.id if current_user.role == UserRole.INSTRUCTOR else instructor_id
    if not actual_instructor_id:
         raise HTTPException(status_code=400, detail="Instructor ID is required")

    # Generate unique join code
    join_code = generate_join_code()
    while db.query(Course).filter(Course.join_code == join_code).first():
        join_code = generate_join_code()
    
    image_url = None
    if image_file:
        file_ext = os.path.splitext(image_file.filename)[1]
        file_name = f"{join_code}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image_file.file, buffer)
        image_url = f"/static/courses/{file_name}"
    else:
        # AI Thumbnail Selection fallback
        keyword = await ai_service.generate_image_keyword(description or title)
        image_url = f"https://picsum.photos/seed/{keyword}/800/600"

    db_course = Course(
        title=title,
        description=description,
        edu_level=edu_level,
        instructor_id=actual_instructor_id,
        join_code=join_code,
        image_url=image_url
    )
    db.add(db_course)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create course")
    
    db.refresh(db_course)
    
    # Invalidate dashboard cache
    invalidate_cache(f"dashboard_{current_user.id}")
    
    return db_course

@router.get("", response_model=List[CourseRead])
def read_courses(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Retrieve all courses.
    """
    query = db.query(Course)
    
    courses = query.offset(skip).limit(limit).all()
    
    # Get all course IDs the current user is enrolled in
    enrolled_ids = {
        e.course_id for e in db.query(Enrollment.course_id).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.is_active == True
        ).all()
    }
    
    # Manually populate is_enrolled for each course and counts
    results = []
    for c in courses:
        course_read = CourseRead.model_validate(c)
        course_read.is_enrolled = c.id in enrolled_ids
        course_read.modules_count = len(c.modules)
        course_read.lessons_count = sum(len(m.lessons) for m in c.modules)
        course_read.announcements_count = len(c.announcements)
        course_read.instructor_name = c.instructor.full_name
        results.append(course_read)
        
    return results

@router.get("/{course_id}", response_model=CourseRead)
def read_course(
    course_id: UUID, 
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Get a specific course by ID (Public, but shows enrollment status if logged in).
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    course_read = CourseRead.model_validate(course)
    course_read.modules_count = len(course.modules)
    course_read.lessons_count = sum(len(m.lessons) for m in course.modules)
    course_read.announcements_count = len(course.announcements)
    course_read.instructor_name = course.instructor.full_name
    
    if current_user:
        is_enrolled = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == course_id,
            Enrollment.is_active == True
        ).first() is not None
        course_read.is_enrolled = is_enrolled
        
    return course_read

@router.patch("/{course_id}", response_model=CourseRead)
async def update_course(
    course_id: UUID,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    edu_level: Optional[EduLevel] = Form(None),
    image_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update a course. Requires Owner (Instructor) or Admin.
    """
    db_course = db.query(Course).filter(Course.id == course_id).first()
    if not db_course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if db_course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    if title: db_course.title = title
    if description: db_course.description = description
    if edu_level: db_course.edu_level = edu_level
    
    if image_file:
        file_ext = os.path.splitext(image_file.filename)[1]
        import time
        file_name = f"{db_course.join_code}_{int(time.time())}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image_file.file, buffer)
        db_course.image_url = f"/static/courses/{file_name}"
    
    db.add(db_course)
    db.commit()
    db.refresh(db_course)
    
    # Invalidate dashboard cache
    invalidate_cache(f"dashboard_{current_user.id}")
    
    return db_course

@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a course. Requires Owner (Instructor) or Admin.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
        
    instructor_id = course.instructor_id
    db.delete(course)
    db.commit()
    
    # Invalidate instructor's dashboard cache
    invalidate_cache(f"dashboard_{instructor_id}")
    
    return None

# --- Module Endpoints ---

@router.post("/{course_id}/modules", response_model=ModuleRead, status_code=status.HTTP_201_CREATED)
def create_module(
    course_id: UUID, 
    module_in: ModuleCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create a new module within a course. Requires Course Owner or Admin.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    db_module = Module(**module_in.model_dump())
    db.add(db_module)
    db.commit()
    db_module_read = ModuleRead.model_validate(db_module)
    return db_module_read

@router.patch("/modules/{module_id}", response_model=ModuleRead)
def update_module(
    module_id: UUID, 
    module_in: ModuleUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update a module. Requires Course Owner or Admin.
    """
    db_module = db.query(Module).filter(Module.id == module_id).first()
    if not db_module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    # Need to check the course owner
    course = db.query(Course).filter(Course.id == db_module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    update_data = module_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_module, field, value)
    
    db.add(db_module)
    db.commit()
    db.refresh(db_module)
    return db_module

@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(
    module_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a module. Requires Course Owner or Admin.
    """
    db_module = db.query(Module).filter(Module.id == module_id).first()
    if not db_module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    course = db.query(Course).filter(Course.id == db_module.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    db.delete(db_module)
    db.commit()
    return None
