from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional

# Difficulty Multipliers
DIFFICULTY_MAP = {
    "easy": 1.0,
    "medium": 1.5,
    "hard": 2.0
}

def calculate_priority(task, now: datetime) -> float:
    """
    Calculate a priority score. Higher is more important.
    Formula: (Weight * Difficulty) / (Hours until Deadline + 1)
    """
    # 1. Weight (Decimal to float)
    weight = float(task.weight_pct)
    
    # 2. Difficulty
    diff_multiplier = DIFFICULTY_MAP.get(task.difficulty, 1.0)
    
    # 3. Urgency (Hours until deadline)
    time_diff = task.deadline - now
    hours_until_due = max(time_diff.total_seconds() / 3600, 0.1) 
    
    # Score calculation
    score = (weight * diff_multiplier) / hours_until_due
    return score

def expand_availability(availability_list, start_date_utc: datetime, user_timezone: str = "UTC", days=14):
    """
    Convert recurring availability (Monday 18:00 Local Time) 
    into specific UTC Datetime slots for the next 'days'.
    """
    expanded_slots = []
    
    # --- NEW LOGIC: Handle Timezones ---
    try:
        user_tz = ZoneInfo(user_timezone)
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")

    # Convert the start date to User's local time to begin counting days properly
    # (e.g. It might be Monday in Vancouver but Tuesday in UTC)
    start_date_local = start_date_utc.astimezone(user_tz)

    for i in range(days):
        # Iterate through days in LOCAL time
        current_day_local = start_date_local + timedelta(days=i)
        current_day_name = current_day_local.strftime("%A").lower()
        
        for slot in availability_list:
            if slot.day_of_week.lower() == current_day_name:
                # Parse HH:MM
                sh, sm = map(int, slot.start_time.split(':'))
                eh, em = map(int, slot.end_time.split(':'))
                
                # 1. Construct LOCAL datetimes (e.g. Monday 18:00 Vancouver)
                slot_start_local = current_day_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
                slot_end_local = current_day_local.replace(hour=eh, minute=em, second=0, microsecond=0)
                
                # Handle overflow (e.g. 23:00 to 01:00 next day)
                if slot_end_local <= slot_start_local:
                    slot_end_local += timedelta(days=1)

                # 2. Convert to UTC (e.g. Tuesday 02:00 UTC)
                slot_start_utc = slot_start_local.astimezone(timezone.utc)
                slot_end_utc = slot_end_local.astimezone(timezone.utc)

                # 3. Logic Checks (in UTC)
                # Skip if slot is already in the past
                if slot_end_utc <= start_date_utc:
                    continue
                
                # Adjust start if we are currently IN the slot
                if slot_start_utc < start_date_utc < slot_end_utc:
                    slot_start_utc = start_date_utc

                duration = (slot_end_utc - slot_start_utc).total_seconds() / 3600
                if duration > 0:
                    expanded_slots.append({
                        "start": slot_start_utc,
                        "end": slot_end_utc,
                        "duration": duration
                    })
    
    # Sort slots by time
    expanded_slots.sort(key=lambda x: x['start'])
    return expanded_slots

def generate_schedule_plan(tasks, availability_list, user_timezone: str = "UTC", now: Optional[datetime] = None):
    """
    Core Algorithm:
    1. Sort tasks by priority.
    2. Expand availability into real time slots (Timezone Aware).
    3. Allocates tasks to slots (splitting if needed).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # 1. Filter completed tasks and Sort by Priority
    active_tasks = [t for t in tasks if t.status != 'completed' and t.deadline > now]
    
    for t in active_tasks:
        t.priority_score = calculate_priority(t, now)
        t.remaining_hours = float(t.estimated_hours)

    # Sort: Highest priority first
    active_tasks.sort(key=lambda x: x.priority_score, reverse=True)
    
    # 2. Get Time Slots (PASS THE TIMEZONE HERE)
    # --- This was missing in your version ---
    slots = expand_availability(availability_list, now, user_timezone, days=14)
    
    schedule_results = []
    
    # 3. Greedy Allocation
    for slot in slots:
        if not active_tasks:
            break 
            
        slot_duration = slot['duration']
        slot_start = slot['start']
        
        for task in active_tasks:
            if slot_duration <= 0:
                break 
            
            if task.remaining_hours <= 0:
                continue

            # Don't schedule this task in this slot if we've passed its deadline
            hours_until_deadline = (task.deadline - slot_start).total_seconds() / 3600
            if hours_until_deadline <= 0:
                continue

            # Max we can allocate before hitting either:
            # - end of slot
            # - remaining hours
            # - task deadline
            time_to_allocate = min(slot_duration, task.remaining_hours, hours_until_deadline)
            if time_to_allocate <= 0:
                continue
            
            block_end = slot_start + timedelta(hours=time_to_allocate)
            
            reason = (
                f"Task: {getattr(task, 'name', 'Untitled')} | "
                f"Priority Score: {task.priority_score:.2f} | "
                f"Deadline: {task.deadline.strftime('%Y-%m-%d %H:%M')} | "
                f"Weight: {float(task.weight_pct):.1f}% | "
                f"Allocated: {time_to_allocate:.2f} hours"
            )

            schedule_results.append({
                "task_id": task.id,
                "start": slot_start,
                "end": block_end,
                "reasoning": reason
            })
            
            task.remaining_hours -= time_to_allocate
            slot_duration -= time_to_allocate
            slot_start = block_end 

    return schedule_results