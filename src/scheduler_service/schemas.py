from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional

class AvailabilityCreate(BaseModel):
    """Input payload for creating a time slot."""
    day_of_week: str = Field(..., description="Monday, Tuesday, etc.")
    start_time: str  = Field(..., description="HH:MM format (24h), e.g. 18:00")
    end_time: str    = Field(..., description="HH:MM format (24h), e.g. 20:00")

    @field_validator('start_time', 'end_time')
    def validate_time_format(cls, v):
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            raise ValueError("Time must be in HH:MM format (24h)")
    
    @model_validator(mode='after')
    def check_times(self):
        # Ensure Start < End
        s = datetime.strptime(self.start_time, "%H:%M")
        e = datetime.strptime(self.end_time, "%H:%M")
        if s >= e:
            raise ValueError("Start time must be before End time")
        return self

class AvailabilityOut(AvailabilityCreate):
    """Output payload including DB ID."""
    id: int
    user_id: int
    
    class Config:
        from_attributes = True

class ScheduleBlockOut(BaseModel):
    """Output payload for a generated schedule block."""
    id: UUID
    task_id: UUID
    scheduled_start: datetime
    scheduled_end: datetime
    reasoning: Optional[str]
    status: str
    
    class Config:
        from_attributes = True