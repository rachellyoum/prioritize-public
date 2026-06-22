import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .analytics import compute_sessions
from .models import Event


@pytest.fixture
def add_events(db: Session):
    """Helper to add events."""
    def _add(user_id, times: list):
        for t in times:
            db.add(Event(
                when=t,
                source="test",
                type="test",
                payload={},
                user_id=user_id
            ))
        db.commit()
    return _add


def test_empty_events(db: Session):
    """Empty DB returns 0 sessions."""
    result = compute_sessions(db)
    assert result["count"] == 0
    assert result["stats"] == {}


def test_date_filter_on(db: Session, add_events):
    """Filter by specific date - just verify no crash."""
    day1 = datetime(2025, 10, 30, 12, 0, tzinfo=timezone.utc)
    add_events("1", [day1, day1 + timedelta(minutes=5)])
    
    result = compute_sessions(db, on=day1.date())
    assert isinstance(result, dict)
    assert "stats" in result
    assert "count" in result


def test_no_events_on_date(db: Session):
    """Query date with no events returns empty."""
    day_future = datetime(2099, 1, 1).date()
    result = compute_sessions(db, on=day_future)
    assert result["count"] == 0


def test_compute_sessions_returns_dict(db: Session):
    """Bare call returns dict with required keys."""
    result = compute_sessions(db)
    assert isinstance(result, dict)
    assert "count" in result
    assert "stats" in result
    assert "sessions" in result
