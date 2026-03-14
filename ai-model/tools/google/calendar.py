# ========================= tools/google/calendar.py =========================
"""Google Calendar actions: today, list, add, delete."""

from datetime import datetime, timedelta, timezone
from tools.google.auth import build_service


def _fmt_event(ev: dict) -> str:
    title     = ev.get("summary", "(no title)")
    start_str = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "?"))[:16].replace("T", " ")
    end_str   = ev.get("end",   {}).get("dateTime", ev.get("end",   {}).get("date", "?"))[:16].replace("T", " ")
    location  = ev.get("location", "")
    desc      = ev.get("description", "")
    eid       = ev.get("id", "")
    line = f"  • {title}\n    {start_str} → {end_str}"
    if location:
        line += f"  |  {location}"
    if desc:
        line += f"\n    {desc[:120]}"
    line += f"\n    ID: {eid}"
    return line


def calendar_today(args: dict) -> str:
    cal, err = build_service("calendar", "v3")
    if err: return err

    now   = datetime.now(timezone.utc)
    start = now.replace(hour=0,  minute=0,  second=0,  microsecond=0).isoformat()
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    try:
        result = cal.events().list(
            calendarId="primary", timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime", maxResults=20
        ).execute()
    except Exception as e:
        return f"[calendar_today] {e}"

    events = result.get("items", [])
    today  = now.strftime("%A, %d %B %Y")
    if not events:
        return f"No events today ({today})."

    lines = [f"Today — {today}  ({len(events)} events)\n{'='*50}"]
    for ev in events:
        lines.append(_fmt_event(ev))
    return "\n".join(lines)


def calendar_list(args: dict) -> str:
    cal, err = build_service("calendar", "v3")
    if err: return err

    days   = max(1, min(int(args.get("days", 7)), 90))
    max_ev = max(1, min(int(args.get("max", 20)), 50))
    now    = datetime.now(timezone.utc)

    try:
        result = cal.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=max_ev
        ).execute()
    except Exception as e:
        return f"[calendar_list] {e}"

    events = result.get("items", [])
    if not events:
        return f"No events in the next {days} days."

    lines = [f"Next {days} days — {len(events)} events\n{'='*50}"]
    for ev in events:
        lines.append(_fmt_event(ev))
    return "\n".join(lines)


def calendar_add(args: dict) -> str:
    cal, err = build_service("calendar", "v3")
    if err: return err

    title = str(args.get("title", "")).strip()
    if not title:
        return "[calendar_add] No 'title' provided."

    date     = str(args.get("date", datetime.now().strftime("%Y-%m-%d")))
    time     = str(args.get("time", "09:00"))
    duration = max(5, int(args.get("duration", 60)))
    desc     = str(args.get("description", ""))
    location = str(args.get("location", ""))

    try:
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        end_dt   = start_dt + timedelta(minutes=duration)
    except ValueError as e:
        return f"[calendar_add] Bad date/time: {e}"

    event = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Kolkata"},
    }
    if desc:     event["description"] = desc
    if location: event["location"]    = location

    try:
        result = cal.events().insert(calendarId="primary", body=event).execute()
        return (
            f"Event added: '{title}'\n"
            f"Date: {date}  Time: {time}  Duration: {duration} min\n"
            f"Link: {result.get('htmlLink', '—')}\n"
            f"ID:   {result.get('id', '—')}"
        )
    except Exception as e:
        return f"[calendar_add] {e}"


def calendar_delete(args: dict) -> str:
    cal, err = build_service("calendar", "v3")
    if err: return err

    event_id = str(args.get("event_id", "")).strip()
    if not event_id:
        return "[calendar_delete] No 'event_id' provided."

    try:
        cal.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"Event deleted: {event_id}"
    except Exception as e:
        return f"[calendar_delete] {e}"
