from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.course import Course, Module
from app.models.lesson import Lesson
from app.models.lesson_progress import LessonProgress
from app.models.announcement import Announcement
from app.models.schedule import ScheduleItem
from app.models.message import Message
from app.models.message_read_state import MessageReadState
from app.models.user import User, UserRole
from app.views.stats import UserStats, DashboardData
from app.views.course import CourseRead
from app.views.announcement import AnnouncementRead
from app.views.enrollment import EnrollmentRead
from app.views.user import UserRead
from app.utils.deps import get_current_active_user
from app.utils.websockets import manager
from app.utils.limiter import limiter
from app.utils.cache import get_cached_or_compute

router = APIRouter()

@router.get("/dashboard", response_model=DashboardData)
@limiter.limit("20/minute")
def get_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Composite endpoint that returns all data needed for the dashboard in a single request.
    Reduces frontend round-trips and improves perceived performance.
    """
    def _compute_dashboard():
        # 1. Calculate Stats
        stats = calculate_user_stats(db, current_user)
        
        # 2. Get User Profile
        user_read = UserRead.model_validate(current_user)
        
        # 3. Get Relevant Announcements (Global + Course-specific)
        now = datetime.now(timezone.utc)
        enrolled_ids = [r[0] for r in db.query(Enrollment.course_id).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.status == EnrollmentStatus.APPROVED
        ).all()]
        
        instructed_ids = [r[0] for r in db.query(Course.id).filter(
            Course.instructor_id == current_user.id
        ).all()]
        
        relevant_ids = list(set(enrolled_ids + instructed_ids))
        
        if relevant_ids:
            announcements = db.query(Announcement).filter(
                (Announcement.expires_at == None) | (Announcement.expires_at > now),
                Announcement.course_id.in_(relevant_ids)
            ).order_by(Announcement.created_at.desc()).limit(10).all()
        else:
            announcements = []
        
        # 4. Get Enrolled Courses (Summary)
        user_enrollments_all = db.query(Enrollment).options(
            joinedload(Enrollment.course).joinedload(Course.instructor)
        ).filter(
            Enrollment.student_id == current_user.id
        ).all()
        user_enrollment_map = {e.course_id: e.status.value for e in user_enrollments_all}

        enrollments = [e for e in user_enrollments_all if e.status == EnrollmentStatus.APPROVED]
        
        # 5. Get Recommended/All Courses (Summary)
        # Optimized: Only fetch 10 courses for the dashboard recommendation
        db_courses = db.query(Course).options(
            joinedload(Course.instructor),
            joinedload(Course.announcements),
            joinedload(Course.modules).joinedload(Module.lessons)
        ).limit(10).all()
        
        course_results = []
        for c in db_courses:
            course_read = CourseRead.model_validate(c)
            course_read.enrollment_status = user_enrollment_map.get(c.id)
            course_read.is_enrolled = course_read.enrollment_status == 'approved'
            course_read.modules_count = len(c.modules)
            course_read.lessons_count = sum(len(m.lessons) for m in c.modules)
            course_read.announcements_count = len(c.announcements)
            course_read.instructor_name = c.instructor.full_name if c.instructor else "Unknown"
            
            # Security: Strip join code
            course_read.join_code = None
            course_results.append(course_read)

        # 6. Get Schedule Items
        schedule_items = db.query(ScheduleItem).filter(
            ScheduleItem.instructor_id == current_user.id
        ).order_by(ScheduleItem.created_at.desc()).limit(10).all()

        return DashboardData(
            user=user_read,
            stats=stats,
            courses=course_results,
            announcements=[AnnouncementRead.model_validate(a) for a in announcements],
            enrollments=[EnrollmentRead.model_validate(e) for e in enrollments],
            schedule=[{"id": str(s.id), "title": s.title, "time_str": s.time_str} for s in schedule_items]
        )


    # Calculate dashboard data in real-time to ensure accuracy
    return _compute_dashboard()

def _get_unread_count(db: Session, user_id: UUID, course_ids: List[UUID]) -> int:
    # 1. Course Messages
    unread_total = 0
    if course_ids:
        # Get all relevant read states at once
        read_states = db.query(MessageReadState).filter(
            MessageReadState.user_id == user_id,
            MessageReadState.course_id.in_(course_ids)
        ).all()
        
        read_map = {rs.course_id: rs.last_read_at for rs in read_states}
        
        for cid in course_ids:
            last_read = read_map.get(cid, datetime(1970, 1, 1, tzinfo=timezone.utc))
            unread_total += db.query(func.count(Message.id)).filter(
                Message.course_id == cid,
                Message.sender_id != user_id,
                Message.timestamp > last_read
            ).scalar() or 0
    
    # 2. Direct Messages
    peer_ids = [r[0] for r in db.query(Message.sender_id).filter(
        Message.recipient_id == user_id,
        Message.course_id == None
    ).distinct().all()]

    for peer_id in peer_ids:
        read_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == user_id,
            MessageReadState.course_id == None,
            MessageReadState.peer_user_id == peer_id,
        ).first()
        fallback_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == user_id,
            MessageReadState.course_id == None,
            MessageReadState.peer_user_id == None,
        ).first()
        last_dm_read = read_state.last_read_at if read_state else (
            fallback_state.last_read_at if fallback_state else datetime(1970, 1, 1, tzinfo=timezone.utc)
        )

        unread_total += db.query(func.count(Message.id)).filter(
            Message.sender_id == peer_id,
            Message.recipient_id == user_id,
            Message.course_id == None,
            Message.timestamp > last_dm_read
        ).scalar() or 0
        
    return unread_total

def calculate_user_stats(db: Session, user: User) -> UserStats:
    """
    Calculate comprehensive learning or teaching statistics based on user role.
    """
    now = datetime.now(timezone.utc)
    is_instructor = user.role in (UserRole.INSTRUCTOR, UserRole.ADMIN)
    
    if is_instructor:
        # --- INSTRUCTOR STATS ---
        # Get course IDs first for filtering
        course_ids = [r[0] for r in db.query(Course.id).filter(Course.instructor_id == user.id).all()]
        
        courses_created = len(course_ids)
        
        # Total students (sum of approved enrollments in my courses)
        total_students = db.query(func.count(Enrollment.id)).filter(
            Enrollment.course_id.in_(course_ids),
            Enrollment.status == EnrollmentStatus.APPROVED
        ).scalar() if course_ids else 0
        
        # Total lessons authored
        total_lessons = db.query(func.count(Lesson.id)).join(Module).filter(
            Module.course_id.in_(course_ids)
        ).scalar() if course_ids else 0
        
        # Average student progress across all my courses (SQL Aggregation)
        avg_student_progress = db.query(func.avg(Enrollment.progress)).filter(
            Enrollment.course_id.in_(course_ids)
        ).scalar() if course_ids else 0.0
        
        # Announcements posted by me (excluding expired)
        announcements_posted = db.query(func.count(Announcement.id)).filter(
            Announcement.author_id == user.id,
            (Announcement.expires_at == None) | (Announcement.expires_at > now)
        ).scalar()

        # REAL UNREAD COUNT
        unread_count = _get_unread_count(db, user.id, course_ids)

        return UserStats(
            courses_created=courses_created,
            total_students=total_students,
            total_lessons_authored=total_lessons,
            total_announcements=announcements_posted,
            average_progress=float(avg_student_progress or 0.0),
            unread_messages=unread_count
        )
        
    else:
        # --- STUDENT STATS ---
        # Fetch only necessary data for students
        enrollment_data = db.query(
            Enrollment.course_id, 
            Enrollment.progress, 
            Enrollment.is_active,
            Course.edu_level
        ).join(Course, Enrollment.course_id == Course.id).filter(
            Enrollment.student_id == user.id
        ).all()
        
        enrolled_courses = len(enrollment_data)
        active_enrollments = sum(1 for e in enrollment_data if e.is_active)
        
        avg_progress = 0.0
        course_ids = []
        level_stats = {}
        for eid, progress, is_active, level in enrollment_data:
            course_ids.append(eid)
            level_name = level.value if level else "unknown"
            level_stats[level_name] = level_stats.get(level_name, 0) + 1
        
        if enrolled_courses > 0:
            avg_progress = sum(e.progress for e in enrollment_data) / enrolled_courses
        
        completed_lessons = db.query(func.count(LessonProgress.id)).filter(
            LessonProgress.student_id == user.id
        ).scalar()
        
        total_lessons = db.query(func.count(Lesson.id)).join(Module).filter(
            Module.course_id.in_(course_ids)
        ).scalar() if course_ids else 0
        
        pending_lessons = max(0, total_lessons - completed_lessons)

        # Total relevant announcements (excluding expired)
        announcement_query = db.query(func.count(Announcement.id)).filter(
            (Announcement.expires_at == None) | (Announcement.expires_at > now)
        )
        if course_ids:
            total_announcements = announcement_query.filter(
                (Announcement.course_id.in_(course_ids)) | (Announcement.course_id == None)
            ).scalar()
        else:
            total_announcements = announcement_query.filter(
                Announcement.course_id == None
            ).scalar()

        # REAL UNREAD COUNT
        unread_count = _get_unread_count(db, user.id, course_ids)

        return UserStats(
            enrolled_courses=enrolled_courses,
            active_enrollments=active_enrollments,
            average_progress=float(avg_progress),
            completed_lessons=completed_lessons,
            pending_lessons=pending_lessons,
            total_announcements=total_announcements,
            unread_messages=unread_count,
            courses_by_level=level_stats
        )

async def push_user_stats(db: Session, user_id: UUID):
    """
    Calculate and push updated stats to a user via WebSocket, 
    and invalidate their dashboard cache to ensure the frontend fetches fresh data.
    """
    from app.utils.cache import invalidate_cache
    invalidate_cache(f"dashboard_{user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
        
    stats = calculate_user_stats(db, user)
    await manager.send_personal_message({
        "type": "stats_update",
        "data": stats.model_dump()
    }, user_id)

@router.get("/me", response_model=UserStats)
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Calculate learning statistics for the current user.
    """
    return calculate_user_stats(db, current_user)

