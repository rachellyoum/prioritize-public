from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from shared.database import get_db
from . import schemas, service
from task_service.auth_wrapper import get_user_id # Reuse auth logic
from .schemas import ScheduleBlockOut

router = APIRouter(
    prefix="/api/scheduler", 
    tags=["scheduler"],
    dependencies=[Depends(HTTPBearer())]
    )

@router.post("/availability", response_model=schemas.AvailabilityOut, status_code=201)
def create_availability(
    data: schemas.AvailabilityCreate,
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """Add a recurring available time slot."""
    return service.add_availability(db, user_id, data)

@router.get("/availability", response_model=list[schemas.AvailabilityOut])
def list_availability(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """List all configured availability slots."""
    return service.get_availability(db, user_id)

@router.delete("/availability/{slot_id}", status_code=204)
def remove_availability(
    slot_id: int,
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """Delete a specific availability slot."""
    service.delete_availability(db, user_id, slot_id)

@router.post("/generate", response_model=list[ScheduleBlockOut])
def generate_schedule(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """
    Triggers the smart scheduling algorithm.
    Wipes existing pending schedule and creates a new one based on current tasks/availability.
    """
    return service.regenerate_schedule(db, user_id)

@router.get("/my-schedule", response_model=list[ScheduleBlockOut])
def get_schedule(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db)
):
    """View the currently generated schedule."""
    return service.get_current_schedule(db, user_id)