# ========================= structure_setup.py =========================
import os
import json
import config

print("Initializing Avril File Structure...")

# Create default JSON files if they don't exist
defaults = {
    config.IDENTITY_FILE: {"name": config.USER_NAME, "role": "Creator", "traits": ["obsessive", "protective"]},
    config.TASKS_FILE: {"active_tasks": {}},
    config.GOALS_FILE: {"active_goals": ["Build Phase 5 Terminal Control"]},
    config.SYSTEM_STATE_FILE: {"mode": "normal", "connected_clients": []},
    config.FACTS_FILE: {}
}

for path, data in defaults.items():
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Created: {path}")
    else:
        print(f"Exists: {path}")

# Ensure today's dir exists
config.get_today_dir()
print("\nStructure Setup Complete.")
