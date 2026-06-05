from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.models.schedule import ScheduleItem
from app.models.user import User, UserRole
from app.utils.deps import get_current_active_user
from app.utils.cache import invalidate_cache
from pydantic import BaseModel

router = APIRouter()

class ScheduleCreate(BaseModel):
    title: str
    time_str: str

@router.post("/")
def create_schedule_item(
    item: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Not permitted")
        
    db_item = ScheduleItem(
        instructor_id=current_user.id,
        title=item.title,
        time_str=item.time_str
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    
    invalidate_cache(f"dashboard_{current_user.id}")
    return {"id": str(db_item.id), "title": db_item.title, "time_str": db_item.time_str}

@router.delete("/{item_id}")
def delete_schedule_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    item = db.query(ScheduleItem).filter(ScheduleItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    if item.instructor_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not permitted")
        
    db.delete(item)
    db.commit()
    
    invalidate_cache(f"dashboard_{current_user.id}")
    return {"status": "success"}