from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List
from uuid import UUID

from app.database import get_db
from app.models.enrollment import Enrollment
from app.models.course import Course
from app.models.user import User, UserRole
from app.views.enrollment import EnrollmentCreate, EnrollmentRead, EnrollmentUpdate
from app.utils.deps import get_current_active_user
from app.controllers.stats import push_user_stats
from app.utils.cache import invalidate_cache

router = APIRouter()

@router.post("/", response_model=EnrollmentRead, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    enrollment_in: EnrollmentCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Enroll a student in a course. 
    Students can enroll themselves. Admins can enroll anyone.
    """
    student_id = enrollment_in.student_id or current_user.id
    
    # Permission check: if trying to enroll someone else, must be admin
    if student_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # Verify course exists
    course = db.query(Course).filter(Course.id == enrollment_in.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    # Check for existing enrollment
    existing = db.query(Enrollment).filter(
        Enrollment.student_id == student_id,
        Enrollment.course_id == enrollment_in.course_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Student is already enrolled in this course")
    
    db_enrollment = Enrollment(
        student_id=student_id,
        course_id=enrollment_in.course_id
    )
    db.add(db_enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Student is already enrolled in this course")
    
    # Reload with joined course for the response
    db_enrollment = db.query(Enrollment).options(
        joinedload(Enrollment.course).joinedload(Course.instructor)
    ).filter(Enrollment.id == db_enrollment.id).first()
    
    # Invalidate dashboard cache for the student
    invalidate_cache(f"dashboard_{student_id}")
    
    # Push real-time stats update
    await push_user_stats(db, UUID(str(student_id)))
    
    return db_enrollment

@router.post("/join/{join_code}", response_model=EnrollmentRead, status_code=status.HTTP_201_CREATED)
async def enroll_by_code(
    join_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Enroll a student in a course using a 6-digit join code.
    """
    # Find course by join code
    course = db.query(Course).filter(Course.join_code == join_code.upper()).first()
    if not course:
        raise HTTPException(status_code=404, detail="Invalid join code")
    
    # Check for existing enrollment
    existing = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == course.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already enrolled in this course")
    
    db_enrollment = Enrollment(
        student_id=current_user.id,
        course_id=course.id
    )
    db.add(db_enrollment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Already enrolled in this course")
    
    # Reload with joined course for the response
    db_enrollment = db.query(Enrollment).options(
        joinedload(Enrollment.course).joinedload(Course.instructor)
    ).filter(Enrollment.id == db_enrollment.id).first()
    
    # Invalidate dashboard cache for the student
    invalidate_cache(f"dashboard_{current_user.id}")
    
    # Push real-time stats update
    await push_user_stats(db, UUID(str(current_user.id)))
    
    return db_enrollment

@router.get("/me", response_model=List[EnrollmentRead])
def read_my_enrollments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all enrollments for the currently logged-in student.
    """
    return db.query(Enrollment).options(
        joinedload(Enrollment.course).joinedload(Course.instructor)
    ).filter(Enrollment.student_id == current_user.id).all()

@router.get("/{enrollment_id}", response_model=EnrollmentRead)
def read_enrollment(
    enrollment_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get a specific enrollment by ID.
    """
    enrollment = db.query(Enrollment).options(
        joinedload(Enrollment.course).joinedload(Course.instructor)
    ).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    # Permission: student, course instructor, or admin
    if (enrollment.student_id != current_user.id and 
        enrollment.course.instructor_id != current_user.id and 
        current_user.role != UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    return enrollment

@router.patch("/{enrollment_id}", response_model=EnrollmentRead)
async def update_enrollment(
    enrollment_id: UUID, 
    enrollment_in: EnrollmentUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update enrollment progress or status.
    Students can update their own progress only.
    Instructors can update progress for their course students.
    Admins can update any enrollment (including is_active).
    """
    db_enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not db_enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    # Get the course to check instructor
    course = db.query(Course).filter(Course.id == db_enrollment.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    # Determine permissions
    is_own_enrollment = db_enrollment.student_id == current_user.id
    is_instructor = course.instructor_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN
    
    update_data = enrollment_in.model_dump(exclude_unset=True)
    
    # Restrict who can modify is_active (only admin/course instructor)
    if 'is_active' in update_data and not (is_admin or is_instructor):
        raise HTTPException(status_code=403, detail="Cannot modify enrollment status")
    
    # Students can only update progress on their own enrollment
    if not is_admin and not is_instructor:
        if not is_own_enrollment:
            raise HTTPException(status_code=403, detail="Can only update your own enrollment")
        # Students can only modify progress, nothing else
        allowed_fields = {'progress'}
        for field in list(update_data.keys()):
            if field not in allowed_fields:
                update_data.pop(field)
    
    for field, value in update_data.items():
        setattr(db_enrollment, field, value)
    
    db.add(db_enrollment)
    db.commit()
    db.refresh(db_enrollment)
    
    # Push real-time stats update
    await push_user_stats(db, UUID(str(db_enrollment.student_id)))
    
    return db_enrollment

@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_enrollment(
    enrollment_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Unenroll a student from a course.
    """
    db_enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not db_enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    if db_enrollment.student_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    student_id = db_enrollment.student_id
    db.delete(db_enrollment)
    db.commit()
    
    # Push real-time stats update
    if student_id:
        await push_user_stats(db, UUID(str(student_id)))
    
    return None
