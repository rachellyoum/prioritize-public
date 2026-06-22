from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from shared.database import Base


class StudySession(Base):
    """
    Database model for study timer sessions.
    Tracks when users start/stop studying for specific tasks.
    """
    __tablename__ = "study_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False, index=True)
    task_name = Column(String, nullable=False)  # Denormalized for analytics
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)  # NULL = still running
    total_hours = Column(Float, nullable=True)  # Calculated when stopped
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    def __repr__(self):
        status = "running" if self.end_time is None else "completed"
        return f"<StudySession(user_id={self.user_id}, task={self.task_name}, status={status})>"
