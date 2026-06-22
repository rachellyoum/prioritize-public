from pydantic import BaseModel
from sqlalchemy import select, insert, delete, String, Integer, func, DateTime, UniqueConstraint, ForeignKey, Boolean
from sqlalchemy.orm import Session, mapped_column, Mapped
from sqlalchemy.exc import IntegrityError
from fastapi import Depends, HTTPException
import bcrypt  # Use bcrypt directly instead of passlib for Python 3.13 compatibility. Would not work with passlib.context 
from datetime import datetime
from typing import Optional, List


from shared.database import get_db, Base


class User(Base):
    """
    User model used by SQLAlchemy to interact with the database.
    """
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    avatar_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timezone: Mapped[str] = mapped_column(String, nullable=False, server_default="UTC")


class UserRepository:
    """
    Controls manipulation of the users table.
    """

    def __init__(self, session: Session):
        self.session = session

    async def create(self, name: str, email: str, password: str, timezone: str = "UTC") -> User:
        """
        Create a new user with the given credentials.
        
        Args:
            name: Username (must be unique)
            email: Email address (must be unique)
            password: Plain text password (will be hashed)
            
        Returns:
            User: The newly created user object
            
        Raises:
            HTTPException: If username or email already exists
        """
        # Check for duplicate username or email
        existing_user = self.session.execute(
            select(User).where((User.name == name) | (User.email == email))
        ).scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(status_code=409, detail="User with this name or email already exists")
        
        # Hash password with bcrypt (automatically handles 72-byte limit). It would throw error if I did not limit it
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
        
        # Create new user in database
        stmt = insert(User).values(
            name=name,
            email=email,
            hashed_password=hashed_password,
            timezone=timezone
        )
        self.session.execute(stmt)
        self.session.commit()
        
        # Return the created user
        return await self.get_by_name(name)

    async def delete(self, name: str) -> None:
        """
        Delete a user by username.
        
        Args:
            name: Username to delete
            
        Raises:
            HTTPException: If user not found
        """
        user = await self.get_by_name(name)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        stmt = delete(User).where(User.name == name)
        result = self.session.execute(stmt)
        self.session.commit()
        return result

    async def get_all(self) -> list[User]:
        """Get all users from the database"""
        users = self.session.scalars(select(User)).all()
        return users

    async def get_by_name(self, name: str) -> User | None:
        """Get user by username"""
        user = self.session.execute(
            select(User).where(User.name == name)
        ).scalar_one_or_none()
        return user
    
    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by id"""
        user = self.session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
        return user
    
    async def get_by_email(self, email: str) -> User | None:
        """Get user by email"""
        user = self.session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        return user

    def count_users(self) -> int:
        """Count total number of users"""
        stmt = select(func.count()).select_from(User)
        result = self.session.execute(stmt)
        return result.scalar()

    def get_users_paginated(self, limit: int = 100, offset: int = 0) -> list[User]:
        """Modify limit: int = x to change how many users to be displayed in one page"""
        stmt = select(User).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain text password against a bcrypt hash.
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Bcrypt hashed password from database
            
        Returns:
            bool: True if password matches, False otherwise
        """
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    def update(self, user_id: int, **fields):
        """
        Update a user by id. Supports updating name, email, and password.
        If 'password' is provided, it will be hashed into 'hashed_password'.
        Returns the updated User or None if the user doesn't exist.
        Lets IntegrityError bubble up (API maps it to HTTP 409).
        """
        user = self.session.get(User, user_id)
        if user is None:
            return None

        fields = {k: v for k, v in fields.items() if v is not None}

        if "password" in fields:
            hashed = bcrypt.hashpw(fields["password"].encode("utf-8"),
                               bcrypt.gensalt()).decode("utf-8")
            fields["hashed_password"] = hashed
            del fields["password"]

        for k, v in fields.items():
            setattr(user, k, v)

        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise

        self.session.refresh(user)
        return user
    
def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)

class FriendRequest(Base):
    """
    Model for pending friend requests.
    """
    __tablename__ = "friend_requests"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    to_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sent_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Prevent duplicate requests
    __table_args__ = (
        UniqueConstraint('from_user_id', 'to_user_id', name='unique_friend_request'),
    )


