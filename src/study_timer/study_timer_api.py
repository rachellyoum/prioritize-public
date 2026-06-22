from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID

from shared.database import get_db
from study_timer.models import StudySession
from task_service.auth_wrapper import get_user_id
from task_service.models import Task
from user_service.models.user import User

router = APIRouter(prefix="/api/study-timer", tags=["study-timer"], dependencies=[Depends(HTTPBearer())])


class StudySessionStart(BaseModel):
    task_id: UUID

class StudySessionResponse(BaseModel):
    session_id: int
    task_id: UUID
    task_name: str
    start_time: datetime
    status: str


@router.post("/sessions/start", response_model=StudySessionResponse)
async def start_study_session(
    session_data: StudySessionStart,
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """
    Start a new study session for a task.
    
    Security: Uses JWT to get authenticated user_id
    Validation: Ensures task exists and belongs to user
    
    Returns:
        Session ID and start time
    """
    # Get User Email (because Task uses email, not ID)
    current_user = db.query(User).filter(User.id == user_id).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if user already has an active session
    active_session = db.query(StudySession).filter(
        and_(
            StudySession.user_id == user_id,
            StudySession.end_time.is_(None)
        )
    ).first()
    
    if active_session:
        raise HTTPException(
            status_code=400,
            detail=f"Session already active for task '{active_session.task_name}'. Please stop it first."
        )
    
    # Validate task exists and belongs to user
    task = db.query(Task).filter(
        and_(
            Task.id == session_data.task_id,
            Task.owner_email == current_user.email
        )
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=404,
            detail="Task not found or does not belong to you"
        )
    
    # Create new session
    new_session = StudySession(
        user_id=user_id,
        task_id=session_data.task_id,
        task_name=task.name,
        start_time=datetime.now(timezone.utc)
    )
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    return {
        "session_id": new_session.id,
        "task_id": new_session.task_id,
        "task_name": new_session.task_name,
        "start_time": new_session.start_time,
        "status": "running"
    }


@router.post("/sessions/stop")
async def stop_study_session(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """
    Stop the currently active study session.
    
    Returns:
        Total logged hours
    """
    # Find active session
    active_session = db.query(StudySession).filter(
        and_(
            StudySession.user_id == user_id,
            StudySession.end_time.is_(None)
        )
    ).first()
    
    if not active_session:
        raise HTTPException(status_code=404, detail="No active session found")
    
    # Calculate duration
    end_time = datetime.now(timezone.utc)
    duration_seconds = (end_time - active_session.start_time).total_seconds()
    total_hours = duration_seconds / 3600
    
    # Update session
    active_session.end_time = end_time
    active_session.total_hours = total_hours
    
    db.commit()
    db.refresh(active_session)
    
    return {
        "session_id": active_session.id,
        "task_id": str(active_session.task_id),
        "task_name": active_session.task_name,
        "total_hours": round(total_hours, 2),
        "message": f"Logged {total_hours:.2f} hours for task '{active_session.task_name}'"
    }


@router.get("/sessions/active")
async def get_active_session(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """
    Get the currently active session (if any).
    
    Returns:
        Session details with real-time elapsed time
    """
    active_session = db.query(StudySession).filter(
        and_(
            StudySession.user_id == user_id,
            StudySession.end_time.is_(None)
        )
    ).first()
    
    if not active_session:
        return {"active_session": None}
    
    # Calculate real-time elapsed time
    elapsed_seconds = (datetime.now(timezone.utc) - active_session.start_time).total_seconds()
    
    return {
        "active_session": {
            "session_id": active_session.id,
            "task_id": str(active_session.task_id),
            "task_name": active_session.task_name,
            "start_time": active_session.start_time.isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "elapsed_hours": round(elapsed_seconds / 3600, 2),
            "status": "running"
        }
    }


@router.get("/analytics")
async def get_study_analytics(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """
    Study analytics dashboard showing completed sessions and time breakdowns.
    
    Dashboard shows:
    - Total sessions completed
    - Hours logged per task
    - Total hours today
    - Total hours past 7 days
    - Total hours past 30 days
    - Total hours all time
    - Daily breakdown for the past 30 days
    
    Returns:
        Analytics dashboard with study time breakdowns
    """
    # Get all completed sessions for this user
    completed_sessions = db.query(StudySession).filter(
        and_(
            StudySession.user_id == user_id,
            StudySession.end_time.isnot(None)
        )
    ).all()
    
    # Calculate time boundaries
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Aggregate data
    hours_by_task = defaultdict(float)
    hours_by_date = defaultdict(float)
    total_hours_today = 0.0
    total_hours_7_days = 0.0
    total_hours_30_days = 0.0
    total_hours_all_time = 0.0
    
    for session in completed_sessions:
        task_name = session.task_name
        hours = session.total_hours or 0.0
        end_time = session.end_time
        
        # Add to task total
        hours_by_task[task_name] += hours
        
        # Add to all time
        total_hours_all_time += hours
        
        # Add to time period totals
        if end_time >= today_start:
            total_hours_today += hours
        if end_time >= week_ago:
            total_hours_7_days += hours
        if end_time >= month_ago:
            total_hours_30_days += hours
            # Add to daily breakdown (last 30 days only)
            date_key = end_time.date().isoformat()
            hours_by_date[date_key] += hours
    
    # Format task breakdown
    tasks_breakdown = [
        {
            "task_name": task,
            "total_hours": round(hours, 2)
        }
        for task, hours in sorted(hours_by_task.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # Format daily breakdown
    daily_breakdown = [
        {
            "date": date,
            "hours": round(hours, 2)
        }
        for date, hours in sorted(hours_by_date.items())
    ]
    
    return {
        "user_id": user_id,
        "total_sessions": len(completed_sessions),
        "tasks": tasks_breakdown,
        "summary": {
            "today": round(total_hours_today, 2),
            "past_7_days": round(total_hours_7_days, 2),
            "past_30_days": round(total_hours_30_days, 2),
            "all_time": round(total_hours_all_time, 2)
        },
        "daily_breakdown": daily_breakdown
    }

