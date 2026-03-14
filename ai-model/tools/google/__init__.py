# ========================= tools/google/__init__.py =========================
"""
Google Apps integration package — Drive, Calendar, Classroom, Gmail.

Structure:
  tools/google/
    __init__.py    ← this file (dispatcher)
    auth.py        ← OAuth2 helpers, credential paths, build_service()
    drive.py       ← Google Drive: list, search, read, upload, create_folder
    calendar.py    ← Google Calendar: today, list, add, delete
    classroom.py   ← Google Classroom: courses, assignments, announcements
    gmail.py       ← Gmail: list, read, send, search

First-time setup:
  1. https://console.cloud.google.com/ → New project
  2. Enable: Drive API + Calendar API + Classroom API + Gmail API
  3. Credentials → OAuth 2.0 Client ID → Desktop App → Download JSON
  4. Save as: ai-model/config/google_credentials.json
  5. run_tool({"action": "auth"})  → browser opens → done

  NOTE: If you added Gmail after initial setup, delete google_token.json and re-run auth.

Usage:
  from tools import google
  google.run_tool({"action": "auth_status"})
  google.run_tool({"action": "drive_list", "max": 10})
  google.run_tool({"action": "calendar_today"})
  google.run_tool({"action": "classroom_courses"})
  google.run_tool({"action": "gmail_list", "max": 5})
  google.run_tool({"action": "gmail_send", "to": "x@y.com", "subject": "Hi", "body": "..."})
"""

from tools.google.auth      import auth, auth_status
from tools.google.drive     import drive_list, drive_search, drive_read, drive_upload, drive_create_folder
from tools.google.calendar  import calendar_today, calendar_list, calendar_add, calendar_delete
from tools.google.classroom import classroom_courses, classroom_assignments, classroom_announcements
from tools.google.gmail     import gmail_list, gmail_read, gmail_send, gmail_search


def _list_actions(_: dict) -> str:
    return (
        "Google tools  (tools/google/)\n\n"
        "Auth         → auth.py\n"
        "  auth                  Start OAuth2 login (opens browser)\n"
        "  auth_status           Check token status\n\n"
        "Drive        → drive.py\n"
        "  drive_list            List files         [folder_id, max=20, type=pdf|doc|sheet]\n"
        "  drive_search          Search files       [query, max=10]\n"
        "  drive_read            Read file content  [file_id, max_chars=5000]\n"
        "  drive_upload          Upload local file  [path, folder_id]\n"
        "  drive_create_folder   Create folder      [name, parent_id]\n\n"
        "Calendar     → calendar.py\n"
        "  calendar_today        Today's events\n"
        "  calendar_list         Upcoming events    [days=7, max=20]\n"
        "  calendar_add          Add event          [title, date, time, duration=60]\n"
        "  calendar_delete       Delete event       [event_id]\n\n"
        "Classroom    → classroom.py\n"
        "  classroom_courses     List active courses\n"
        "  classroom_assignments Assignments        [course_id, max=20]\n"
        "  classroom_announcements Announcements    [course_id, max=10]\n\n"
        "Gmail        → gmail.py\n"
        "  gmail_list            Recent inbox       [max=10, label=INBOX]\n"
        "  gmail_read            Read email         [message_id=...]\n"
        "  gmail_send            Send email         [to=..., subject=..., body=...]\n"
        "  gmail_search          Search emails      [query=..., max=10]"
    )


_ACTIONS = {
    # auth
    "auth":                    auth,
    "auth_status":             auth_status,
    # drive
    "drive_list":              drive_list,
    "drive_search":            drive_search,
    "drive_read":              drive_read,
    "drive_upload":            drive_upload,
    "drive_create_folder":     drive_create_folder,
    # calendar
    "calendar_today":          calendar_today,
    "calendar_list":           calendar_list,
    "calendar_add":            calendar_add,
    "calendar_delete":         calendar_delete,
    # classroom
    "classroom_courses":       classroom_courses,
    "classroom_assignments":   classroom_assignments,
    "classroom_announcements": classroom_announcements,
    # gmail
    "gmail_list":              gmail_list,
    "gmail_read":              gmail_read,
    "gmail_send":              gmail_send,
    "gmail_search":            gmail_search,
    "list":                    _list_actions,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return "[google] No action specified. Use action='list' to see all tools."
    fn = _ACTIONS.get(action)
    if fn is None:
        return f"[google] Unknown action '{action}'. Available: {', '.join(_ACTIONS)}"
    try:
        return fn(args)
    except Exception as e:
        return f"[google] Error in '{action}': {e}"
