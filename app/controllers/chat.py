from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, WebSocketException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_
from typing import List, Optional, Tuple, Dict
from uuid import UUID
import json
import logging
import sys
import os
from datetime import datetime

from app.database import get_db
from app.utils.websockets import manager
from app.utils.deps import get_current_active_user
from app.utils.security import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from app.models.message import Message, MessageReaction
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.course import Course
from app.models.user import User, UserRole
from app.views.chat import MessageRead, MessageCreate, MessageReply

from app.utils.cloudinary_upload import upload_to_cloudinary

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
            attachment_url = message_data.get("attachment_url")
            attachment_name = message_data.get("attachment_name")
            attachment_type = message_data.get("attachment_type")
            if not content and not attachment_url:
                continue
            
            recipient_id = message_data.get("recipient_id")
            course_id = message_data.get("course_id")
            reply_to_id = message_data.get("reply_to_id")
            
            db_message = Message(
                sender_id=user_uuid,
                content=content[:2000],
                recipient_id=recipient_id,
                course_id=course_id,
                reply_to_id=reply_to_id,
                attachment_url=attachment_url,
                attachment_name=attachment_name,
                attachment_type=attachment_type,
            )
            db.add(db_message)
            db.commit()
            
            # Eagerly load relationships for the real-time payload
            db_message = db.query(Message).options(
                joinedload(Message.sender),
                joinedload(Message.reply_to).joinedload(Message.sender)
            ).filter(Message.id == db_message.id).first()
            
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


@router.post("/attachment", response_model=MessageRead)
async def send_message_attachment(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    content: str = Form(""),
    recipient_id: Optional[UUID] = Form(None),
    course_id: Optional[UUID] = Form(None),
    reply_to_id: Optional[UUID] = Form(None),
    file: UploadFile = File(...),
):
    """
    Create a chat message with a file attachment for either a direct chat or a course chat.
    """
    if (recipient_id is None and course_id is None) or (recipient_id is not None and course_id is not None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of recipient_id or course_id",
        )
    if recipient_id is not None and recipient_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot message yourself")

    original_name = os.path.basename(file.filename or "attachment").replace("\\", "_").replace("/", "_")
    file_ext = os.path.splitext(original_name)[1].lower()
    public_id = f"chat/{int(datetime.now().timestamp())}_{original_name.replace(' ', '_')}"
    file_bytes = file.file.read()
    attachment_url = upload_to_cloudinary(file_bytes, folder="chat", public_id=public_id, resource_type="auto")

    db_message = Message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        course_id=course_id,
        reply_to_id=reply_to_id,
        content=content.strip()[:2000] if content.strip() else original_name,
        attachment_url=attachment_url,
        attachment_name=original_name,
        attachment_type=file.content_type or _guess_attachment_type(file_ext),
    )
    db.add(db_message)
    db.commit()
    
    # Eagerly load relationships for the real-time payload
    db_message = db.query(Message).options(
        joinedload(Message.sender),
        joinedload(Message.reply_to).joinedload(Message.sender)
    ).filter(Message.id == db_message.id).first()

    payload = _create_message_payload(db_message, "message")
    if course_id:
        recipients = _get_course_recipients(db, course_id)
        await manager.broadcast(payload, recipients)
        for uid in recipients:
            if uid != current_user.id:
                await _push_direct_or_course_stats(db, uid)
    elif recipient_id:
        await manager.broadcast(payload, [current_user.id, recipient_id])
        await _push_direct_or_course_stats(db, recipient_id)

    return _populate_msg_read(db_message, db)

