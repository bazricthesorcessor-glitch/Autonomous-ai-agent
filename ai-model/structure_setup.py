# ========================= structure_setup.py =========================
import os
import json
import config

print("Initializing Avril File Structure...")

# Create default JSON files if they don't exist
defaults = {
    config.IDENTITY_FILE:     {"ai_name": config.AI_NAME, "user": config.USER_NAME, "system": "Arch Linux, Wayland, Hyprland"},
    config.TASKS_FILE:        {"active": [], "completed": []},
    config.GOALS_FILE:        {"goals": ["Help Divyansh with any task efficiently and completely"]},
    config.SYSTEM_STATE_FILE: {"status": "online", "last_restart": None},
    config.FACTS_FILE:        {}
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
