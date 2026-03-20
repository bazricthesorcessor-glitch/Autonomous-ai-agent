# ========================= main.py =========================
import threading
from core import api_server
from engines import janitor
from engines.goal_scheduler import GoalScheduler
import config

def _check_fast_model():
    """Verify FAST_MODEL is available in Ollama; fall back to PRIMARY_MODEL if not."""
    try:
        from ollama import Client
        c = Client(host='http://localhost:11434')
        models = c.list()
        available = {m.get("name", m.get("model", "")) for m in models.get("models", [])}
        if config.FAST_MODEL not in available:
            # Also check without tag (e.g., "llama3.2:3b" might be listed as "llama3.2:3b")
            short_names = {n.split(":")[0] for n in available}
            fast_short = config.FAST_MODEL.split(":")[0]
            if fast_short not in short_names:
                print(f"[Startup] FAST_MODEL '{config.FAST_MODEL}' not found in Ollama, "
                      f"falling back to PRIMARY_MODEL '{config.PRIMARY_MODEL}'")
                config.FAST_MODEL = config.PRIMARY_MODEL
            else:
                print(f"[Startup] FAST_MODEL '{config.FAST_MODEL}' available.")
        else:
            print(f"[Startup] FAST_MODEL '{config.FAST_MODEL}' available.")
    except Exception as e:
        print(f"[Startup] Could not check FAST_MODEL availability: {e}")
        config.FAST_MODEL = config.PRIMARY_MODEL

if __name__ == "__main__":
    # Run maintenance on startup (Summarize old logs, check health)
    janitor.run_maintenance()

    # Verify FAST_MODEL availability
    _check_fast_model()

    # Pre-warm semantic classifier embeddings in background
    from core.agent_loop import warm_classifier
    threading.Thread(target=warm_classifier, daemon=True, name="classifier-warmup").start()

    # Start autonomous goal scheduler in the background
    scheduler = GoalScheduler()
    scheduler.start()

    print(f"Avril Brain Server running on port 8000...")
    api_server.app.run(port=8000, debug=False, threaded=True)