def _create_message_payload(db_message: Message, msg_type: str = "message") -> dict:
    payload = {
        "type": msg_type,
        "id": str(db_message.id),
        "sender_id": str(db_message.sender_id),
        "sender_name": db_message.sender.full_name if db_message.sender else "User",
        "sender_avatar_url": db_message.sender.avatar_url if db_message.sender else None,
        "content": db_message.content,
        "timestamp": db_message.timestamp.isoformat(),
        "course_id": str(db_message.course_id) if db_message.course_id else None,
        "recipient_id": str(db_message.recipient_id) if db_message.recipient_id else None,
        "reply_to_id": str(db_message.reply_to_id) if db_message.reply_to_id else None,
        "is_edited": db_message.is_edited.isoformat() if db_message.is_edited else None,
        "is_deleted": db_message.is_deleted.isoformat() if db_message.is_deleted else None,
        "attachment_url": db_message.attachment_url,
        "attachment_name": db_message.attachment_name,
        "attachment_type": db_message.attachment_type,
        "likes": [str(r.user_id) for r in db_message.reactions if r.reaction_type == 'like'],
        "dislikes": [str(r.user_id) for r in db_message.reactions if r.reaction_type == 'dislike'],
    }
    
    if db_message.reply_to:
        payload["reply_to"] = {
            "id": str(db_message.reply_to.id),
            "sender_id": str(db_message.reply_to.sender_id),
            "sender_name": db_message.reply_to.sender.full_name if db_message.reply_to.sender else "User",
            "sender_avatar_url": db_message.reply_to.sender.avatar_url if db_message.reply_to.sender else None,
            "content": db_message.reply_to.content if not db_message.reply_to.is_deleted else "This message was deleted"
        }
    return payload


def _guess_attachment_type(file_ext: str) -> str:
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    video_exts = {".mp4", ".mov", ".webm"}
    audio_exts = {".mp3", ".wav", ".m4a", ".aac"}
    document_exts = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv"}
    if file_ext in image_exts:
        return "image"
    if file_ext in video_exts:
        return "video"
    if file_ext in audio_exts:
        return "audio"
    if file_ext in document_exts:
        return "document"
    return "file"


def _get_course_recipients(db: Session, course_id: UUID) -> List[UUID]:
    enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id,
        Enrollment.is_active == True
    ).all()
    recipients = [e.student_id for e in enrollments]
    course = db.query(Course).filter(Course.id == course_id).first()
    if course and course.instructor_id not in recipients:
        recipients.append(course.instructor_id)
    return recipients


async def _push_direct_or_course_stats(db: Session, user_id: UUID):
    from app.controllers.stats import push_user_stats
    from app.utils.cache import invalidate_cache

    invalidate_cache(f"dashboard_{user_id}")
    await push_user_stats(db, user_id)

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
    
    my_enrollments = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id, 
        Enrollment.status == EnrollmentStatus.APPROVED
    ).all()
    course_ids.extend([e.course_id for e in my_enrollments])
    
    course_ids = list(set(course_ids))

    from app.models.message_read_state import MessageReadState

    results = []
    for cid in course_ids:
        read_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == current_user.id,
            MessageReadState.course_id == cid,
            MessageReadState.peer_user_id == None,
        ).first()
        last_read = read_state.last_read_at if read_state else datetime.min.replace(tzinfo=current_user.created_at.tzinfo)

        messages = db.query(Message).options(joinedload(Message.sender)).filter(
            Message.course_id == cid,
            Message.timestamp > last_read
        ).order_by(Message.timestamp.desc()).all()

        if messages:
            course = db.query(Course).filter(Course.id == cid).first()
            last_msg = messages[0]
            unread_count = sum(1 for m in messages if m.sender_id != current_user.id)
            results.append({
                "id": str(cid),
                "title": course.title if course else "Unknown Course",
                "last_message": last_msg.content if last_msg.content else (last_msg.attachment_name or "Attachment"),
                "last_message_time": last_msg.timestamp.isoformat(),
                "sender_name": last_msg.sender.full_name if last_msg.sender else "User",
                "course_id": str(cid),
                "recipient_id": None,
                "conversation_type": "course",
                "unread_count": unread_count,
            })

    direct_conversations = _get_direct_conversation_summaries(db, current_user)
    results.extend(direct_conversations)
    results.sort(key=lambda x: x["last_message_time"], reverse=True)
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
    
    # Use per-peer DM read state so multiple direct conversations can be tracked independently.
    read_state = db.query(MessageReadState).filter(
        MessageReadState.user_id == current_user.id,
        MessageReadState.course_id == None,
        MessageReadState.peer_user_id == other_user_id,
    ).first()
    
    if not read_state:
        read_state = MessageReadState(user_id=current_user.id, course_id=None, peer_user_id=other_user_id)
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
        joinedload(Message.reply_to).joinedload(Message.sender),
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
        joinedload(Message.reply_to).joinedload(Message.sender),
        joinedload(Message.reactions)
    ).filter(Message.course_id == course_id).order_by(Message.timestamp.asc()).all()
    return [_populate_msg_read(m, db) for m in messages]

