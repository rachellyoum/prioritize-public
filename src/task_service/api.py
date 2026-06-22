from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timezone

from shared.database import get_db
from . import service, schemas
from .user_client import get_user_email  
from .auth_wrapper import get_user_id 

from scheduler_service.service import regenerate_schedule

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

security = HTTPBearer()

@router.post("", response_model=schemas.TaskOut, status_code=201)
def create_task(
    data: schemas.TaskIn,
    db: Session = Depends(get_db),
    user_email: str = Depends(get_user_email),
    user_id: int = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    if data.deadline <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="deadline must be in the future")
    
    task = service.create_task(db, user_email, data)

    regenerate_schedule(db, user_id)

    return task


@router.get("", response_model=list[schemas.TaskOut])
def list_my_tasks(
    db: Session = Depends(get_db),
    user_email: str = Depends(get_user_email),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    return service.list_tasks(db, user_email)


@router.patch("/{task_id}", response_model=schemas.TaskOut)
def patch_task(
    task_id: UUID,
    patch: schemas.TaskPatch,
    db: Session = Depends(get_db),
    user_email: str = Depends(get_user_email),
    user_id: int = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    task = service.update_task(db, user_email, task_id, patch)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    
    regenerate_schedule(db, user_id)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    user_email: str = Depends(get_user_email),
    user_id: int = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    ok = service.delete_task(db, user_email, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    
    regenerate_schedule(db, user_id)
    return Response(status_code=204)
