from sqlalchemy.orm import Session
from uuid import UUID
from . import models, schemas


def create_task(db: Session, owner_email: str, data: schemas.TaskIn)-> models.Task:
    task = models.Task(
        owner_email = owner_email,
        name = data.name,
        deadline = data.deadline,
        weight_pct = data.weight_pct,
        difficulty = data.difficulty,
        estimated_hours = data.estimated_hours 
    )

    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def list_tasks(db: Session , owner_email: str) -> list[models.Task]:
    return db.query(models.Task).filter(models.Task.owner_email == owner_email).order_by(models.Task.deadline).all()

def get_task_owned(db: Session, owner_email: str, task_id: UUID) -> models.Task | None:
    return db.query(models.Task).filter(models.Task.id == task_id, models.Task.owner_email == owner_email).first()

def update_task(db: Session, owner_email: str, task_id: UUID, patch: schemas.TaskPatch):
    task = get_task_owned(db, owner_email, task_id)
    if not task:
        return None
    for k, v in patch.model_dump(exclude_unset=True).items():
        setattr(task, k, v)
    db.commit()
    db.refresh(task)
    return task

def delete_task(db: Session, owner_email: str, task_id: UUID) -> bool:
    task = get_task_owned(db, owner_email, task_id)
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


