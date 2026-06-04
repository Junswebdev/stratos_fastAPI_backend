from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.models.announcement import Announcement
from app.models.course import Course
from app.models.user import User, UserRole
from app.models.enrollment import Enrollment
from app.views.announcement import AnnouncementCreate, AnnouncementRead
from app.utils.deps import get_current_active_user

router = APIRouter()

from app.controllers.stats import push_user_stats
from app.utils.websockets import manager

@router.post("/", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    announcement_in: AnnouncementCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Create an announcement. 
    Global (course_id=null) requires Admin.
    Course-specific requires Instructor/Admin.
    """
    if announcement_in.course_id is None:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Only admins can create global announcements")
    else:
        course = db.query(Course).filter(Course.id == announcement_in.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Not enough permissions")
            
    db_announcement = Announcement(
        **announcement_in.model_dump(),
        author_id=current_user.id
    )
    db.add(db_announcement)
    db.commit()
    db.refresh(db_announcement)

    # Real-time update logic
    if announcement_in.course_id:
        # Push to all enrolled students
        student_ids = [e.student_id for e in db.query(Enrollment.student_id).filter(
            Enrollment.course_id == announcement_in.course_id,
            Enrollment.is_active == True
        ).all()]
        for sid in student_ids:
            await push_user_stats(db, sid)
    else:
        # Global announcement: Push to all currently connected users
        # Note: In a large system, this would be handled via a background worker or Pub/Sub
        all_connected_users = list(manager.active_connections.keys())
        for uid in all_connected_users:
            await push_user_stats(db, uid)

    return db_announcement

@router.get("/", response_model=List[AnnouncementRead])
def read_announcements(
    course_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get announcements. 
    If course_id is provided, get course announcements.
    Otherwise, get global + enrolled course announcements.
    Filters out expired announcements.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    query = db.query(Announcement).filter(
        (Announcement.expires_at == None) | (Announcement.expires_at > now)
    )

    if course_id:
        # Verify course exists and user has access
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        
        is_instructor = course.instructor_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        is_enrolled = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == course_id,
            Enrollment.is_active == True
        ).first() is not None
        
        if not (is_instructor or is_admin or is_enrolled):
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        return query.filter(Announcement.course_id == course_id).order_by(Announcement.created_at.desc()).all()
    else:
        # Get all course IDs the user is enrolled in or instructing
        enrolled_course_ids = [e.course_id for e in db.query(Enrollment.course_id).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.is_active == True
        ).all()]
        
        instructed_course_ids = [c.id for c in db.query(Course.id).filter(
            Course.instructor_id == current_user.id
        ).all()]
        
        all_relevant_course_ids = list(set(enrolled_course_ids + instructed_course_ids))
        
        # Filter: Global (None) OR in relevant courses
        return query.filter(
            (Announcement.course_id == None) | (Announcement.course_id.in_(all_relevant_course_ids))
        ).order_by(Announcement.created_at.desc()).all()