class Friendship(Base):
    """
    Model for accepted friendships (bidirectional).
    When a request is accepted, TWO rows are created (A->B and B->A).
    """
    __tablename__ = "friendships"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    friend_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Prevent duplicate friendships
    __table_args__ = (
        UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),
    )

class FriendshipRepository:
    """
    Controls manipulation of friend requests and friendships.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    async def send_friend_request(self, from_user_id: int, to_user_id: int) -> FriendRequest:
        """
        Send a friend request from one user to another.
        
        Raises:
            HTTPException 400: If trying to friend yourself
            HTTPException 409: If request already exists or users are already friends
            HTTPException 404: If either user doesn't exist
        """
        # Validate users exist
        from_user = self.session.execute(
            select(User).where(User.id == from_user_id)
        ).scalar_one_or_none()
        
        to_user = self.session.execute(
            select(User).where(User.id == to_user_id)
        ).scalar_one_or_none()
        
        if not from_user or not to_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Can't friend yourself
        if from_user_id == to_user_id:
            raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
        
        # Check if already friends
        existing_friendship = self.session.execute(
            select(Friendship).where(
                (Friendship.user_id == from_user_id) & (Friendship.friend_id == to_user_id)
            )
        ).scalar_one_or_none()
        
        if existing_friendship:
            raise HTTPException(status_code=409, detail="Users are already friends")
        
        # Check if request already exists (either direction)
        existing_request = self.session.execute(
            select(FriendRequest).where(
                ((FriendRequest.from_user_id == from_user_id) & (FriendRequest.to_user_id == to_user_id)) |
                ((FriendRequest.from_user_id == to_user_id) & (FriendRequest.to_user_id == from_user_id))
            )
        ).scalar_one_or_none()
        
        if existing_request:
            raise HTTPException(status_code=409, detail="Friend request already exists")
        
        # Create the request
        stmt = insert(FriendRequest).values(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            sent_timestamp=datetime.utcnow()
        )
        self.session.execute(stmt)
        self.session.commit()
        
        # Return the created request
        return self.session.execute(
            select(FriendRequest).where(
                (FriendRequest.from_user_id == from_user_id) & 
                (FriendRequest.to_user_id == to_user_id)
            )
        ).scalar_one()
    
    async def get_incoming_requests(self, user_id: int) -> list[FriendRequest]:
        """Get all pending friend requests sent TO this user."""
        requests = self.session.execute(
            select(FriendRequest).where(FriendRequest.to_user_id == user_id)
        ).scalars().all()
        return list(requests)
    
    async def get_outgoing_requests(self, user_id: int) -> list[FriendRequest]:
        """Get all pending friend requests sent FROM this user."""
        requests = self.session.execute(
            select(FriendRequest).where(FriendRequest.from_user_id == user_id)
        ).scalars().all()
        return list(requests)
    
    async def accept_friend_request(self, to_user_id: int, from_user_id: int) -> None:
        """
        Accept a friend request. Creates bidirectional friendship and deletes the request.
        
        Args:
            to_user_id: The user accepting the request (recipient)
            from_user_id: The user who sent the request
        
        Raises:
            HTTPException 404: If request not found
        """
        # Find the request
        request = self.session.execute(
            select(FriendRequest).where(
                (FriendRequest.from_user_id == from_user_id) & 
                (FriendRequest.to_user_id == to_user_id)
            )
        ).scalar_one_or_none()
        
        if not request:
            raise HTTPException(status_code=404, detail="Friend request not found")
        
        # Create bidirectional friendship (two rows)
        timestamp = datetime.utcnow()
        
        # A -> B
        stmt1 = insert(Friendship).values(
            user_id=from_user_id,
            friend_id=to_user_id,
            created_timestamp=timestamp
        )
        self.session.execute(stmt1)
        
        # B -> A
        stmt2 = insert(Friendship).values(
            user_id=to_user_id,
            friend_id=from_user_id,
            created_timestamp=timestamp
        )
        self.session.execute(stmt2)
        
        # Delete the request
        delete_stmt = delete(FriendRequest).where(FriendRequest.id == request.id)
        self.session.execute(delete_stmt)
        
        self.session.commit()
    
    async def reject_friend_request(self, to_user_id: int, from_user_id: int) -> None:
        """
        Reject a friend request (delete it).
        
        Args:
            to_user_id: The user rejecting the request (recipient)
            from_user_id: The user who sent the request
        """
        request = self.session.execute(
            select(FriendRequest).where(
                (FriendRequest.from_user_id == from_user_id) & 
                (FriendRequest.to_user_id == to_user_id)
            )
        ).scalar_one_or_none()
        
        if not request:
            raise HTTPException(status_code=404, detail="Friend request not found")
        
        stmt = delete(FriendRequest).where(FriendRequest.id == request.id)
        self.session.execute(stmt)
        self.session.commit()
    
    async def cancel_friend_request(self, from_user_id: int, to_user_id: int) -> None:
        """
        Cancel a friend request you sent.
        
        Args:
            from_user_id: The user who sent the request (and is now canceling)
            to_user_id: The recipient of the request
        """
        request = self.session.execute(
            select(FriendRequest).where(
                (FriendRequest.from_user_id == from_user_id) & 
                (FriendRequest.to_user_id == to_user_id)
            )
        ).scalar_one_or_none()
        
        if not request:
            raise HTTPException(status_code=404, detail="Friend request not found")
        
        stmt = delete(FriendRequest).where(FriendRequest.id == request.id)
        self.session.execute(stmt)
        self.session.commit()
    
    async def get_friends(self, user_id: int) -> list[User]:
        """Get all friends of a user (returns User objects)."""
        friends = self.session.execute(
            select(User).join(
                Friendship, Friendship.friend_id == User.id
            ).where(Friendship.user_id == user_id)
        ).scalars().all()
        return list(friends)
    
    async def get_friend_by_name(self, user_id: int, friend_name: str) -> User | None:
        """Get a specific friend by name."""
        friend = self.session.execute(
            select(User).join(
                Friendship, Friendship.friend_id == User.id
            ).where(
                (Friendship.user_id == user_id) & (User.name == friend_name)
            )
        ).scalar_one_or_none()
        return friend
    
    async def get_friend_by_id(self, user_id: int, friend_id: int) -> User | None:
        """Get a specific friend by ID."""
        friend = self.session.execute(
            select(User).join(
                Friendship, Friendship.friend_id == User.id
            ).where(
                (Friendship.user_id == user_id) & (User.id == friend_id)
            )
        ).scalar_one_or_none()
        return friend
    
    async def unfriend(self, user_id: int, friend_id: int) -> None:
        """
        Remove friendship (deletes both directions).
        
        Raises:
            HTTPException 404: If friendship doesn't exist
        """
        # Check if friendship exists
        friendship = self.session.execute(
            select(Friendship).where(
                (Friendship.user_id == user_id) & (Friendship.friend_id == friend_id)
            )
        ).scalar_one_or_none()
        
        if not friendship:
            raise HTTPException(status_code=404, detail="Friendship not found")
        
        # Delete both directions
        stmt1 = delete(Friendship).where(
            (Friendship.user_id == user_id) & (Friendship.friend_id == friend_id)
        )
        stmt2 = delete(Friendship).where(
            (Friendship.user_id == friend_id) & (Friendship.friend_id == user_id)
        )
        
        self.session.execute(stmt1)
        self.session.execute(stmt2)
        self.session.commit()


def get_friendship_repository(db: Session = Depends(get_db)) -> FriendshipRepository:
    return FriendshipRepository(db)

class FriendRequestCreateSchema(BaseModel):
    """Schema for creating a friend request (only needs to_user_id)."""
    to_user_id: int

    
class Schedule(Base):
    """
    Model for user schedule entries (time slots).
    """
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_busy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # True = busy, False = free
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Optional event title
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class ScheduleRepository:
    """
    Repository for schedule operations.
    Updated to link Recurring Availability with Generated Schedules.
    """

    def __init__(self, session: Session):
        self.session = session

    async def create_schedule_entry(self, user_id: int, start_time: datetime, end_time: datetime, is_busy: bool = True, title: Optional[str] = None) -> "Schedule":
        # Legacy support for manual entries
        from .user import Schedule
        schedule = Schedule(user_id=user_id, start_time=start_time, end_time=end_time, is_busy=is_busy, title=title)
        self.session.add(schedule)
        self.session.commit()
        self.session.refresh(schedule)
        return schedule

    async def get_user_schedule(self, user_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List["Schedule"]:
        # Legacy support
        from .user import Schedule
        query = select(Schedule).where(Schedule.user_id == user_id)
        if start_date: 
            query = query.where(Schedule.start_time >= start_date)
        if end_date: 
            query = query.where(Schedule.end_time <= end_date)
        return list(self.session.scalars(query).all())

    def find_common_free_time(
        self, 
        user_ids: List[int], 
        start_date: datetime, 
        end_date: datetime,
        min_duration_minutes: int = 30
    ) -> List[dict]:
        """
        Calculates mutual free time by:
        1. Fetching Availability (Recurring)
        2. Subtracting Generated Tasks (Busy)
        3. Intersecting users
        """
        # LOCAL IMPORTS to prevent Circular Import Crashes
        from scheduler_service.models import UserAvailability, GeneratedSchedule
        from scheduler_service.algorithm import expand_availability
        from user_service.models.user import User

        # 1. Helper: Get Net Free Slots for a User
        def get_net_free_slots(uid):
            # A. Get User's Timezone
            user = self.session.get(User, uid)
            tz = user.timezone if user and user.timezone else "UTC"

            # B. Get Recurring Availability
            avail_rows = self.session.scalars(
                select(UserAvailability).where(UserAvailability.user_id == uid)
            ).all()
            
            if not avail_rows:
                return []

            # C. Expand to Concrete Slots
            # We explicitly pass the user's timezone here
            concrete_slots = expand_availability(avail_rows, start_date, tz, days=7)
            
            # Filter slots within requested range
            valid_slots = []
            for slot in concrete_slots:
                s, e = slot['start'], slot['end']
                # Clip to requested range
                s = max(s, start_date)
                e = min(e, end_date)
                if s < e:
                    valid_slots.append((s, e))

            # D. Get Busy Tasks
            tasks = self.session.scalars(
                select(GeneratedSchedule).where(
                    (GeneratedSchedule.user_id == uid) &
                    (GeneratedSchedule.scheduled_end > start_date) &
                    (GeneratedSchedule.scheduled_start < end_date)
                )
            ).all()

            # E. Subtract Tasks from Slots
            net_slots = valid_slots
            for task in tasks:
                ts, te = task.scheduled_start, task.scheduled_end
                
                # Ensure timezones match for comparison
                if ts.tzinfo is None: 
                    ts = ts.replace(tzinfo=start_date.tzinfo)
                if te.tzinfo is None:
                    te = te.replace(tzinfo=start_date.tzinfo)

                temp_slots = []
                for (ss, se) in net_slots:
                    # Logic: Subtract [ts, te] from [ss, se]
                    
                    # Case 1: No overlap (Task is completely outside slot)
                    if te <= ss or ts >= se:
                        temp_slots.append((ss, se))
                        continue

                    # Case 2: Overlap
                    # Keep part before the task
                    if ss < ts:
                        temp_slots.append((ss, ts))
                    # Keep part after the task
                    if se > te:
                        temp_slots.append((te, se))
                
                net_slots = temp_slots
            
            return sorted(net_slots, key=lambda x: x[0])

        try:
            # 2. Get Slots for First User
            common_slots = get_net_free_slots(user_ids[0])

            # 3. Intersect with Subsequent Users
            for uid in user_ids[1:]:
                user_slots = get_net_free_slots(uid)
                if not user_slots:
                    return [] # One user has no free time

                new_common = []
                i, j = 0, 0
                while i < len(common_slots) and j < len(user_slots):
                    s1, e1 = common_slots[i]
                    s2, e2 = user_slots[j]

                    # Intersect
                    start = max(s1, s2)
                    end = min(e1, e2)

                    if start < end:
                        duration_min = (end - start).total_seconds() / 60
                        if duration_min >= min_duration_minutes:
                            new_common.append((start, end))

                    # Advance pointers
                    if e1 < e2:
                        i += 1
                    else:
                        j += 1
                common_slots = new_common

            # 4. Format Results
            results = []
            for s, e in common_slots:
                results.append({
                    "start": s,
                    "end": e,
                    "users": user_ids,
                    "duration_minutes": int((e - s).total_seconds() / 60)
                })

            return results

        except Exception as e:
            print(f"Error calculating mutual time: {e}")
            return [] # Fail safe: return no mutual time rather than 500 error


def get_schedule_repository(db: Session = Depends(get_db)) -> ScheduleRepository:
    return ScheduleRepository(db)