def _populate_msg_read(m: Message, db: Session) -> MessageRead:
    msg_read = MessageRead.model_validate(m)
    msg_read.sender_name = m.sender.full_name if m.sender else "Unknown"
    msg_read.sender_avatar_url = m.sender.avatar_url if m.sender else None
    msg_read.attachment_url = m.attachment_url
    msg_read.attachment_name = m.attachment_name
    msg_read.attachment_type = m.attachment_type
    
    # Include reactions in history
    msg_read.likes = [str(r.user_id) for r in m.reactions if r.reaction_type == 'like']
    msg_read.dislikes = [str(r.user_id) for r in m.reactions if r.reaction_type == 'dislike']
    
    if m.reply_to:
        msg_read.reply_to = MessageReply(
            id=m.reply_to.id,
            sender_id=m.reply_to.sender_id,
            sender_name=m.reply_to.sender.full_name if m.reply_to.sender else "User",
            sender_avatar_url=m.reply_to.sender.avatar_url if m.reply_to.sender else None,
            content=m.reply_to.content if not m.reply_to.is_deleted else "This message was deleted"
        )
    
    if m.is_deleted:
        msg_read.content = "This message was deleted"
        
    return msg_read


def _get_direct_conversation_summaries(db: Session, current_user: User) -> List[dict]:
    from app.models.message_read_state import MessageReadState

    messages = db.query(Message).options(joinedload(Message.sender)).filter(
        Message.course_id == None,
        or_(
            Message.sender_id == current_user.id,
            Message.recipient_id == current_user.id
        )
    ).order_by(Message.timestamp.desc()).all()

    grouped: Dict[str, List[Message]] = {}
    for message in messages:
        other_user_id = message.recipient_id if message.sender_id == current_user.id else message.sender_id
        if not other_user_id:
            continue
        key = str(other_user_id)
        grouped.setdefault(key, [])
        if len(grouped[key]) < 1:
            grouped[key].append(message)

    results = []
    for peer_id_str, latest_messages in grouped.items():
        latest = latest_messages[0]
        peer_id = UUID(peer_id_str)

        read_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == current_user.id,
            MessageReadState.course_id == None,
            MessageReadState.peer_user_id == peer_id,
        ).first()
        global_dm_state = db.query(MessageReadState).filter(
            MessageReadState.user_id == current_user.id,
            MessageReadState.course_id == None,
            MessageReadState.peer_user_id == None,
        ).first()
        last_read = read_state.last_read_at if read_state else (global_dm_state.last_read_at if global_dm_state else datetime.min.replace(tzinfo=current_user.created_at.tzinfo))

        unread_count = db.query(Message).filter(
            Message.course_id == None,
            Message.sender_id == peer_id,
            Message.recipient_id == current_user.id,
            Message.timestamp > last_read,
        ).count()

        peer = db.query(User).filter(User.id == peer_id).first()
        results.append({
            "id": peer_id_str,
            "title": peer.full_name if peer and peer.full_name else (peer.email if peer else "Direct Message"),
            "last_message": latest.content if latest.content else (latest.attachment_name or "Attachment"),
            "last_message_time": latest.timestamp.isoformat(),
            "sender_name": latest.sender.full_name if latest.sender else "User",
            "course_id": None,
            "recipient_id": peer_id_str,
            "conversation_type": "direct",
            "unread_count": unread_count,
        })

    return results
