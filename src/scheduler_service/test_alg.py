from datetime import datetime, timezone, timedelta
from .algorithm import calculate_priority, expand_availability#, generate_schedule_plan

# Mock object to simulate a Task model
class MockTask:
    def __init__(self, id, deadline, weight, difficulty, hours, status="open"):
        self.id = id
        self.deadline = deadline
        self.weight_pct = weight
        self.difficulty = difficulty
        self.estimated_hours = hours
        self.status = status

# Mock object for Availability
class MockSlot:
    def __init__(self, day, start, end):
        self.day_of_week = day
        self.start_time = start
        self.end_time = end

def test_priority_score():
    """Test that High Weight + High Difficulty = High Score."""
    now = datetime(2025, 11, 24, 12, 0, tzinfo=timezone.utc)
    
    # Task due in 10 hours
    deadline = now + timedelta(hours=10)
    
    # Hard Task (Diff 2.0, Weight 50)
    t1 = MockTask(1, deadline, 50, "hard", 2)
    score1 = calculate_priority(t1, now)
    
    # Easy Task (Diff 1.0, Weight 10)
    t2 = MockTask(2, deadline, 10, "easy", 2)
    score2 = calculate_priority(t2, now)
    
    # Hard task should have roughly 10x score (50*2 vs 10*1)
    assert score1 > score2
    assert score1 == (50 * 2.0) / 10.0  # 10.0

def test_timezone_expansion_vancouver():
    """
    CRITICAL: Test that 6 PM Vancouver becomes UTC 2 AM (next day).
    """
    # Reference: Nov 24 2025 is a Monday
    start_date = datetime(2025, 11, 24, 0, 0, tzinfo=timezone.utc)
    
    # User says: "I am free Monday 18:00 - 20:00" in Vancouver
    slots = [MockSlot("Monday", "18:00", "20:00")]
    
    # Expand for Vancouver
    results = expand_availability(slots, start_date, user_timezone="America/Vancouver", days=7)
    
    assert len(results) >= 1
    first_slot = results[0]
    
    # 18:00 PST is 02:00 UTC the NEXT day (Tuesday)
    # OR 18:00 PDT is 01:00 UTC.
    # In Nov, it's Standard Time (PST, UTC-8). 18 + 8 = 26 (02:00 next day)
    
    assert first_slot['start'].hour == 2
    assert first_slot['start'].day == 25 # Tuesday, not Monday
    assert first_slot['duration'] == 2.0


# This test assumes deadlines do NOT prevent scheduling in later weekly slots.
# The current algorithm enforces deadlines correctly, so this test fails.
# Update the 'now' date to a future value if you want to re-enable it.
# Remove the commented import at the top as well.
""" 
def test_scheduler_greedy_allocation():
    #Test that the algorithm picks the highest priority task first.
    now = datetime(2025, 11, 24, 12, 0, tzinfo=timezone.utc)
    
    # 2 Hours available
    slots = [MockSlot("Monday", "12:00", "14:00")] # Matches 'now' for simplicity (UTC)
    
    # Task A: High Priority (2 hours)
    tA = MockTask("A", now + timedelta(hours=5), 100, "hard", 2)
    
    # Task B: Low Priority (1 hour)
    tB = MockTask("B", now + timedelta(days=5), 1, "easy", 1)
    
    results = generate_schedule_plan([tA, tB], slots, user_timezone="UTC", now=now)
    
    # We expect 2 results because the slot repeats next week
    assert len(results) == 2
    
    # The FIRST scheduled item must be Task A (High Priority)
    assert results[0]['task_id'] == "A"
    
    # Task A should be on the 24th
    assert results[0]['start'].day == 24
    
    # Task B should be bumped to the next Monday (Dec 1st)
    assert results[1]['task_id'] == "B"
    assert results[1]['start'].day == 1 
"""