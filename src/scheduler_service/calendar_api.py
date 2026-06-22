# src/scheduler_service/calendar_api.py

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.database import get_db
from task_service.auth_wrapper import get_user_id
from .calendar_export import (
    get_calendar_blocks_for_user,
    blocks_to_ics,
    push_blocks_to_google_calendar,
)

router = APIRouter(
    prefix="/api/calendar",
    tags=["calendar"],
    dependencies=[Depends(HTTPBearer())],
)


# --------- Schemas --------- #

class GoogleExportRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None
    timezone: str = "America/Vancouver"
    calendar_id: str = "primary"


class GoogleExportResult(BaseModel):
    created_events: int


# --------- Endpoints --------- #

@router.get(
    "/export/ics",
    responses={200: {"content": {"text/calendar": {}}}},
)
def export_schedule_as_ics(
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db),
):
    """
    Download the current user's generated schedule as an .ics file.
    """
    blocks = get_calendar_blocks_for_user(db, user_id)
    if not blocks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule available to export.",
        )

    ics_data = blocks_to_ics(blocks)
    headers = {
        "Content-Disposition": 'attachment; filename="smart_scheduler_schedule.ics"'
    }
    return Response(content=ics_data, media_type="text/calendar", headers=headers)


@router.post("/export/google", response_model=GoogleExportResult)
def export_schedule_to_google(
    payload: GoogleExportRequest,
    user_id: int = Depends(get_user_id),
    db: Session = Depends(get_db),
):
    """
    Push the user's generated schedule to Google Calendar.
    Frontend must supply a valid Google OAuth access token.
    """
    blocks = get_calendar_blocks_for_user(db, user_id)
    if not blocks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule available to export.",
        )

    created = push_blocks_to_google_calendar(
        blocks=blocks,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        timezone_str=payload.timezone,
        calendar_id=payload.calendar_id,
    )

    return GoogleExportResult(created_events=created)