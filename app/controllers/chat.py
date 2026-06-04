from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, WebSocketException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from uuid import UUID
import json
import logging
import sys
from datetime import datetime

from app.database import get_db
from app.utils.websockets import manager
from app.utils.deps import get_current_active_user
from app.utils.security import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from app.models.message import Message, MessageReaction
from app.models.enrollment import Enrollment
from app.models.course import Course
from app.models.user import User, UserRole
from app.views.chat import MessageRead, MessageCreate, MessageReply

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_ws_user(websocket: WebSocket, db: Session) -> User:
    """Extract and validate JWT token from WebSocket query params or Authorization header."""
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication token")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="User not found or inactive")
        return user
    except JWTError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Could not validate credentials")


async def websocket_endpoint(
    websocket: WebSocket, 
    user_id: str, 
    db: Session = Depends(get_db)
):
    """
    Main WebSocket endpoint for real-time chat.
    """
    print(f"WS CONNECTION ATTEMPT: {user_id}", file=sys.stdout)
    sys.stdout.flush()

    try:
        user_uuid = UUID(user_id)
    except (ValueError, AttributeError):
        print(f"WS FAILED: Invalid UUID {user_id}", file=sys.stdout)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    try:
        current_user = await get_ws_user(websocket, db)
    except Exception as e:
        print(f"WS AUTH FAILED: {e}", file=sys.stdout)
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if current_user.id != user_uuid and current_user.role != UserRole.ADMIN:
        print(f"WS FAILED: User mismatch. Current: {current_user.id}, Path: {user_uuid}", file=sys.stdout)
        await websocket.send_json({"error": "User mismatch"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await manager.connect(user_uuid, websocket)
    print(f"WS CONNECTED: {user_uuid}", file=sys.stdout)
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            msg_type = message_data.get("type", "message")
            
            if msg_type == "reaction":
                message_id = message_data.get("message_id")
                reaction_type = message_data.get("reaction")
                
                if not message_id or reaction_type not in ['like', 'dislike']:
                    continue
                
                db_message = db.query(Message).filter(Message.id == message_id).first()
                if not db_message:
                    continue
                
                # Persistence: Store/Toggle reaction in DB
                existing_reaction = db.query(MessageReaction).filter(
                    MessageReaction.message_id == db_message.id,
                    MessageReaction.user_id == current_user.id
                ).first()

                if existing_reaction:
                    if existing_reaction.reaction_type == reaction_type:
                        db.delete(existing_reaction)
                    else:
                        existing_reaction.reaction_type = reaction_type
                else:
                    new_reaction = MessageReaction(
                        message_id=db_message.id,
                        user_id=current_user.id,
                        reaction_type=reaction_type
                    )
                    db.add(new_reaction)
                
                db.commit()
                db.refresh(db_message)
                
                broadcast_payload = _create_message_payload(db_message, "reaction")
                
                if db_message.course_id:
                    enrollments = db.query(Enrollment).filter(Enrollment.course_id == db_message.course_id).all()
                    u_ids = [e.student_id for e in enrollments]
                    course = db.query(Course).filter(Course.id == db_message.course_id).first()
                    if course and course.instructor_id not in u_ids:
                        u_ids.append(course.instructor_id)
                    await manager.broadcast(broadcast_payload, u_ids)
                elif db_message.recipient_id:
                    # Broadcast to both participants for DMs
                    await manager.broadcast(broadcast_payload, [db_message.sender_id, db_message.recipient_id])
                
                continue

            elif msg_type == "edit":
                message_id = message_data.get("message_id")
                new_content = message_data.get("content", "").strip()
                if not message_id or not new_content:
                    continue
                
                db_message = db.query(Message).filter(Message.id == message_id).first()
                if not db_message or db_message.sender_id != current_user.id:
                    continue
                
                db_message.content = new_content
                db_message.is_edited = datetime.now()
                db.commit()
                db.refresh(db_message)
                
                broadcast_payload = _create_message_payload(db_message, "edit")
                if db_message.course_id:
                    enrollments = db.query(Enrollment).filter(Enrollment.course_id == db_message.course_id).all()
                    u_ids = [e.student_id for e in enrollments]
                    course = db.query(Course).filter(Course.id == db_message.course_id).first()
                    if course:
                        u_ids.append(course.instructor_id)
                        await manager.broadcast(broadcast_payload, u_ids)
                continue

            elif msg_type == "delete":
                message_id = message_data.get("message_id")
                if not message_id:
                    continue
                
                db_message = db.query(Message).filter(Message.id == message_id).first()
                if not db_message or (db_message.sender_id != current_user.id and current_user.role != UserRole.ADMIN):
                    continue
                
                db_message.is_deleted = datetime.now()
                db_message.content = "This message was deleted"
                db.commit()
                db.refresh(db_message)
                
                broadcast_payload = _create_message_payload(db_message, "delete")
                if db_message.course_id:
                    enrollments = db.query(Enrollment).filter(Enrollment.course_id == db_message.course_id).all()
                    u_ids = [e.student_id for e in enrollments]
                    course = db.query(Course).filter(Course.id == db_message.course_id).first()
                    if course:
                        u_ids.append(course.instructor_id)
                        await manager.broadcast(broadcast_payload, u_ids)
                continue

            # Standard message or Reply
            content = message_data.get("content", "").strip()
            if not content:
                continue
            
            recipient_id = message_data.get("recipient_id")
            course_id = message_data.get("course_id")
            reply_to_id = message_data.get("reply_to_id")
            
            db_message = Message(
                sender_id=user_uuid,
                content=content[:2000],
                recipient_id=recipient_id,
                course_id=course_id,
                reply_to_id=reply_to_id
            )
            db.add(db_message)
            db.commit()
            db.refresh(db_message)
            
            broadcast_payload = _create_message_payload(db_message, "message")
            from app.controllers.stats import push_user_stats
            from app.utils.cache import invalidate_cache
            
            if db_message.course_id:
                enrollments = db.query(Enrollment).filter(
                    Enrollment.course_id == db_message.course_id,
                    Enrollment.is_active == True
                ).all()
                user_ids = [e.student_id for e in enrollments]
                course = db.query(Course).filter(Course.id == db_message.course_id).first()
                if course and course.instructor_id not in user_ids:
                    user_ids.append(course.instructor_id)
                
                await manager.broadcast(broadcast_payload, user_ids)
                
                # Push stats update to everyone in the course to refresh unread counts
                for uid in user_ids:
                    if uid != user_uuid: # Don't push to sender
                        invalidate_cache(f"dashboard_{uid}")
                        await push_user_stats(db, UUID(str(uid)))
            
            elif db_message.recipient_id:
                # Direct Message logic
                await manager.broadcast(broadcast_payload, [db_message.sender_id, db_message.recipient_id])
                
                # Push notification and stats update to recipient
                recipient_id = db_message.recipient_id
                invalidate_cache(f"dashboard_{recipient_id}")
                await push_user_stats(db, recipient_id)
                
    except WebSocketDisconnect:
        manager.disconnect(user_uuid, websocket)
    except Exception as e:
        logger.exception(f"WebSocket error for user {user_id}: {e}")
        manager.disconnect(user_uuid, websocket)

def _create_message_payload(db_message: Message, msg_type: str = "message") -> dict:
    payload = {
        "type": msg_type,
        "id": str(db_message.id),
        "sender_id": str(db_message.sender_id),
        "sender_name": db_message.sender.full_name if db_message.sender else "User",
        "content": db_message.content,
        "timestamp": db_message.timestamp.isoformat(),
        "course_id": str(db_message.course_id) if db_message.course_id else None,
        "recipient_id": str(db_message.recipient_id) if db_message.recipient_id else None,
        "reply_to_id": str(db_message.reply_to_id) if db_message.reply_to_id else None,
        "is_edited": db_message.is_edited.isoformat() if db_message.is_edited else None,
        "is_deleted": db_message.is_deleted.isoformat() if db_message.is_deleted else None,
        "likes": [str(r.user_id) for r in db_message.reactions if r.reaction_type == 'like'],
        "dislikes": [str(r.user_id) for r in db_message.reactions if r.reaction_type == 'dislike'],
    }
    
    if db_message.reply_to:
        payload["reply_to"] = {
            "id": str(db_message.reply_to.id),
            "sender_id": str(db_message.reply_to.sender_id),
            "sender_name": db_message.reply_to.sender.full_name if db_message.reply_to.sender else "User",
            "content": db_message.reply_to.content if not db_message.reply_to.is_deleted else "This message was deleted"
        }
    return payload

@router.get("/recent")
def get_recent_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Get a summary of conversations that have UNREAD messages.
    Clicking these will mark them as read and they will 'vanish' from this list.
    """
    course_ids = []
    if current_user.role in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        my_taught = db.query(Course).filter(Course.instructor_id == current_user.id).all()
        course_ids.extend([c.id for c in my_taught])
    
    my_enrollments = db.query(Enrollment).filter(Enrollment.student_id == current_user.id, Enrollment.is_active == True).all()
    course_ids.extend([e.course_id for e in my_enrollments])
    
    course_ids = list(set(course_ids))
    
    from app.models.message_read_state import MessageReadState
    results = []
    for cid in course_ids:
        # Get last read time
        read_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == current_user.id,
            MessageReadState.course_id == cid
        ).first()
        last_read = read_state.last_read_at if read_state else datetime.min.replace(tzinfo=current_user.created_at.tzinfo)

        # Find messages after last_read
        unread_msgs = db.query(Message).filter(
            Message.course_id == cid,
            Message.sender_id != current_user.id,
            Message.timestamp > last_read
        ).order_by(Message.timestamp.desc()).all()

        if unread_msgs:
            course = db.query(Course).filter(Course.id == cid).first()
            last_msg = unread_msgs[0]
            results.append({
                "id": str(cid),
                "title": course.title if course else "Unknown Course",
                "last_message": last_msg.content,
                "last_message_time": last_msg.timestamp.isoformat(),
                "sender_name": last_msg.sender.full_name if last_msg.sender else "User",
                "course_id": str(cid),
                "unread_count": len(unread_msgs)
            })
            
    results.sort(key=lambda x: x['last_message_time'], reverse=True)
    return results

@router.post("/mark_read/{course_id}")
async def mark_course_as_read(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Mark all messages in a course as read for the current user.
    """
    from app.models.message_read_state import MessageReadState
    from app.controllers.stats import push_user_stats
    from app.utils.cache import invalidate_cache
    
    read_state = db.query(MessageReadState).filter(
        MessageReadState.user_id == current_user.id,
        MessageReadState.course_id == course_id
    ).first()
    
    if not read_state:
        read_state = MessageReadState(user_id=current_user.id, course_id=course_id)
        db.add(read_state)
    else:
        read_state.last_read_at = datetime.now()
        
    db.commit()
    
    # Push updated stats (unread count should decrease)
    invalidate_cache(f"dashboard_{current_user.id}")
    await push_user_stats(db, UUID(str(current_user.id)))
    return {"status": "success"}

@router.post("/mark_direct_read/{other_user_id}")
async def mark_direct_as_read(
    other_user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Mark all direct messages from a specific user as read.
    """
    from app.models.message_read_state import MessageReadState
    from app.controllers.stats import push_user_stats
    from app.utils.cache import invalidate_cache
    
    # Simple logic: use MessageReadState with course_id=None as a global DM read marker
    read_state = db.query(MessageReadState).filter(
        MessageReadState.user_id == current_user.id,
        MessageReadState.course_id == None
    ).first()
    
    if not read_state:
        read_state = MessageReadState(user_id=current_user.id, course_id=None)
        db.add(read_state)
    else:
        read_state.last_read_at = datetime.now()
        
    db.commit()
    
    invalidate_cache(f"dashboard_{current_user.id}")
    await push_user_stats(db, UUID(str(current_user.id)))
    return {"status": "success"}

@router.get("/history/direct/{other_user_id}", response_model=List[MessageRead])
def get_direct_message_history(
    other_user_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    messages = db.query(Message).options(
        joinedload(Message.sender),
        joinedload(Message.reply_to),
        joinedload(Message.reactions)
    ).filter(
        ((Message.sender_id == current_user.id) & (Message.recipient_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.recipient_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    
    return [_populate_msg_read(m, db) for m in messages]

@router.get("/history/course/{course_id}", response_model=List[MessageRead])
def get_course_chat_history(
    course_id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    messages = db.query(Message).options(
        joinedload(Message.sender),
        joinedload(Message.reply_to),
        joinedload(Message.reactions)
    ).filter(Message.course_id == course_id).order_by(Message.timestamp.asc()).all()
    return [_populate_msg_read(m, db) for m in messages]

def _populate_msg_read(m: Message, db: Session) -> MessageRead:
    msg_read = MessageRead.model_validate(m)
    msg_read.sender_name = m.sender.full_name if m.sender else "Unknown"
    
    # Include reactions in history
    msg_read.likes = [str(r.user_id) for r in m.reactions if r.reaction_type == 'like']
    msg_read.dislikes = [str(r.user_id) for r in m.reactions if r.reaction_type == 'dislike']
    
    if m.reply_to:
        msg_read.reply_to = MessageReply(
            id=m.reply_to.id,
            sender_id=m.reply_to.sender_id,
            sender_name=m.reply_to.sender.full_name if m.reply_to.sender else "User",
            content=m.reply_to.content if not m.reply_to.is_deleted else "This message was deleted"
        )
    
    if m.is_deleted:
        msg_read.content = "This message was deleted"
        
    return msg_read
