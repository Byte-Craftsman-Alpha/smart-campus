"""Derived availability.

No row stores a free/occupied flag. The answer is computed from three sources
united first (listing 1): live reservations, the official timetable, and room
closures. A window that intersects any of them never reaches the hard checks.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import config, intervals

SOURCE_LABEL = {"BOOKING": "a reservation", "TIMETABLE": "the timetable", "CLOSURE": "a closure"}


# ------------------------------------------------------------------ occupancy
def occupied_windows(conn, room_code: str, start, end):
    """Union of the three occupancy sources for one room inside [start, end)."""
    s, e = intervals.to_db(intervals.parse_dt(start)), intervals.to_db(intervals.parse_dt(end))
    out = []

    for row in conn.execute(
        """SELECT b.id, b.start_at, b.end_at, b.status, b.purpose, b.section_code, b.faculty_id
           FROM booking b
           WHERE b.room_code = ?
             AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
             AND ? < b.end_at AND b.start_at < ?""",
        (room_code, s, e),
    ):
        out.append({
            "source": "BOOKING", "start": row["start_at"], "end": row["end_at"],
            "label": f"{row['purpose'].title()} · {row['section_code'] or 'no section'}",
            "ref": row["id"], "status": row["status"],
        })

    for row in conn.execute(
        """SELECT t.id, t.weekday, t.period, c.title, t.section_code, t.valid_from, t.valid_to
           FROM timetable_slot t JOIN course c ON c.code = t.course_code
           WHERE t.room_code = ?""",
        (room_code,),
    ):
        for slot_start, slot_end in _slot_instances(row, start, end, conn):
            out.append({
                "source": "TIMETABLE", "start": intervals.to_db(slot_start),
                "end": intervals.to_db(slot_end),
                "label": f"Timetabled {row['title']} · {row['section_code']}",
                "ref": row["id"], "status": "TIMETABLE",
            })

    for row in conn.execute(
        """SELECT id, start_at, end_at, reason FROM room_closure
           WHERE room_code = ? AND ? < end_at AND start_at < ?""",
        (room_code, s, e),
    ):
        out.append({
            "source": "CLOSURE", "start": row["start_at"], "end": row["end_at"],
            "label": f"Closed: {row['reason']}", "ref": row["id"], "status": "CLOSED",
        })

    out.sort(key=lambda w: w["start"])
    return out


def _slot_instances(slot, start, end, conn):
    """Expand a recurring weekday+period slot into the datetimes it occupies."""
    grid = period_grid(conn)
    period = next((p for p in grid if p["id"] == slot["period"]), None)
    if period is None:
        return []
    s = intervals.parse_dt(start).date()
    e = intervals.parse_dt(end).date()
    valid_from = intervals.parse_dt(slot["valid_from"]).date()
    valid_to = intervals.parse_dt(slot["valid_to"]).date()
    day = max(s, valid_from)
    out = []
    while day <= min(e, valid_to):
        if config.WEEKDAYS[day.weekday()] == slot["weekday"]:
            out.append((intervals.combine(day, period["start"]),
                        intervals.combine(day, period["end"])))
        day += timedelta(days=1)
    return [p for p in out if intervals.overlaps(p[0], p[1], start, end)]


def period_grid(conn):
    from .seed import load_registry
    if not hasattr(period_grid, "_cache"):
        period_grid._cache = load_registry()["period_grid"]["periods"]
    return period_grid._cache


def free_windows(conn, room_code: str, start, end):
    """The complement of occupancy inside the requested window."""
    blockers = [(w["start"], w["end"]) for w in occupied_windows(conn, room_code, start, end)]
    return [(a, b) for a, b in intervals.subtract(
        (intervals.parse_dt(start), intervals.parse_dt(end)), blockers)]


# ------------------------------------------------------------------ room rows
def rooms(conn, building=None, bookable_only=True, room_types=None):
    sql = """SELECT r.*, f.building_code, f.level AS floor_level, b.name AS building_name,
                    b.distance_to_iet_m
             FROM room r
             JOIN floor f ON f.id = r.floor_id
             JOIN building b ON b.code = f.building_code"""
    where, args = [], []
    if bookable_only:
        where.append("r.bookable = 1")
    if building and building != "ALL":
        where.append("f.building_code = ?")
        args.append(building)
    if room_types:
        where.append("r.room_type IN (%s)" % ",".join("?" * len(room_types)))
        args.extend(room_types)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY f.building_code DESC, f.level, r.code"
    return [dict(r) for r in conn.execute(sql, args)]


def room_by_code(conn, code):
    row = conn.execute(
        """SELECT r.*, f.building_code, f.level AS floor_level, b.name AS building_name,
                  b.distance_to_iet_m
           FROM room r JOIN floor f ON f.id = r.floor_id JOIN building b ON b.code = f.building_code
           WHERE r.code = ?""", (code,)).fetchone()
    return dict(row) if row else None


def effective_capacity(room_row, purpose: str, exam_factor: float = 0.5) -> int:
    """Spaced capacity for examinations, nominal capacity otherwise.

    The stored exam_capacity already reflects the factor; the setting is applied
    only when the stored value is missing, so the two never disagree.
    """
    if purpose in config.EXAM_PURPOSES:
        stored = room_row.get("exam_capacity") or 0
        if stored:
            return stored
        return int((room_row.get("capacity") or 0) * exam_factor)
    return room_row.get("capacity") or 0


def permitted(room_row, purpose: str) -> bool:
    uses = room_row.get("permitted_uses") or "[]"
    if isinstance(uses, str):
        uses = json.loads(uses)
    return purpose in uses


def hard_check(room_row, purpose: str, headcount: int, features=None, accessible=False,
               exam_factor: float = 0.5) -> list[str]:
    """Every constraint that can exclude a room, named rather than summarised."""
    fails = []
    if not room_row["bookable"]:
        fails.append("not bookable")
    if not permitted(room_row, purpose):
        fails.append(f"not permitted for {purpose.lower()}")
    cap = effective_capacity(room_row, purpose, exam_factor)
    if headcount > cap:
        label = "spaced capacity" if purpose in config.EXAM_PURPOSES else "capacity"
        fails.append(f"seats {cap} against {headcount} requested ({label})")
    if features:
        have = room_row.get("features") or "[]"
        if isinstance(have, str):
            have = json.loads(have)
        missing = [f for f in features if f not in have]
        if missing:
            fails.append("missing " + ", ".join(missing))
    if accessible and room_row.get("accessibility") not in ("step_free", "lift"):
        fails.append("not step-free")
    return fails


# ------------------------------------------------------------------ search
def search(conn, start, end, headcount, purpose="CLASS", building="ALL", floor=None,
           features=None, accessible=False, include_unconfirmed=True) -> dict:
    """Availability for one window. Returns available rooms and the reasons the
    others were excluded -- a refusal is a question already answered."""
    start, end = intervals.parse_dt(start), intervals.parse_dt(end)
    factor = _exam_factor(conn)
    available, excluded = [], []
    for room in rooms(conn, building=building, bookable_only=False):
        if floor not in (None, "ALL") and str(room["floor_level"]) != str(floor):
            continue
        if not include_unconfirmed and room["unconfirmed"]:
            continue
        busy = occupied_windows(conn, room["code"], start, end)
        fails = hard_check(room, purpose, headcount, features, accessible, factor)
        if busy:
            fails.insert(0, "occupied by " + SOURCE_LABEL[busy[0]["source"]])
        if fails:
            excluded.append({**room, "reasons": fails, "busy": busy})
        else:
            windows = free_windows(conn, room["code"], start, end)
            available.append({**room, "free_windows": windows,
                              "slack": effective_capacity(room, purpose, factor) - headcount})
    available.sort(key=lambda r: (r["slack"], r["code"]))
    return {"available": available, "excluded": excluded,
            "window": (start, end), "headcount": headcount, "purpose": purpose}


def _exam_factor(conn):
    from . import policy
    return float(policy.get_setting(conn, "exam_spacing_factor"))


def day_schedule(conn, day: date, building="ALL"):
    """Everything that touches the rooms on one day, for the grid view."""
    rows = []
    lo = datetime.combine(day, datetime.min.time())
    hi = lo + timedelta(days=1)
    for room in rooms(conn, building=building, bookable_only=True):
        rows.append({"room": room, "windows": occupied_windows(conn, room["code"], lo, hi)})
    return rows


def section_schedule(conn, section_code: str, start, end):
    """A section's own week: reservations plus timetabled classes."""
    out = []
    for row in conn.execute(
        """SELECT b.*, r.label AS room_label, f.building_code
           FROM booking b JOIN room r ON r.code=b.room_code
           JOIN floor f ON f.id=r.floor_id
           WHERE b.section_code=?
             AND b.status IN ('CONFIRMED','PENDING_APPROVAL','CANCELLED','DISPLACED','COMPLETED')
             AND ? < b.end_at AND b.start_at < ?
           ORDER BY b.start_at""",
        (section_code, intervals.to_db(start), intervals.to_db(end))):
        out.append({**dict(row), "source": "BOOKING"})
    for row in conn.execute(
        """SELECT t.*, c.title, r.label AS room_label, fl.building_code
           FROM timetable_slot t
           JOIN course c ON c.code=t.course_code
           JOIN room r ON r.code=t.room_code
           JOIN floor fl ON fl.id=r.floor_id
           WHERE t.section_code=?""", (section_code,)):
        for s, e in _slot_instances(row, start, end, conn):
            out.append({"source": "TIMETABLE", "start_at": intervals.to_db(s),
                        "end_at": intervals.to_db(e), "room_code": row["room_code"],
                        "room_label": row["room_label"], "building_code": row["building_code"],
                        "purpose": "CLASS", "title": row["title"], "status": "TIMETABLE",
                        "section_code": section_code})
    out.sort(key=lambda r: r["start_at"])
    return out
