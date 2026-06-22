import redis
import os
from datetime import datetime

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AUTH_TTL = int(os.getenv("AUTH_TTL_SECONDS", "900"))

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def mark_user_active(user_id: int, timestamp: datetime):
    """Mark user as active in Redis with TTL."""
    key = f"user:{user_id}:last_activity"
    redis_client.setex(key, AUTH_TTL, timestamp.isoformat())

def get_active_users() -> set:
    """Get all currently active users from Redis."""
    pattern = "user:*:last_activity"
    keys = redis_client.keys(pattern)
    active_users = set()
    for key in keys:
        user_id = int(key.split(":")[1])
        active_users.add(user_id)
    return active_users