@router.get("/instructor/reports")
async def get_instructor_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get detailed student progress reports and AI insights for instructor courses.
    """
    if current_user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        return {"error": "Unauthorized"}
        
    my_courses = db.query(Course).filter(Course.instructor_id == current_user.id).all()
    if not my_courses:
        return []
        
    course_ids = [c.id for c in my_courses]
    
    # Optimized: Fetch all relevant enrollments for all courses in a single query
    all_enrollments = db.query(Enrollment).options(
        joinedload(Enrollment.student)
    ).join(User, Enrollment.student_id == User.id).filter(
        Enrollment.course_id.in_(course_ids),
        User.role == UserRole.STUDENT,
        Enrollment.student_id != current_user.id
    ).all()
    
    # Group enrollments by course_id in memory
    from collections import defaultdict
    enrollments_by_course = defaultdict(list)
    for e in all_enrollments:
        enrollments_by_course[e.course_id].append(e)
    
    reports = []
    for course in my_courses:
        course_enrollments = enrollments_by_course[course.id]
        
        student_data = []
        total_progress = 0
        for e in course_enrollments:
            total_progress += e.progress
            student_data.append({
                "student_name": e.student.full_name,
                "email": e.student.email,
                "progress": e.progress,
                "enrolled_at": e.enrolled_at.isoformat()
            })
            
        student_count = len(course_enrollments)
        avg_progress = total_progress / student_count if student_count > 0 else 0
        
        # Rule-based AI insight
        insight = f"Course '{course.title}' has {student_count} students with an average progress of {avg_progress:.1f}%."
        if avg_progress < 30 and student_count > 0:
            insight += " Consider sending a motivational announcement to boost engagement."
        elif avg_progress > 80:
            insight += " Great job! Students are highly engaged. You might want to add more advanced modules."
            
        reports.append({
            "course_id": str(course.id),
            "course_title": course.title,
            "student_count": student_count,
            "average_progress": avg_progress,
            "students": student_data,
            "ai_insight": insight
        })
        
    return reports
