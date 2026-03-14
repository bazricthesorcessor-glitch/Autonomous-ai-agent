# ========================= tools/google/auth.py =========================
"""
Google OAuth2 authentication helpers shared across Drive, Calendar, Classroom.

Credential files:
  ai-model/config/google_credentials.json  ← download from Google Cloud Console
  ai-model/config/google_token.json        ← auto-generated after first login

Setup:
  1. https://console.cloud.google.com/ → New project
  2. Enable: Google Drive API, Google Calendar API, Google Classroom API
  3. Credentials → OAuth 2.0 Client ID → Desktop App → Download JSON
  4. Save as: ai-model/config/google_credentials.json
  5. Call: auth({}), opens browser once, token saved automatically
"""

import os
import json
import tempfile

_HERE  = os.path.dirname(os.path.abspath(__file__))
_ROOT  = os.path.dirname(os.path.dirname(_HERE))   # ai-model/
CREDS_FILE = os.path.join(_ROOT, "config", "google_credentials.json")
TOKEN_FILE  = os.path.join(_ROOT, "config", "google_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/gmail.modify",  # read + send + labels
]

_ERR_MISSING_PKGS = (
    "[google] Missing packages. Run:\n"
    "  pip install google-auth google-auth-oauthlib google-api-python-client"
)


def check_imports() -> str | None:
    try:
        import google.auth                   # noqa
        import google_auth_oauthlib.flow     # noqa
        import googleapiclient.discovery     # noqa
        return None
    except ImportError as e:
        return f"{_ERR_MISSING_PKGS}\nMissing: {e}"


def get_creds():
    """Returns (credentials, error_str). Auto-refreshes expired tokens."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds, None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds, None
        except Exception:
            creds = None

    if not os.path.exists(CREDS_FILE):
        return None, (
            "[google] credentials.json not found.\n"
            f"Expected at: {CREDS_FILE}\n"
            "Run action='auth' for setup instructions."
        )

    try:
        flow  = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        _save(creds)
        return creds, None
    except Exception as e:
        return None, f"[google] OAuth failed: {e}"


def _save(creds) -> None:
    """Atomically write token file — crash during write cannot corrupt the existing token."""
    token_dir = os.path.dirname(TOKEN_FILE)
    os.makedirs(token_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=token_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(creds.to_json())
        os.replace(tmp_path, TOKEN_FILE)   # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def build_service(service: str, version: str):
    """Returns (api_client, error_str)."""
    err = check_imports()
    if err:
        return None, err
    creds, err = get_creds()
    if err:
        return None, err
    from googleapiclient.discovery import build
    try:
        return build(service, version, credentials=creds, cache_discovery=False), None
    except Exception as e:
        return None, f"[google] Cannot build {service} client: {e}"


# ─── auth actions ────────────────────────────────────────────────────────────

def auth(args: dict) -> str:
    err = check_imports()
    if err:
        return err
    if not os.path.exists(CREDS_FILE):
        return (
            "[google] credentials.json not found. Setup:\n"
            "  1. https://console.cloud.google.com/ → New project\n"
            "  2. Enable Drive + Calendar + Classroom APIs\n"
            "  3. Credentials → OAuth 2.0 Client ID → Desktop App → Download JSON\n"
            f"  4. Save as: {CREDS_FILE}\n"
            "  5. Run action='auth' again"
        )
    creds, err = get_creds()
    if err:
        return err
    return "Google auth successful. Token saved. All Google tools ready."


def auth_status(args: dict) -> str:
    err = check_imports()
    if err:
        return err
    if not os.path.exists(CREDS_FILE):
        return f"Not configured. credentials.json missing at:\n  {CREDS_FILE}"
    if not os.path.exists(TOKEN_FILE):
        return "Credentials present but not logged in. Run action='auth'."
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds.valid:
            return "Authenticated. Token is valid."
        if creds.expired and creds.refresh_token:
            return "Token expired — will auto-refresh on next call."
        return "Token invalid. Run action='auth' to re-login."
    except Exception as e:
        return f"Token file corrupted: {e}. Run action='auth'."
