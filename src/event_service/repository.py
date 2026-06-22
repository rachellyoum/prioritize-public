from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from .models import Event
from .schemas import EventCreate
from datetime import datetime
from typing import Optional


class EventRepository:
    """Repository for Event database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_event(self, event_data: EventCreate) -> Event:
        """Create and save a new event."""
        # Parse datetime string (ISO format: "2025-10-30 05:37:14")
        when_dt = datetime.fromisoformat(event_data.when.replace(' ', 'T'))
        
        # Convert user string to int if present
        user_id = None
        if event_data.user:
            try:
                user_id = int(event_data.user)
            except ValueError:
                # If not an int, skip it (could be UUID, handle later)
                user_id = None
        
        event = Event(
            when=when_dt,
            source=event_data.source,
            type=event_data.type,
            payload=event_data.payload,
            user_id=user_id
        )
        
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event
    
    def query_events(
        self,
        type: Optional[str] = None,
        source: Optional[str] = None,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
        user_id: Optional[int] = None
    ) -> list[Event]:
        """Query events with optional filters."""
        query = select(Event)
        
        filters = []
        if type:
            filters.append(Event.type == type)
        if source:
            filters.append(Event.source == source)
        if before:
            filters.append(Event.when < before)
        if after:
            filters.append(Event.when > after)
        if user_id is not None:
            filters.append(Event.user_id == user_id)
        
        if filters:
            query = query.where(and_(*filters))
        
        # Order by newest first
        query = query.order_by(Event.when.desc())
        
        return self.db.execute(query).scalars().all()
