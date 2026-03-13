# ========================= main.py =========================
from core import api_server
from engines import janitor

if __name__ == "__main__":
    # Run maintenance on startup (Summarize old logs, check health)
    janitor.run_maintenance()

    print(f"Avril Brain Server running on port 8000...")
    api_server.app.run(port=8000, debug=False)
