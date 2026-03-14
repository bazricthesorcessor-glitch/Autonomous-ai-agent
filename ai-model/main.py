# ========================= main.py =========================
from core import api_server
from engines import janitor
from engines.goal_scheduler import GoalScheduler

if __name__ == "__main__":
    # Run maintenance on startup (Summarize old logs, check health)
    janitor.run_maintenance()

    # Start autonomous goal scheduler in the background
    scheduler = GoalScheduler()
    scheduler.start()

    print(f"Avril Brain Server running on port 8000...")
    api_server.app.run(port=8000, debug=False, threaded=True)
