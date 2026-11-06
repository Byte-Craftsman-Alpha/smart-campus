"""Seed the register, the academic structure, the timetable and a few
demonstration bookings.

Reference data is a file, not a habit (section 6.4): the room register comes
from data/campus_room_registry.json and is never retyped here.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from . import config, intervals

BRANCHES = [
    ("CSE", 2, "Computer Science and Engineering"),
    ("AIML", 2, "Artificial Intelligence and Machine Learning"),
    ("AIDS", 1, "Artificial Intelligence and Data Science"),
    ("ECE", 1, "Electronics and Communication Engineering"),
    ("MECH", 1, "Mechanical Engineering"),
    ("IT", 1, "Information Technology"),
]

FACULTY = [
    ("FAC-01", "Dr A. Verma", "a.verma@iet.example.edu", "Computer Science", "IET"),
    ("FAC-02", "Dr S. Mishra", "s.mishra@iet.example.edu", "Computer Science", "IET"),
    ("FAC-03", "Dr P. Rai", "p.rai@iet.example.edu", "AI and ML", "IET"),
    ("FAC-04", "Dr N. Singh", "n.singh@iet.example.edu", "AI and Data Science", "IET"),
    ("FAC-05", "Dr R. Pandey", "r.pandey@iet.example.edu", "Electronics", "IET"),
    ("FAC-06", "Dr M. Khan", "m.khan@iet.example.edu", "Mechanical", "DB"),
    ("FAC-07", "Dr K. Tiwari", "k.tiwari@iet.example.edu", "Information Technology", "DB"),
    ("FAC-08", "Dr J. Yadav", "j.yadav@iet.example.edu", "Applied Science", "DB"),
]

COURSE_TITLES = {
    "CSE": "Database Management Systems",
    "AIML": "Machine Learning",
    "AIDS": "Data Engineering",
    "ECE": "Digital Signal Processing",
    "MECH": "Thermodynamics",
    "IT": "Computer Networks",
}

PERIODS_PER_SLOT_DAY = 5


def load_registry() -> dict:
    return json.loads(config.REGISTRY_PATH.read_text())


def _now() -> str:
    return datetime.now().strftime(intervals.FMT)


def next_teaching_day(anchor: date, offset: int = 0) -> date:
    """The offset-th teaching day on or after anchor (Sunday is skipped)."""
    day, found = anchor, -1
    while found < offset:
        if day.weekday() != 6:
            found += 1
        if found < offset:
            day += timedelta(days=1)
    return day


def _free(conn, room_code, start_at, end_at, weekday, period) -> bool:
    clash_booking = conn.execute(
        """SELECT 1 FROM booking WHERE room_code=? AND status IN ('CONFIRMED','PENDING_APPROVAL')
           AND ? < end_at AND start_at < ?""",
        (room_code, intervals.to_db(start_at), intervals.to_db(end_at)),
    ).fetchone()
    clash_slot = conn.execute(
        "SELECT 1 FROM timetable_slot WHERE room_code=? AND weekday=? AND period=?",
        (room_code, weekday, period),
    ).fetchone()
    return not clash_booking and not clash_slot


def seed_all(conn, anchor: date | None = None) -> dict:
    """Idempotent: the caller has already checked that room is empty."""
    anchor = anchor or date.today()
    reg = load_registry()
    stats = {}

    # ---------------------------------------------------------------- buildings
    inter = reg["meta"]["inter_building"]["IET<->DB"]
    for code, meta in reg["meta"]["buildings"].items():
        conn.execute(
            "INSERT INTO building (code, name, distance_to_iet_m, has_lift, entry_gate) VALUES (?,?,?,?,?)",
            (code, meta["name"], 0 if code == "IET" else inter["distance_m"],
             1 if meta.get("lift") else 0, meta["entry"]),
        )
        for idx, fl in enumerate(meta["floors"]):
            conn.execute(
                "INSERT INTO floor (building_code, level, label) VALUES (?,?,?)",
                (code, idx, fl),
            )

    # -------------------------------------------------------------------- rooms
    for r in reg["rooms"]:
        floor_row = conn.execute(
            "SELECT id FROM floor WHERE building_code=? AND label=?",
            (r["building"], r["floor"]),
        ).fetchone()
        conn.execute(
            """INSERT INTO room (code, floor_id, room_type, label, capacity, exam_capacity,
                                 bookable, accessibility, zone, permitted_uses, features,
                                 unconfirmed, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["code"], floor_row["id"], r["rtype"], r["label"], r["capacity"],
             r["exam_capacity"], 1 if r["bookable"] else 0, r.get("accessibility"),
             r.get("zone"), json.dumps(r.get("permitted_uses", [])),
             json.dumps(r.get("features", [])), 1 if r.get("unconfirmed") else 0,
             r.get("notes")),
        )
    stats["rooms"] = len(reg["rooms"])

    # ----------------------------------------------------------------- settings
    for k, v in config.DEFAULT_SETTINGS.items():
        conn.execute("INSERT INTO setting (key, value, updated_at) VALUES (?,?,?)",
                     (k, str(v), _now()))

    # ----------------------------------------------------------------- sections
    sections = []
    for year in (1, 2, 3, 4):
        for branch, count, _name in BRANCHES:
            for idx in range(count):
                suffix = "AB"[idx]
                sections.append((f"{branch}-{year}{suffix}", branch, year, 75))
    conn.executemany("INSERT INTO section (code, branch, year, strength) VALUES (?,?,?,?)",
                     sections)
    stats["sections"] = len(sections)

    # ----------------------------------------------------------------- students
    students = []
    for code, branch, year, _strength in sections:
        for n in (1, 2, 3):
            students.append((f"{code}-{n:02d}", f"Student {code} number {n}", code))
    conn.executemany("INSERT INTO student (roll_number, name, section_code) VALUES (?,?,?)",
                     students)
    stats["students"] = len(students)

    # ------------------------------------------------------------------ faculty
    conn.executemany(
        "INSERT INTO faculty (id, name, email, department, home_building) VALUES (?,?,?,?,?)",
        FACULTY)
    stats["faculty"] = len(FACULTY)

    # ------------------------------------------------------------------ courses
    courses = []
    for branch, _count, _name in BRANCHES:
        for year in (1, 2, 3, 4):
            courses.append((f"{branch}{year}01", COURSE_TITLES[branch], branch, year,
                            json.dumps(["projector"] if branch in ("CSE", "AIML") else [])))
    conn.executemany(
        "INSERT INTO course (code, title, branch, year, required_features) VALUES (?,?,?,?,?)",
        courses)

    # ---------------------------------------------------------------- timetable
    # The official recurring classes are the background load: roughly five of
    # the eight periods for each section, spread across the week.
    grid = [(p["id"], p["start"], p["end"]) for p in reg["period_grid"]["periods"]]
    room_rows = conn.execute(
        "SELECT code, capacity FROM room WHERE bookable=1 AND room_type IN ('CLASS','LAB') ORDER BY capacity DESC"
    ).fetchall()
    big_rooms = [r["code"] for r in room_rows if r["capacity"] >= 75]
    all_rooms = [r["code"] for r in room_rows]

    slots = 0
    for s_idx, (sec, branch, year, _strength) in enumerate(sections):
        course = f"{branch}{year}01"
        faculty_id = FACULTY[s_idx % len(FACULTY)][0]
        chosen = [(s_idx + k * 2) % 6 for k in range(PERIODS_PER_SLOT_DAY)]
        for k, day_idx in enumerate(chosen):
            weekday = config.WEEKDAYS[day_idx]
            period_id, p_start, p_end = grid[(s_idx + k) % len(grid)]
            candidates = big_rooms if (s_idx + k) % 4 else all_rooms
            for room in candidates:
                start = intervals.combine(anchor, p_start)
                end = intervals.combine(anchor, p_end)
                if _free(conn, room, start, end, weekday, period_id) and not conn.execute(
                        "SELECT 1 FROM timetable_slot WHERE section_code=? AND weekday=? AND period=?",
                        (sec, weekday, period_id)).fetchone():
                    conn.execute(
                        """INSERT INTO timetable_slot (course_code, section_code, room_code, weekday,
                                                      period, valid_from, valid_to)
                           VALUES (?,?,?,?,?,?,?)""",
                        (course, sec, room, weekday, period_id,
                         anchor.strftime(intervals.FMT_DAY),
                         (anchor + timedelta(days=120)).strftime(intervals.FMT_DAY)))
                    slots += 1
                    break
    stats["timetable_slots"] = slots

    # ------------------------------------------------------- demonstration data
    stats["demo_bookings"] = _seed_demo(conn, anchor, grid, sections, big_rooms)

    # ------------------------------------------------------------ setting trail
    conn.execute(
        "INSERT INTO setting_history (key, old_value, new_value, actor, at) VALUES (?,?,?,?,?)",
        ("exam_spacing_factor", None, str(config.DEFAULT_SETTINGS["exam_spacing_factor"]),
         "system:seed", _now()))
    return stats


