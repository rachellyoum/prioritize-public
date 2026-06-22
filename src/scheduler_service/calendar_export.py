from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from scheduler_service.models import GeneratedSchedule
from task_service.models import Task

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# ---------- Core data model used for export ----------

@dataclass
class CalendarBlock:
    task_id: str
    title: str
    start: datetime
    end: datetime
    description: str
    priority_reason: str


# ---------- Fetch schedule blocks for a user ----------

def get_calendar_blocks_for_user(db: Session, user_id: int) -> List[CalendarBlock]:
    """
    Load the user's current schedule and convert it into CalendarBlock objects
    ready for .ics export or Google Calendar.
    """
    stmt = (
        select(GeneratedSchedule, Task.name, Task.difficulty)
        .join(Task, Task.id == GeneratedSchedule.task_id)
        .where(GeneratedSchedule.user_id == user_id)
        .order_by(GeneratedSchedule.scheduled_start)
    )
    rows = db.execute(stmt).all()
    blocks: List[CalendarBlock] = []

    for sched, task_name, difficulty in rows:
        # scheduled_start/end are already timezone-aware according to your model
        start: datetime = sched.scheduled_start
        end: datetime = sched.scheduled_end

        desc = f"{task_name} (difficulty {difficulty})"

        blocks.append(
            CalendarBlock(
                task_id=str(sched.task_id),
                title=task_name,
                start=start,
                end=end,
                description=desc,
                priority_reason=sched.reasoning or "",
            )
        )

    return blocks


# ---------- iCal (.ics) generation ----------

def _format_dt_utc(dt: datetime) -> str:
    """
    Format datetime as UTC ical format: 20251124T180000Z
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def blocks_to_ics(blocks: Iterable[CalendarBlock]) -> str:
    """
    Convert CalendarBlock list into an iCal (.ics) string.
    """
    now_utc = datetime.now(timezone.utc)
    dtstamp = _format_dt_utc(now_utc)

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Smart Scheduler//EN",
        "X-WR-CALNAME:Smart Scheduler",
    ]

    for b in blocks:
        # NOTE: UID must be globally unique, but deterministic is fine here
        uid = f"{b.task_id}-{_format_dt_utc(b.start)}@smartscheduler"
        summary = b.title.replace("\n", " ")
        desc = (
            f"{b.description}\n\nPriority reasoning: {b.priority_reason}"
        ).replace("\n", "\\n")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{_format_dt_utc(b.start)}",
                f"DTEND:{_format_dt_utc(b.end)}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------- Google Calendar export helper ----------

def push_blocks_to_google_calendar(
    blocks: Iterable[CalendarBlock],
    access_token: str,
    timezone_str: str = "America/Vancouver",
    calendar_id: str = "primary",
    refresh_token: str | None = None,
    token_uri: str = "https://oauth2.googleapis.com/token",
    client_id: str | None = None,
    client_secret: str | None = None,
) -> int:
    """
    Create events in the user's Google Calendar using an OAuth access token.
    Frontend is responsible for obtaining the token; backend just uses it.
    """
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )

    service = build("calendar", "v3", credentials=creds)

    created = 0
    for b in blocks:
        event = {
            "summary": b.title,
            "description": f"{b.description}\n\nPriority reasoning: {b.priority_reason}",
            "start": {"dateTime": b.start.isoformat(), "timeZone": timezone_str},
            "end": {"dateTime": b.end.isoformat(), "timeZone": timezone_str},
        }
        service.events().insert(calendarId=calendar_id, body=event).execute()
        created += 1

    return created