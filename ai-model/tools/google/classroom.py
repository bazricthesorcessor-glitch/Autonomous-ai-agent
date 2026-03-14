# ========================= tools/google/classroom.py =========================
"""Google Classroom actions: courses, assignments, announcements."""

from tools.google.auth import build_service


def classroom_courses(args: dict) -> str:
    gc, err = build_service("classroom", "v1")
    if err: return err

    try:
        result = gc.courses().list(
            studentId="me", courseStates=["ACTIVE"], pageSize=20,
            fields="courses(id,name,section,description)"
        ).execute()
    except Exception as e:
        return f"[classroom_courses] {e}"

    courses = result.get("courses", [])
    if not courses:
        return "No active Google Classroom courses."

    lines = [f"Google Classroom — {len(courses)} active courses\n{'='*50}"]
    for c in courses:
        name    = c.get("name", "—")
        section = c.get("section", "")
        cid     = c.get("id", "—")
        desc    = c.get("description", "")
        lines.append(f"\n  • {name}" + (f" ({section})" if section else ""))
        lines.append(f"    ID: {cid}")
        if desc:
            lines.append(f"    {desc[:100]}")
    return "\n".join(lines)


def classroom_assignments(args: dict) -> str:
    gc, err = build_service("classroom", "v1")
    if err: return err

    course_id = str(args.get("course_id", "")).strip()
    if not course_id:
        return "[classroom_assignments] No 'course_id'. Run action='classroom_courses' first."

    max_items = max(1, min(int(args.get("max", 20)), 50))

    try:
        result = gc.courses().courseWork().list(
            courseId=course_id, pageSize=max_items, orderBy="dueDate desc",
            fields="courseWork(id,title,description,dueDate,state,maxPoints,workType,alternateLink)"
        ).execute()
    except Exception as e:
        return f"[classroom_assignments] {e}"

    items = result.get("courseWork", [])
    if not items:
        return f"No assignments for course: {course_id}"

    lines = [f"Assignments — course {course_id}  ({len(items)})\n{'='*50}"]
    for item in items:
        title  = item.get("title", "—")
        state  = item.get("state", "—")
        pts    = item.get("maxPoints", "—")
        wtype  = item.get("workType", "—")
        due    = item.get("dueDate", {})
        due_str = (
            f"{due.get('year','?')}-{str(due.get('month','?')).zfill(2)}-{str(due.get('day','?')).zfill(2)}"
            if due else "No due date"
        )
        desc = item.get("description", "")
        link = item.get("alternateLink", "")
        lines.append(f"\n  • {title}  [{state}]")
        lines.append(f"    Due: {due_str}  |  Points: {pts}  |  Type: {wtype}")
        if desc:  lines.append(f"    {desc[:120]}")
        if link:  lines.append(f"    {link}")
    return "\n".join(lines)


def classroom_announcements(args: dict) -> str:
    gc, err = build_service("classroom", "v1")
    if err: return err

    course_id = str(args.get("course_id", "")).strip()
    if not course_id:
        return "[classroom_announcements] No 'course_id'. Run action='classroom_courses' first."

    max_items = max(1, min(int(args.get("max", 10)), 30))

    try:
        result = gc.courses().announcements().list(
            courseId=course_id, pageSize=max_items, orderBy="updateTime desc",
            fields="announcements(id,text,updateTime,alternateLink)"
        ).execute()
    except Exception as e:
        return f"[classroom_announcements] {e}"

    items = result.get("announcements", [])
    if not items:
        return f"No announcements for course: {course_id}"

    lines = [f"Announcements — course {course_id}  ({len(items)})\n{'='*50}"]
    for item in items:
        text = item.get("text", "—")
        ts   = item.get("updateTime", "")[:10]
        link = item.get("alternateLink", "")
        lines.append(f"\n  [{ts}]  {text[:300]}")
        if link: lines.append(f"  {link}")
    return "\n".join(lines)