def _seed_demo(conn, anchor, grid, sections, big_rooms):
    """A handful of reservations, every one flagged is_test so the interface can
    mark it (section 1.2: test data carries a flag and a visible marker)."""
    day1 = next_teaching_day(anchor, 0)
    day2 = next_teaching_day(anchor, 1)
    day3 = next_teaching_day(anchor, 2)
    rows = [
        # (room, section, faculty, day, period_index, purpose, headcount, status, reason)
        ("IET20", "CSE-3A", "FAC-01", day1, 0, "CLASS", 75, "CONFIRMED", None),
        ("IET19", "CSE-3B", "FAC-02", day1, 1, "CLASS", 75, "CONFIRMED", None),
        ("LH01", "IT-2A", "FAC-07", day1, 2, "CLASS", 75, "CONFIRMED", None),
        ("IET32", None, "FAC-03", day1, 3, "SEMINAR", 150, "PENDING_APPROVAL",
         "Seminar hall needs administrative approval"),
        ("IET22", "AIML-4A", "FAC-03", day2, 0, "PRACTICAL", 75, "CONFIRMED", None),
        ("LIB", None, "FAC-04", day2, 4, "EXAM", 90, "CONFIRMED", None),
        ("IET18", "ECE-1A", "FAC-05", day2, 5, "CLASS", 75, "CONFIRMED", None),
        ("LH08", "AIDS-3A", "FAC-08", day3, 1, "CLASS", 75, "CONFIRMED", None),
        ("IET24", "MECH-2A", "FAC-06", day3, 6, "CLASS", 75, "CANCELLED",
         "Faculty on duty leave"),
    ]
    made = 0
    for room, sec, fac, day, p_idx, purpose, headcount, status, reason in rows:
        period_id, p_start, p_end = grid[p_idx % len(grid)]
        start = intervals.combine(day, p_start)
        end = intervals.combine(day, p_end)
        weekday = config.WEEKDAYS[day.weekday()]
        if status != "CANCELLED" and not _free(conn, room, start, end, weekday, period_id):
            continue
        cur = conn.execute(
            """INSERT INTO booking (room_code, section_code, faculty_id, start_at, end_at, purpose,
                                    headcount, status, reason, is_test, version, title, created_by,
                                    created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (room, sec, fac, intervals.to_db(start), intervals.to_db(end), purpose, headcount,
             status, reason, 1, 1, f"{purpose.title()} · demo", fac, _now(), _now()))
        conn.execute(
            "INSERT INTO booking_event (booking_id, event_type, actor, at, detail) VALUES (?,?,?,?,?)",
            (cur.lastrowid, "CREATED", fac, _now(), f"Demonstration booking ({status})"))
        made += 1

    # a closure with no reservations inside it, so the demo has a clean example
    close_day = next_teaching_day(anchor, 4)
    p_id, p_start, p_end = grid[5]
    conn.execute(
        """INSERT INTO room_closure (room_code, start_at, end_at, reason, created_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("IET17", intervals.to_db(intervals.combine(close_day, p_start)),
         intervals.to_db(intervals.combine(close_day, p_end)),
         "Electrical repair in the corridor", "ADM-01", _now()))
    return made
