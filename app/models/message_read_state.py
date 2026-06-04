from sqlalchemy import Column, ForeignKey, DateTime, Index, and_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class MessageReadState(Base):
    __tablename__ = "message_read_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True, index=True)
    peer_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    last_read_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            'ix_message_read_states_unique_dm',
            'user_id',
            'peer_user_id',
            unique=True,
            postgresql_where=and_(course_id.is_(None), peer_user_id.isnot(None)),
        ),
    )
