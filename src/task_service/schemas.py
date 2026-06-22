from pydantic import BaseModel, condecimal, EmailStr
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime


class TaskIn(BaseModel):
    name: str
    deadline: datetime
    weight_pct: condecimal(ge=0, le=100, max_digits=5, decimal_places=2)
    difficulty: Literal["easy", "medium", "hard"]
    estimated_hours: condecimal(ge=0, max_digits=6, decimal_places=2)


class TaskOut(TaskIn):
    id: UUID
    owner_email: EmailStr
    status: str
    created_at: datetime
    updated_at: datetime


class TaskPatch(BaseModel):
    name: Optional[str] = None
    deadline: Optional[datetime] = None
    weight_pct: Optional[
        condecimal(ge=0, le=100, max_digits=5, decimal_places=2)
    ] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    estimated_hours: Optional[
        condecimal(ge=0, max_digits=6, decimal_places=2)
    ] = None
    status: Optional[str] = None
