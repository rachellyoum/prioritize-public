from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional, List, Any
from datetime import datetime

# --- User Schemas ---
class UserCreateSchema(BaseModel):
    name: str
    email: EmailStr
    password: str
    timezone: str = "UTC"

class UserUpdateSchema(BaseModel):
    password: Optional[str] = None
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    new_password: Optional[str] = None

class UserDeleteSchema(BaseModel):
    password: Optional[str] = None 

class UserSchema(BaseModel):
    id: int
    name: str
    email: str
    has_avatar: bool = False
    tier: int = 1
    timezone: str 

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_model(cls, user: Any) -> "UserSchema":
        """
        Create a UserSchema from a User DB model.
        Using 'Any' for user type to avoid circular imports with models.py
        """
        return cls(
            id=user.id, 
            name=user.name, 
            email=user.email, 
            has_avatar=user.avatar_path is not None, 
            tier=user.tier, 
            timezone=user.timezone
        )

# --- Authentication Schemas ---
class AuthenticationCreateSchema(BaseModel):
    name: str
    password: str
    expiry: str 

class AuthenticationResponseSchema(BaseModel):
    jwt: str

class AuthenticationDeleteSchema(BaseModel):
    jwt: str

# --- Friend Request Schemas ---
class FriendRequestCreateSchema(BaseModel):
    to_user_id: int

class FriendRequestSchema(BaseModel):
    from_user_id: int = Field(alias="from")
    to_user_id: int = Field(alias="to")
    sent_timestamp: datetime
    
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    
    @classmethod
    def from_db_model(cls, request: Any) -> "FriendRequestSchema":
        return cls(
            from_user_id=request.from_user_id,
            to_user_id=request.to_user_id,
            sent_timestamp=request.sent_timestamp
        )

# --- Schedule/Availability Schemas ---
class ScheduleEntryCreate(BaseModel):
    start_time: datetime
    end_time: datetime
    is_busy: bool = True
    title: Optional[str] = None

class ScheduleEntryOut(BaseModel):
    id: int
    start_time: datetime
    end_time: datetime
    is_busy: bool
    title: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class FindCommonTimeRequest(BaseModel):
    user_ids: List[int]
    start_date: datetime
    end_date: datetime
    min_duration_minutes: int = 30

class CommonTimeSlot(BaseModel):
    start: datetime
    end: datetime
    users: List[int]
    duration_minutes: int