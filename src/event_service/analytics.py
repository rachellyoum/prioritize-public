import os
import redis
from datetime import date, datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from shared.database import get_db
import statistics

router = APIRouter(prefix="/v2", tags=["analytics"])

AUTH_TTL = int(os.getenv("AUTH_TTL_SECONDS", "900"))

try:
    _r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
except Exception:
    _r = None

SESSION_SQL = """
WITH day_events AS (
  SELECT user_id, "when"
  FROM events
  WHERE user_id IS NOT NULL
  AND "when" >= DATE :day
  AND "when" < DATE :day + INTERVAL '1 day'
  ORDER BY user_id, "when"
),
marked AS (
  SELECT user_id, "when",
  CASE WHEN LAG("when") OVER (PARTITION BY user_id ORDER BY "when") IS NULL
  OR EXTRACT(EPOCH FROM ("when" - LAG("when") OVER (PARTITION BY user_id ORDER BY "when"))) > :ttl
  THEN 1 ELSE 0 END AS new_session
  FROM day_events
),
sessionized AS (
  SELECT user_id, "when",
  SUM(new_session) OVER (PARTITION BY user_id ORDER BY "when" ROWS UNBOUNDED PRECEDING) AS sid
  FROM marked
),
per_session AS (
  SELECT user_id, MIN("when") AS s, MAX("when") AS e,
  GREATEST(EXTRACT(EPOCH FROM (MAX("when") - MIN("when"))), 0) AS len
  FROM sessionized GROUP BY user_id, sid
)
SELECT
  COALESCE(MIN(len), 0) AS min_len,
  COALESCE(MAX(len), 0) AS max_len,
  COALESCE(AVG(len), 0) AS mean_len,
  COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY len), 0) AS median_len,
  COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY len), 0) AS p95_len,
  COUNT(DISTINCT user_id) AS max_active
FROM per_session;
"""

def get_currently_active_users(d: date) -> int:
    """Get active users from Redis for a specific day."""
    if not _r:
        return 0
    
    try:
        today = d.isoformat()
        now = int(datetime.now(tz=timezone.utc).timestamp())
        
        # Count users active in last AUTH_TTL seconds
        count = _r.zcount(f"last_seen:{today}", now - AUTH_TTL, "+inf")
        return int(count)
    except Exception as e:
        print(f"Redis error in get_currently_active_users: {e}")
        return 0

def get_day_stats(db: Session, d: date) -> dict:
    try:
        row = db.execute(text(SESSION_SQL), {
            "day": d.isoformat(),
            "ttl": AUTH_TTL
        }).mappings().one()
        
        # Get real-time current active users from Redis
        current_active = 0
        if _r:
            try:
                now = int(datetime.now(timezone.utc).timestamp())
                today = d.isoformat()
                current_active = int(_r.zcount(f"last_seen:{today}", now - AUTH_TTL, "+inf"))
            except Exception:
                current_active = 0
        
        max_active = int(row["max_active"]) if row["max_active"] else 0
        
        return {
            "session_length": {
                "min": float(row["min_len"]),
                "max": float(row["max_len"]),
                "mean": float(row["mean_len"]),
                "median": float(row["median_len"]),
                "p95": float(row["p95_len"]),
            },
            "active_users": {
                "current": current_active,  # Real-time from Redis
                "max": max_active  # Historical max from DB
            }
        }
    except Exception as e:
        print(f"Error: {e}")
        return {
            "session_length": {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0},
            "active_users": {"current": 0, "max": 0}
        }

@router.get("/analytics/")
def get_analytics(
    db: Session = Depends(get_db),
    on: date | None = Query(None),
    since: date | None = Query(None)
):
    """Get session and active user analytics."""
    
    if on and since:
        return {"error": "Use either 'on' or 'since', not both"}
    
    today = datetime.now(timezone.utc).date()
    
    # Bare GET → default to today
    if not on and not since:
        on = today
    
    # Case 1: Specific date
    if on:
        return get_day_stats(db, on)
    
    # Case 2: Since date — average over period
    if since:
        all_stats = []
        d = since
        
        while d <= today:
            stats = get_day_stats(db, d)
            all_stats.append(stats)
            d += timedelta(days=1)
        
        n = len(all_stats) or 1
        
        # Average all stats
        return {
            "session_length": {
                "min": sum(s["session_length"]["min"] for s in all_stats) / n,
                "max": sum(s["session_length"]["max"] for s in all_stats) / n,
                "mean": sum(s["session_length"]["mean"] for s in all_stats) / n,
                "median": sum(s["session_length"]["median"] for s in all_stats) / n,
                "p95": sum(s["session_length"]["p95"] for s in all_stats) / n,
            },
            "active_users": {
                "current": sum(s["active_users"]["current"] for s in all_stats) / n,
                "max": sum(s["active_users"]["max"] for s in all_stats) / n,
            }
        }

def compute_sessions(db: Session, on: datetime = None, since: datetime = None) -> dict:
    """Compute session statistics from events.
    
    Returns:
        {
            "count": total sessions,
            "stats": {min, max, mean, median, p95},
            "sessions": list of session lengths
        }
    """
    
    # Build WHERE clause
    where_clause = "WHERE user_id IS NOT NULL"
    params = {}
    
    if on:
        d = on if isinstance(on, date) else on.date()
        where_clause += " AND \"when\" >= DATE :day AND \"when\" < DATE :day + INTERVAL '1 day'"
        params["day"] = d.isoformat()
    elif since:
        d = since if isinstance(since, date) else since.date()
        where_clause += " AND \"when\" >= DATE :since"
        params["since"] = d.isoformat()
    
    sql = f"""
    WITH day_events AS (
      SELECT user_id, "when"
      FROM events
      {where_clause}
      ORDER BY user_id, "when"
    ),
    marked AS (
      SELECT user_id, "when",
      CASE WHEN LAG("when") OVER (PARTITION BY user_id ORDER BY "when") IS NULL
      OR EXTRACT(EPOCH FROM ("when" - LAG("when") OVER (PARTITION BY user_id ORDER BY "when"))) > :ttl
      THEN 1 ELSE 0 END AS new_session
      FROM day_events
    ),
    sessionized AS (
      SELECT user_id, "when",
      SUM(new_session) OVER (PARTITION BY user_id ORDER BY "when" ROWS UNBOUNDED PRECEDING) AS sid
      FROM marked
    ),
    per_session AS (
      SELECT user_id, MIN("when") AS s, MAX("when") AS e,
      GREATEST(EXTRACT(EPOCH FROM (MAX("when") - MIN("when"))), 0) AS len
      FROM sessionized GROUP BY user_id, sid
    )
    SELECT len FROM per_session ORDER BY len;
    """
    
    params["ttl"] = AUTH_TTL
    
    try:
        rows = db.execute(text(sql), params).fetchall()
        lengths = [float(row[0]) for row in rows]
        
        if not lengths:
            return {"count": 0, "stats": {}, "sessions": []}
        
        return {
            "count": len(lengths),
            "stats": {
                "min": min(lengths),
                "max": max(lengths),
                "mean": sum(lengths) / len(lengths),
                "median": statistics.median(lengths),
                "p95": statistics.quantiles(lengths, n=20)[18] if len(lengths) >= 20 else max(lengths)
            },
            "sessions": lengths
        }
    except Exception as e:
        print(f"Error: {e}")
        return {"count": 0, "stats": {}, "sessions": []}