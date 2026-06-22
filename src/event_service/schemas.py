from pydantic import BaseModel
from typing import Optional


class EventCreate(BaseModel):
    """Schema for creating an event."""
    when: str  # ISO format datetime string
    source: str
    type: str
    payload: dict
    user: Optional[str] = None  # UUID or user ID as string


class EventOut(BaseModel):
    """Schema for returning an event."""
    id: str
    when: str
    source: str
    type: str
    payload: dict
    user: Optional[str]
    
    class Config:
        from_attributes = True
