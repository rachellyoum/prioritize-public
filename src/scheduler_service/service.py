from sqlalchemy.orm import Session
from sqlalchemy import select, delete
from . import models, schemas, algorithm
from task_service.models import Task
from user_service.models.user import User 

def add_availability(db: Session, user_id: int, data: schemas.AvailabilityCreate) -> models.UserAvailability:
    slot = models.UserAvailability(
        user_id=user_id,
        day_of_week=data.day_of_week.capitalize(),
        start_time=data.start_time,
        end_time=data.end_time
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot

def get_availability(db: Session, user_id: int) -> list[models.UserAvailability]:
    return db.scalars(
        select(models.UserAvailability)
        .where(models.UserAvailability.user_id == user_id)
        .order_by(models.UserAvailability.id)
    ).all()

def delete_availability(db: Session, user_id: int, slot_id: int):
    db.execute(
        delete(models.UserAvailability).where(
            models.UserAvailability.id == slot_id,
            models.UserAvailability.user_id == user_id
        )
    )
    db.commit()

def regenerate_schedule(db: Session, user_id: int):
    """
    1. Clear existing pending schedule.
    2. Fetch Tasks and Availability.
    3. Run Algorithm.
    4. Save new Schedule.
    """
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        return [] # Should not happen due to auth
        
    user_tz = user.timezone if hasattr(user, 'timezone') else "UTC"

    # Get tasks via email (legacy link)
    tasks = db.scalars(
        select(Task).where(Task.owner_email == user.email)
        .where(Task.status != 'completed')
    ).all()
    
    availabilities = get_availability(db, user_id)
    
    if not tasks or not availabilities:
        db.execute(delete(models.GeneratedSchedule).where(models.GeneratedSchedule.user_id == user_id))
        db.commit()
        return []
        
    # 3. Run Algorithm (Pure Logic)
    new_blocks = algorithm.generate_schedule_plan(tasks, availabilities, user_timezone=user_tz)

    # 4. Clear existing schedule for this user
    db.execute(
        delete(models.GeneratedSchedule).where(models.GeneratedSchedule.user_id == user_id)
    )
    
    # 5. Save to DB
    saved_blocks = []
    for block in new_blocks:
        db_block = models.GeneratedSchedule(
            user_id=user_id,
            task_id=block['task_id'],
            scheduled_start=block['start'],
            scheduled_end=block['end'],
            reasoning=block['reasoning'],
            status='pending'
        )
        db.add(db_block)
        saved_blocks.append(db_block)
        
    db.commit()
    return saved_blocks

# Helper to get email from ID (since Task uses email owner)
def select_user_email(db: Session, user_id: int) -> str:
    from user_service.models.user import User
    return db.scalar(select(User.email).where(User.id == user_id))

def get_current_schedule(db: Session, user_id: int):
    """Get the currently saved schedule."""
    return db.scalars(
        select(models.GeneratedSchedule)
        .where(models.GeneratedSchedule.user_id == user_id)
        .order_by(models.GeneratedSchedule.scheduled_start)
    ).all()