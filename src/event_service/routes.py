from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional       
from datetime import datetime     
from urllib.parse import unquote  

from shared.database import get_db
from .repository import EventRepository
from .schemas import EventCreate
from .models import Event  
import redis
import os

router = APIRouter(prefix="/v2/events", tags=["events"])

AUTH_TTL = int(os.getenv("AUTH_TTL_SECONDS", "900"))
_r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)

@router.post("/", status_code=201)
def create_event(event: EventCreate, db: Session = Depends(get_db)):
    
    when = datetime.fromisoformat(event.when) if event.when else datetime.utcnow()
    user_id = int(event.user) if event.user else None
    
    db_event = Event(
        when=when,
        source=event.source,
        type=event.type,
        payload=event.payload,
        user_id=user_id
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    
    # Track in Redis for real-time analytics
    if user_id:
        try:
            r = redis.from_url("redis://redis:6379", decode_responses=True)
            now = int(datetime.now().timestamp())
            today = datetime.now().date().isoformat()
            r.zadd(f"last_seen:{today}", {str(user_id): now})
        except Exception:
            pass  # Fail silently if Redis down
    
    return {"id": str(db_event.id), "when": db_event.when.isoformat(), "created": True}

@router.get("/", response_model=list)
def query_events(
    type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    user: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Query events with optional filters."""
    # ... rest of existing code

    """
    Query events with optional filters.
    
    Query parameters (all URL-encoded):
    - type: Filter by event type
    - source: Filter by source URL
    - before: Events before this datetime (YYYY-MM-DD HH:MM:SS)
    - after: Events after this datetime (YYYY-MM-DD HH:MM:SS)
    - user: Filter by user ID
    """
    repo = EventRepository(db)
    
    # Parse datetime strings (URL-decoded)
    before_dt = None
    after_dt = None
    
    if before:
        before_str = unquote(before)
        before_dt = datetime.fromisoformat(before_str.replace(' ', 'T'))
    
    if after:
        after_str = unquote(after)
        after_dt = datetime.fromisoformat(after_str.replace(' ', 'T'))
    
    # Parse user ID
    user_id = None
    if user:
        try:
            user_id = int(user)
        except ValueError:
            user_id = None
    
    # Query database
    events = repo.query_events(
        type=type,
        source=unquote(source) if source else None,
        before=before_dt,
        after=after_dt,
        user_id=user_id
    )
    
    # Return as JSON
    return [
        {
            "id": str(e.id),
            "when": e.when.isoformat(),
            "source": e.source,
            "type": e.type,
            "payload": e.payload,
            "user": str(e.user_id) if e.user_id else None
        }
        for e in events
    ]

