# ========================= tools/web/browser.py =========================
"""Open URLs in Firefox only. Never falls back to other browsers."""

import shutil
import subprocess


def open_browser(args: dict) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return "[open_browser] No 'url' provided."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    private = str(args.get("private", "false")).lower() in ("true", "1", "yes")

    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        return "[open_browser] Firefox is not installed. Automation requires Firefox."

    try:
        cmd = [firefox]
        if private:
            cmd.append("--private-window")
        cmd.append(url)

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        mode = " (private)" if private else ""
        return f"Opened Firefox: {url}{mode}"

    except Exception as e:
        return f"[open_browser] Failed to open Firefox: {e}"
