"""Grounded natural-language search.

The model may read results and return a structured intent; it has no path that
writes (section 7.1). Every room code that appears in an answer is checked
against the result set the query returned, and an answer that mentions a room
the query did not offer is replaced by the plain result list.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import availability, config, intervals

WEEKDAY_HINTS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

EXAMPLES = [
    "Which rooms are free tomorrow at 10:00 for 75 students?",
    "Is IET20 free on Monday at 11:00?",
    "How many rooms can hold 90 candidates for an exam?",
    "When is CSE-3A's next class?",
    "Which rooms seat 200 people?",
]


def _next_weekday(today: date, target: int) -> date:
    delta = (target - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def parse_day(text: str, today: date | None = None) -> date:
    today = today or date.today()
    low = text.lower()
    if "day after tomorrow" in low:
        return today + timedelta(days=2)
    if "tomorrow" in low:
        return today + timedelta(days=1)
    if "today" in low:
        return today
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for name, idx in WEEKDAY_HINTS.items():
        if name in low:
            return _next_weekday(today, idx)
    return today + timedelta(days=1)


def parse_time(text: str, default="10:00") -> str:
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", text.lower())
    if not m:
        m2 = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text.lower())
        if m2:
            hour = int(m2.group(1)) % 12
            if m2.group(2) == "pm":
                hour += 12
            return f"{hour:02d}:00"
        return default
    hour, minute = int(m.group(1)), int(m.group(2))
    suffix = m.group(3)
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_headcount(text: str, default=75) -> int:
    """Numbers tied to people, not to clock times: '75 students', 'for 90'."""
    patterns = [
        r"(\d{2,4})\s*(?:students|candidates|people|seats|persons|headcount|attendees)",
        r"\bfor\s+(\d{2,4})\b",
        r"\b(?:needs?|holds?|seats?)\s+(\d{2,4})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = int(m.group(1))
            if 1 <= value <= 1000:
                return value
    return default


def parse_purpose(text: str) -> str:
    low = text.lower()
    if "exam" in low:
        return "EXAM"
    if "practical" in low or "lab" in low:
        return "PRACTICAL"
    if "seminar" in low:
        return "SEMINAR"
    if "event" in low:
        return "EVENT"
    if "tutorial" in low:
        return "TUTORIAL"
    if "viva" in low:
        return "VIVA"
    return "CLASS"


def _room_codes(conn):
    return [r["code"] for r in conn.execute("SELECT code FROM room")]


def _mentioned_rooms(text, codes, ignore_case=True):
    """Room codes named in a string. Answers are checked case-sensitively,
    because 'to' is a word and TO is an office."""
    found = []
    flags = re.IGNORECASE if ignore_case else 0
    for code in sorted(codes, key=len, reverse=True):
        if re.search(rf"\b{re.escape(code)}\b", text, flags):
            found.append(code)
    return found


def detect_intent(question: str, conn) -> str:
    low = question.lower()
    if re.search(r"\bwhen\b|\bwhere is\b|\bschedule of\b", low) and re.search(r"[a-z]{2,5}-\d", low):
        return "section_schedule"
    if "free" in low and (_mentioned_rooms(question, _room_codes(conn)) or "is " in low):
        if _mentioned_rooms(question, _room_codes(conn)):
            return "room_free"
    if re.search(r"how many rooms|count of rooms", low):
        return "count_rooms"
    if re.search(r"seat|hold|capacity", low) and "free" not in low:
        return "capacity_lookup"
    if "free" in low or "available" in low:
        return "find_rooms"
    if "cancelled" in low or "cancel" in low:
        return "cancellations"
    return "find_rooms"


def ask(conn, question: str, actor=None, today=None) -> dict:
    question = (question or "").strip()
    if not question:
        return {"intent": "none", "answer": "Ask a question about rooms, sections or the register.",
                "rooms": [], "guardrail_triggered": False, "data": {}}

    today = today or date.today()
    intent = detect_intent(question, conn)
    codes = _room_codes(conn)
    mentioned = _mentioned_rooms(question, codes)
    purpose = parse_purpose(question)
    day = parse_day(question, today)
    hhmm = parse_time(question)
    headcount = parse_headcount(question)

    if intent == "room_free" and mentioned:
        room = availability.room_by_code(conn, mentioned[0])
        start = intervals.combine(day, hhmm)
        end = start + timedelta(minutes=int(_setting(conn, "period_length_minutes")))
        busy = availability.occupied_windows(conn, mentioned[0], start, end)
        free = not busy
        if free:
            name = room["label"] if room["label"] != room["code"] else room["code"]
            answer = (f"{name} ({room['code']}) is free on {day:%a %d %b} from "
                      f"{hhmm} to {end:%H:%M}.")
        else:
            name = room["label"] if room["label"] != room["code"] else room["code"]
            answer = (f"{name} ({room['code']}) is not free on {day:%a %d %b} between "
                      f"{hhmm} and {end:%H:%M}: {busy[0]['label'].lower()}.")
        result_rooms = [mentioned[0]]
        data = {"room": mentioned[0], "free": free, "busy": busy}

    elif intent == "section_schedule":
        m = re.search(r"\b([A-Z]{2,5}-\d[AB]?)\b", question.upper())
        section = m.group(1) if m else None
        if section is None:
            return {"intent": intent,
                    "answer": "Name the section, for example CSE-3A, and I will look it up.",
                    "rooms": [], "guardrail_triggered": False, "data": {}}
        start = intervals.combine(today, "00:00")
        end = start + timedelta(days=7)
        rows = availability.section_schedule(conn, section, start, end)
        future = [r for r in rows if intervals.parse_dt(r["start_at"]) >= datetime.now()]
        if not future:
            answer = f"{section} has nothing on the schedule in the next seven days."
        else:
            first = future[0]
            answer = (f"{section}'s next class is {intervals.fmt_range(first['start_at'], first['end_at'])} "
                      f"in {first['room_label']} ({first['room_code']}). "
                      f"There are {len(future)} entries in the next seven days.")
        result_rooms = sorted({r["room_code"] for r in future})
        data = {"section": section, "entries": future}

    elif intent == "count_rooms":
        rows = [r for r in availability.rooms(conn, bookable_only=False)
                if availability.effective_capacity(r, purpose, _exam_factor(conn)) >= headcount]
        answer = (f"{len(rows)} rooms can take {headcount} people for {purpose.lower()}: "
                  + ", ".join(r["code"] for r in rows) + ".")
        result_rooms = [r["code"] for r in rows]
        data = {"rooms": rows, "headcount": headcount}

    elif intent == "capacity_lookup":
        rows = [r for r in availability.rooms(conn, bookable_only=False)
                if availability.effective_capacity(r, purpose, _exam_factor(conn)) >= headcount]
        rows.sort(key=lambda r: r["capacity"])
        answer = (f"{len(rows)} rooms seat at least {headcount} for {purpose.lower()}. "
                  + (f"The tightest fit is {rows[0]['code']} at {rows[0]['capacity']}." if rows else ""))
        result_rooms = [r["code"] for r in rows]
        data = {"rooms": rows, "headcount": headcount}

    elif intent == "cancellations":
        rows = conn.execute(
            """SELECT b.id, b.room_code, b.start_at, b.section_code, b.reason
               FROM booking b WHERE b.status='CANCELLED' ORDER BY b.start_at DESC LIMIT 10"""
        ).fetchall()
        answer = (f"{len(rows)} cancellations on record. "
                  + (f"The most recent released {rows[0]['room_code']} for {rows[0]['section_code']}."
                     if rows else ""))
        result_rooms = sorted({r["room_code"] for r in rows})
        data = {"cancellations": [dict(r) for r in rows]}

    else:  # find_rooms
        start = intervals.combine(day, hhmm)
        end = start + timedelta(minutes=int(_setting(conn, "period_length_minutes")))
        result = availability.search(conn, start, end, headcount, purpose)
        avail = result["available"][:8]
        if avail:
            answer = (f"{len(result['available'])} rooms are free on {day:%a %d %b} from {hhmm} to "
                      f"{end:%H:%M} for {headcount} people: "
                      + ", ".join(f"{r['code']} ({r['capacity']})" for r in avail) + ".")
        else:
            answer = (f"No room is free on {day:%a %d %b} between {hhmm} and {end:%H:%M} "
                      f"for {headcount} people. Widen the building filter or shift the window.")
        result_rooms = [r["code"] for r in avail]
        data = {"search": result, "window": (intervals.to_db(start), intervals.to_db(end))}

    # ------------------------------------------------------------ guardrail
    bookable_codes = [r["code"] for r in availability.rooms(conn)]
    answer, guardrail = apply_guardrail(answer, result_rooms, bookable_codes)
    return {"intent": intent, "answer": answer, "rooms": result_rooms,
            "guardrail_triggered": guardrail, "data": data,
            "parsed": {"day": day.strftime(intervals.FMT_DAY), "time": hhmm,
                       "headcount": headcount, "purpose": purpose}}


def apply_guardrail(answer: str, result_rooms, bookable_codes) -> tuple[str, bool]:
    """Replace any answer that names a room the query did not return.

    This is the check that makes the hallucinated-room failure impossible rather
    than unlikely: the answer may only mention codes from its own result set.
    """
    allowed = set(result_rooms)
    stray = [c for c in _mentioned_rooms(answer, bookable_codes, ignore_case=False)
             if c not in allowed]
    if not stray:
        return answer, False
    replacement = ("The drafted answer named a room the query did not return, so it has been "
                   "replaced by the plain result list: "
                   + (", ".join(sorted(allowed)) if allowed else "no rooms."))
    return replacement, True


def _setting(conn, key):
    from . import policy
    return policy.get_setting(conn, key)


def _exam_factor(conn):
    from . import policy
    return float(policy.get_setting(conn, "exam_spacing_factor"))
