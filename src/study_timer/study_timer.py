import time

# User clicks "Start studying (Task Name)"
# Timer runs and displays elapsed time in real-time
# User can "Pause" when they take a break
# User clicks "Stop" when done; system logs total hours to that task
# Timer saves data autoamtically (no manual entry needed)

# Dashboard shows: "CMPT276: 8.5 hours logged, CMPT201: 3.2 hours logged"
# System tracks:"You studied 15.7 hours this week"
# Breakdown by day: "Mon: 2.5 hrs, Tue: 3.1 hrs..."
# Can view history: "Last 7 days, Last 30 days, All time"

# System tracks how long users are logged into Smart Scheduler to measure engagement and app usage
# Tracking method: 
# Record 'session_start' when user logs in
# Record 'session_end' when user logs out or closes tab
# Calculate 'total_online_time' = 'session_end' - 'session_start'
# Store in analytics database

class StudyTimer:
    def __init__(self):
        self.start_time = None
        self.elapsed_time = 0
        self.is_running = False

    def start(self):
        """Start or resume the timer."""
        if not self.is_running:
            self.start_time = time.time()
            self.is_running = True

    def pause(self):
        """Pause the timer and accumulate elapsed time."""
        if self.is_running:
            self.elapsed_time += time.time() - self.start_time
            self.is_running = False
            self.start_time = None

    def stop(self):
        """Stop the timer and return total hours."""
        if self.is_running:
            self.elapsed_time += time.time() - self.start_time
            self.is_running = False
        total_hours = self.elapsed_time / 3600  # Convert seconds to hours
        return total_hours

    def get_elapsed_time(self):
        """Get current elapsed time in seconds (real-time calculation)."""
        if self.is_running:
            return self.elapsed_time + (time.time() - self.start_time)
        return self.elapsed_time

    def reset(self):
        """Reset the timer to initial state."""
        self.start_time = None
        self.elapsed_time = 0
        self.is_running = False

    def log_study_time(self, hours):
        # Here we would log the hours to the database or user profile
        print(f"Logged {hours:.2f} hours of study time.")
    
