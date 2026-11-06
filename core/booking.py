"""Reservation lifecycle: create, approve, reschedule, cancel, early release,
displace, and weekly series.

Every state change is a status change with a reason attached. Nothing is
deleted, ever, and the interface never offers the option.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import availability, config, intervals, policy, scoring


def now() -> str:
    return datetime.now().strftime(intervals.FMT)


# ------------------------------------------------------------------ helpers
def get_booking(conn, booking_id) -> dict | None:
    row = conn.execute(
        """SELECT b.*, r.label AS room_label, f.building_code, b.section_code,
                  fa.name AS faculty_name
           FROM booking b
           JOIN room r ON r.code = b.room_code
           JOIN floor f ON f.id = r.floor_id
           LEFT JOIN faculty fa ON fa.id = b.faculty_id
           WHERE b.id = ?""", (booking_id,)).fetchone()
    return dict(row) if row else None


def booking_events(conn, booking_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM booking_event WHERE booking_id=? ORDER BY id", (booking_id,))]


def _audit(conn, actor, action, entity, entity_id, before=None, after=None, request_id=None):
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state,
                                    after_state, request_id, at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (actor, action, entity, str(entity_id),
         json.dumps(before, default=str) if before is not None else None,
         json.dumps(after, default=str) if after is not None else None,
         request_id, now()))


def _event(conn, booking_id, event_type, actor, detail=None):
    conn.execute(
        "INSERT INTO booking_event (booking_id, event_type, actor, at, detail) VALUES (?,?,?,?,?)",
        (booking_id, event_type, actor, now(), detail))


def _notify_section(conn, section_code, payload):
    """Outbox rows, written inside the same transaction as the change."""
    if not section_code:
        return 0
    students = conn.execute(
        "SELECT roll_number FROM student WHERE section_code=?", (section_code,)).fetchall()
    for s in students:
        conn.execute(
            """INSERT INTO notification (user_id, channel, payload, status, attempts, created_at)
               VALUES (?,?,?,?,?,?)""",
            (s["roll_number"], "EMAIL", json.dumps(payload), "QUEUED", 0, now()))
    return len(students)


def _notification_ids(conn, section_code):
    if not section_code:
        return []
    return [r["roll_number"] for r in conn.execute(
        "SELECT roll_number FROM student WHERE section_code=?", (section_code,))]


def _fail(http, code, message, **extra):
    return {"ok": False, "http": http, "code": code, "message": message, **extra}


def _ok(http, booking, warnings=None, **extra):
    return {"ok": True, "http": http, "code": "OK", "booking": booking,
            "warnings": warnings or [], **extra}


# ------------------------------------------------------------------ validation
def validate_window(conn, start, end, purpose) -> str | None:
    """Everything that can be wrong with a window before a room is considered."""
    try:
        s, e = intervals.parse_dt(start), intervals.parse_dt(end)
    except intervals.IntervalError:
        return "The start or end time is not a timestamp."
    if s >= e:
        return "The end of a reservation must be after its start."
    snap = int(policy.get_setting(conn, "snap_minutes"))
    if (s.minute % snap) or (e.minute % snap):
        return f"Times must fall on the {snap}-minute grid."
    if intervals.duration_minutes(s, e) < snap:
        return "A reservation must last at least one grid step."
    lead = int(policy.get_setting(conn, "min_lead_time_minutes"))
    if e < datetime.now() + timedelta(minutes=lead):
        return f"The window has already passed, or is inside the {lead}-minute lead time."
    horizon = int(policy.get_setting(conn, "booking_horizon_days"))
    if s > datetime.now() + timedelta(days=horizon):
        return f"The booking horizon is {horizon} days; that window is beyond it."
    return None


def validate_headcount(headcount) -> str | None:
    try:
        hc = int(headcount)
    except (TypeError, ValueError):
        return "Headcount must be a whole number."
    if hc < 1:
        return "Headcount must be at least one."
    if hc > 1000:
        return "Headcount above a thousand is outside the model."
    return None


def _cross_building_warning(conn, section_code, start, end, room_row):
    """Two activities for one section in different buildings need a buffer."""
    if not section_code or room_row is None:
        return None
    gap = int(policy.get_setting(conn, "min_cross_building_gap_minutes"))
    s, e = intervals.parse_dt(start), intervals.parse_dt(end)
    neighbours = conn.execute(
        """SELECT b.*, f.building_code FROM booking b JOIN room r ON r.code=b.room_code
           JOIN floor f ON f.id=r.floor_id
           WHERE b.section_code=? AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
             AND b.start_at >= ? AND b.start_at <= ?""",
        (section_code, intervals.to_db(s - timedelta(hours=3)),
         intervals.to_db(e + timedelta(hours=3)))).fetchall()
    for n in neighbours:
        other_start = intervals.parse_dt(n["start_at"])
        if n["building_code"] == room_row["building_code"]:
            continue
        if other_start >= e:
            if (other_start - e).total_seconds() / 60 < gap:
                return (f"{section_code} has a class in {n['building_code']} at "
                        f"{other_start:%H:%M}, {int((other_start - e).total_seconds() // 60)} minutes "
                        f"after this one ends; the cross-building gap is {gap} minutes.")
        elif s >= intervals.parse_dt(n["end_at"]):
            if (s - intervals.parse_dt(n["end_at"])).total_seconds() / 60 < gap:
                return (f"{section_code} leaves {n['building_code']} too close to this window; "
                        f"the cross-building gap is {gap} minutes.")
    return None


# ------------------------------------------------------------------ create
def create(conn, actor, room_code, start, end, purpose="CLASS", headcount=75,
           section_code=None, faculty_id=None, idempotency_key=None, title=None,
           series_id=None, request_id=None, require_approval=None,
           auto_faculty=True) -> dict:
    """Create one reservation. Returns an HTTP-shaped result."""
    decision = policy.can(actor, "booking:create")
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)

    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM booking WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            return _ok(200, get_booking(conn, existing["id"]),
                       note="Repeated request: the original reservation is returned.")

    problem = validate_headcount(headcount)
    if problem:
        return _fail(422, "INVALID_HEADCOUNT", problem)
    headcount = int(headcount)
    purpose = (purpose or "CLASS").upper()
    if purpose not in config.PURPOSES:
        return _fail(422, "INVALID_PURPOSE", f"{purpose!r} is not a purpose the model knows.")
    problem = validate_window(conn, start, end, purpose)
    if problem:
        return _fail(422, "INVALID_WINDOW", problem)

    if section_code is not None and not conn.execute(
            "SELECT 1 FROM section WHERE code=?", (section_code,)).fetchone():
        return _fail(422, "INVALID_SECTION",
                     f"There is no section {section_code!r} in the register.")
    room = availability.room_by_code(conn, room_code)
    if room is None:
        return _fail(404, "ROOM_NOT_FOUND", f"There is no room {room_code!r} on the campus register.")
    if not room["bookable"]:
        return _fail(422, "ROOM_NOT_BOOKABLE",
                     f"{room['label']} is not a bookable space; it is recorded as {room['room_type'].lower()}.")
    if not availability.permitted(room, purpose):
        return _fail(422, "PURPOSE_NOT_PERMITTED",
                     f"{room['label']} is not offered for {purpose.lower()}.")

    factor = float(policy.get_setting(conn, "exam_spacing_factor"))
    cap = availability.effective_capacity(room, purpose, factor)
    if headcount > cap:
        code = "EXAM_CAPACITY_EXCEEDED" if purpose in config.EXAM_PURPOSES else "CAPACITY_EXCEEDED"
        extras = {}
        if purpose in config.EXAM_PURPOSES:
            extras["split"] = scoring.plan_split(conn, start, end, headcount, purpose)
        return _fail(422, code,
                     f"{room['label']} seats {cap} for {purpose.lower()} against "
                     f"{headcount} requested.", **extras)

    # gates
    gate = policy.gate_reason(room, headcount, purpose)
    gated_decision = policy.can(actor, "booking:create_gated")
    if gate and gated_decision.requires_approval:
        require_approval = True
    if require_approval is None:
        require_approval = bool(gate) and actor.role != "admin"

    # closure inside the window
    closure = conn.execute(
        """SELECT * FROM room_closure WHERE room_code=? AND ? < end_at AND start_at < ?""",
        (room_code, intervals.to_db(intervals.parse_dt(start)),
         intervals.to_db(intervals.parse_dt(end)))).fetchone()
    if closure:
        return _fail(409, "ROOM_CLOSED",
                     f"{room['label']} is closed for {closure['reason']} in that window.")

    if faculty_id is None and auto_faculty and actor.role == "faculty":
        faculty_id = actor.faculty_id

    # Pre-checks in the order that produces the most useful refusal. The
    # triggers remain the arbiter; these exist so the caller is told which
    # constraint fired, and so the alternatives can be attached.
    live = [w for w in availability.occupied_windows(conn, room_code, start, end)
            if w["source"] == "BOOKING"]
    if live:
        return _fail(409, "ROOM_ALREADY_BOOKED",
                     f"{room_code} is already committed in that window: {live[0]['label']}.",
                     alternatives=scoring.alternatives(conn, start, end, headcount, purpose,
                                                       from_room=room, exclude_room=room_code))
    timetabled = [w for w in availability.occupied_windows(conn, room_code, start, end)
                  if w["source"] == "TIMETABLE"]
    if timetabled:
        return _fail(409, "TIMETABLE_OCCUPIED",
                     f"{room_code} carries a timetabled class in that window "
                     f"({timetabled[0]['label']}).",
                     alternatives=scoring.alternatives(conn, start, end, headcount, purpose,
                                                       from_room=room, exclude_room=room_code))
    if section_code:
        section_clash = conn.execute(
            """SELECT b.id, b.room_code, b.start_at, b.end_at FROM booking b
               WHERE b.section_code=? AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
                 AND ? < b.end_at AND b.start_at < ?""",
            (section_code, intervals.to_db(intervals.parse_dt(start)),
             intervals.to_db(intervals.parse_dt(end)))).fetchone()
        if section_clash:
            return _fail(409, "SECTION_DOUBLE_BOOKED",
                         f"{section_code} is already expected in {section_clash['room_code']} at "
                         f"{section_clash['start_at'][11:]}. A section cannot be in two rooms at once.",
                         alternatives=scoring.alternatives(conn, start, end, headcount, purpose,
                                                           from_room=room, exclude_room=room_code))
    if faculty_id:
        faculty_clash = conn.execute(
            """SELECT b.id, b.room_code, b.start_at FROM booking b
               WHERE b.faculty_id=? AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
                 AND ? < b.end_at AND b.start_at < ?""",
            (faculty_id, intervals.to_db(intervals.parse_dt(start)),
             intervals.to_db(intervals.parse_dt(end)))).fetchone()
        if faculty_clash:
            return _fail(409, "FACULTY_DOUBLE_BOOKED",
                         f"You are already booked in {faculty_clash['room_code']} at "
                         f"{faculty_clash['start_at'][11:]}, so you cannot be in two rooms at once.",
                         alternatives=scoring.alternatives(conn, start, end, headcount, purpose,
                                                           from_room=room, exclude_room=room_code))

    status = "PENDING_APPROVAL" if require_approval else "CONFIRMED"
    warnings = []
    warn = _cross_building_warning(conn, section_code, start, end, room)
    if warn:
        warnings.append(warn)

    s, e = intervals.to_db(intervals.parse_dt(start)), intervals.to_db(intervals.parse_dt(end))
    try:
        cur = conn.execute(
            """INSERT INTO booking (room_code, section_code, faculty_id, start_at, end_at, purpose,
                                    headcount, status, is_test, version, idempotency_key, series_id,
                                    title, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (room_code, section_code, faculty_id, s, e, purpose, headcount, status,
             1 if policy.get_setting(conn, "demo_mode") else 0, 1, idempotency_key,
             series_id, title or f"{purpose.title()} · {section_code or room_code}",
             actor.id, now(), now()))
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        code = "DB_CONSTRAINT"
        for candidate in ("ROOM_ALREADY_BOOKED", "SECTION_DOUBLE_BOOKED", "FACULTY_DOUBLE_BOOKED"):
            if candidate in message:
                code = candidate
                break
        alternatives = scoring.alternatives(
            conn, start, end, headcount, purpose,
            from_room=room, exclude_room=room_code,
            required_features=None)
        if "FOREIGN KEY" in message:
            code = "REFERENCE_MISSING"
        detail = {
            "ROOM_ALREADY_BOOKED": f"{room_code} is already committed in that window.",
            "SECTION_DOUBLE_BOOKED": f"{section_code} is already expected somewhere else at that hour.",
            "FACULTY_DOUBLE_BOOKED": "You are already booked elsewhere at that hour.",
            "REFERENCE_MISSING": "A referenced record does not exist in the register.",
        }.get(code, "The database refused the insert.")
        return _fail(409, code, detail, alternatives=alternatives, room=room_code)

    booking_id = cur.lastrowid
    _event(conn, booking_id, "CREATED", actor.id,
           f"{status} for {section_code or 'no section'} in {room_code}")
    if require_approval:
        _event(conn, booking_id, "APPROVAL_REQUESTED", actor.id, gate or "approval required")
        _notify_owner(conn, actor.id, booking_id, "Your reservation is waiting for approval")
    else:
        _notify_section(conn, section_code, {
            "booking": booking_id, "room": room_code,
            "start": s, "end": e, "message": "A class has been placed in your schedule"})
    _audit(conn, actor.id, "booking:create", "booking", booking_id, None,
           {"room": room_code, "start": s, "end": e, "status": status}, request_id)
    return _ok(201, get_booking(conn, booking_id), warnings=warnings,
               requires_approval=require_approval, gate=gate)


def _notify_owner(conn, user_id, booking_id, message):
    conn.execute(
        """INSERT INTO notification (user_id, channel, payload, status, attempts, created_at)
           VALUES (?,?,?,?,?,?)""",
        (user_id, "EMAIL", json.dumps({"booking": booking_id, "message": message}),
         "QUEUED", 0, now()))


# ------------------------------------------------------------------ transitions
def approve(conn, actor, booking_id, note=None) -> dict:
    decision = policy.can(actor, "booking:approve")
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    if b["status"] != "PENDING_APPROVAL":
        return _fail(409, "NOT_PENDING", f"That reservation is {b['status'].lower()}, not pending.")
    clash = availability.occupied_windows(conn, b["room_code"], b["start_at"], b["end_at"])
    clash = [c for c in clash if c.get("ref") != booking_id and c["source"] == "BOOKING"]
    if clash:
        return _fail(409, "ROOM_ALREADY_BOOKED",
                     "The room was taken while the request waited; the request cannot be confirmed.",
                     alternatives=scoring.alternatives(conn, b["start_at"], b["end_at"],
                                                       b["headcount"], b["purpose"]))
    try:
        conn.execute("UPDATE booking SET status='CONFIRMED', version=version+1, updated_at=? WHERE id=?",
                     (now(), booking_id))
    except sqlite3.IntegrityError as exc:
        return _fail(409, "CONFLICT", str(exc))
    _event(conn, booking_id, "APPROVED", actor.id, note or "approved")
    _notify_section(conn, b["section_code"], {
        "booking": booking_id, "room": b["room_code"],
        "start": b["start_at"], "end": b["end_at"], "message": "Your reservation was approved"})
    _audit(conn, actor.id, "booking:approve", "booking", booking_id,
           {"status": "PENDING_APPROVAL"}, {"status": "CONFIRMED"})
    return _ok(200, get_booking(conn, booking_id))


def reject(conn, actor, booking_id, reason) -> dict:
    decision = policy.can(actor, "booking:approve")
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    if not reason or not reason.strip():
        return _fail(422, "REASON_REQUIRED", "A rejection needs a reason.")
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    if b["status"] != "PENDING_APPROVAL":
        return _fail(409, "NOT_PENDING", f"That reservation is {b['status'].lower()}, not pending.")
    conn.execute("UPDATE booking SET status='REJECTED', reason=?, version=version+1, updated_at=? WHERE id=?",
                 (reason, now(), booking_id))
    _event(conn, booking_id, "REJECTED", actor.id, reason)
    _notify_owner(conn, b["created_by"], booking_id, f"Your request was refused: {reason}")
    _audit(conn, actor.id, "booking:reject", "booking", booking_id,
           {"status": "PENDING_APPROVAL"}, {"status": "REJECTED", "reason": reason})
    return _ok(200, get_booking(conn, booking_id))


def cancel(conn, actor, booking_id, reason, force=False) -> dict:
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    decision = policy.can(actor, "booking:cancel", b)
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    if b["status"] in ("CANCELLED", "REJECTED", "COMPLETED", "DISPLACED"):
        return _fail(409, "NOT_LIVE", f"That reservation is already {b['status'].lower()}.")
    if not reason or not reason.strip():
        return _fail(422, "REASON_REQUIRED", "A cancellation carries a mandatory reason.")
    started = intervals.parse_dt(b["start_at"]) <= datetime.now()
    if started and actor.role != "admin" and not force:
        return _fail(403, "AFTER_START",
                     "The class has already started or happened; only an administrator may "
                     "record a cancellation now, with a reason.")

    conn.execute(
        "UPDATE booking SET status='CANCELLED', reason=?, version=version+1, updated_at=? WHERE id=?",
        (reason, now(), booking_id))
    _event(conn, booking_id, "CANCELLED", actor.id, reason)
    notice_id = _announce_cancellation(conn, actor, b, reason)
    _notify_section(conn, b["section_code"], {
        "booking": booking_id, "room": b["room_code"],
        "start": b["start_at"], "end": b["end_at"],
        "message": f"Your class in {b['room_code']} was cancelled: {reason}"})
    _audit(conn, actor.id, "booking:cancel", "booking", booking_id,
           {"status": b["status"]}, {"status": "CANCELLED", "reason": reason})
    return _ok(200, get_booking(conn, booking_id), announcement_id=notice_id)


def _announce_cancellation(conn, actor, b, reason):
    title = f"Class cancelled: {b['section_code'] or b['purpose'].title()} in {b['room_code']}"
    body = (f"The reservation for {b['section_code'] or 'this activity'} in {b['room_code']} at "
            f"{intervals.fmt_range(b['start_at'], b['end_at'])} has been cancelled. "
            f"Reason: {reason}.")
    cur = conn.execute(
        """INSERT INTO announcement (scope, scope_id, severity, title, body, publish_at,
                                     supersedes_booking_id, version, created_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("SECTION" if b["section_code"] else "CAMPUS", b["section_code"], "IMPORTANT",
         title, body, now(), b["id"], 1, actor.id))
    return cur.lastrowid


def reschedule(conn, actor, booking_id, start, end, reason=None) -> dict:
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    decision = policy.can(actor, "booking:reschedule", b)
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    if b["status"] not in config.LIVE_STATUSES:
        return _fail(409, "NOT_LIVE", f"A {b['status'].lower()} reservation cannot be moved.")
    problem = validate_window(conn, start, end, b["purpose"])
    if problem:
        return _fail(422, "INVALID_WINDOW", problem)
    if availability.occupied_windows(conn, b["room_code"], start, end):
        others = [w for w in availability.occupied_windows(conn, b["room_code"], start, end)
                  if w.get("ref") != booking_id]
        if others:
            return _fail(409, "ROOM_ALREADY_BOOKED",
                         f"{b['room_code']} is committed in the new window.",
                         alternatives=scoring.alternatives(conn, start, end, b["headcount"],
                                                           b["purpose"], exclude_room=b["room_code"]))
    s, e = intervals.to_db(intervals.parse_dt(start)), intervals.to_db(intervals.parse_dt(end))
    try:
        conn.execute(
            "UPDATE booking SET start_at=?, end_at=?, version=version+1, updated_at=? WHERE id=?",
            (s, e, now(), booking_id))
    except sqlite3.IntegrityError as exc:
        return _fail(409, "CONFLICT", str(exc))
    _event(conn, booking_id, "RESCHEDULED", actor.id,
           f"{b['start_at']} -> {s}" + (f" ({reason})" if reason else ""))
    _notify_section(conn, b["section_code"], {
        "booking": booking_id, "room": b["room_code"], "start": s, "end": e,
        "message": "Your class has moved"})
    _audit(conn, actor.id, "booking:reschedule", "booking", booking_id,
           {"start": b["start_at"], "end": b["end_at"]}, {"start": s, "end": e, "reason": reason})
    return _ok(200, get_booking(conn, booking_id))


def early_release(conn, actor, booking_id, new_end) -> dict:
    """Shorten a reservation while it is in progress. The remainder returns to
    the pool; nothing is deleted and attendance is untouched."""
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    decision = policy.can(actor, "booking:early_release", b)
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    if b["status"] not in config.LIVE_STATUSES:
        return _fail(409, "NOT_LIVE", f"A {b['status'].lower()} reservation cannot be released.")
    new_end = intervals.parse_dt(new_end)
    orig_end = intervals.parse_dt(b["end_at"])
    if new_end >= orig_end:
        return _fail(422, "NOT_SHORTER", "An early release must end before the booked end.")
    if new_end <= intervals.parse_dt(b["start_at"]):
        return _fail(422, "INVALID_WINDOW", "The release would erase the whole reservation; cancel instead.")
    released = (new_end, orig_end)
    conn.execute(
        "UPDATE booking SET end_at=?, version=version+1, updated_at=? WHERE id=?",
        (intervals.to_db(new_end), now(), booking_id))
    _event(conn, booking_id, "EARLY_RELEASE", actor.id,
           f"End moved from {orig_end:%H:%M} to {new_end:%H:%M}; "
           f"{intervals.duration_minutes(new_end, orig_end)} minutes returned")
    _notify_section(conn, b["section_code"], {
        "booking": booking_id, "message": f"The class ends at {new_end:%H:%M} today"})
    _audit(conn, actor.id, "booking:early_release", "booking", booking_id,
           {"end": b["end_at"]}, {"end": intervals.to_db(new_end)})
    return _ok(200, get_booking(conn, booking_id), released=[intervals.to_db(x) for x in released])


def displace(conn, actor, booking_id, reason, new_room=None, new_start=None, new_end=None) -> dict:
    """Administrative override: move an existing reservation to free a room."""
    decision = policy.can(actor, "booking:displace")
    if not decision.allowed:
        return _fail(403, "FORBIDDEN", decision.reason)
    if not reason or not reason.strip():
        return _fail(422, "REASON_REQUIRED", "A displacement carries a mandatory reason.")
    b = get_booking(conn, booking_id)
    if b is None:
        return _fail(404, "NOT_FOUND", "No such reservation.")
    if b["status"] not in config.LIVE_STATUSES:
        return _fail(409, "NOT_LIVE", f"A {b['status'].lower()} reservation cannot be displaced.")
    room = new_room or b["room_code"]
    start = new_start or b["start_at"]
    end = new_end or b["end_at"]
    occupied = [w for w in availability.occupied_windows(conn, room, start, end)
                if w.get("ref") != booking_id]
    if occupied:
        return _fail(409, "ROOM_ALREADY_BOOKED", f"{room} is committed in the new window.")
    try:
        conn.execute(
            """UPDATE booking SET status='DISPLACED', room_code=?, start_at=?, end_at=?,
                                  reason=?, version=version+1, updated_at=? WHERE id=?""",
            (room, intervals.to_db(intervals.parse_dt(start)), intervals.to_db(intervals.parse_dt(end)),
             reason, now(), booking_id))
    except sqlite3.IntegrityError as exc:
        return _fail(409, "CONFLICT", str(exc))
    _event(conn, booking_id, "DISPLACED", actor.id,
           f"{b['room_code']} -> {room} ({reason})")
    conn.execute(
        """INSERT INTO announcement (scope, scope_id, severity, title, body, publish_at,
                                     supersedes_booking_id, version, created_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("SECTION", b["section_code"], "IMPORTANT",
         f"Room changed for {b['section_code'] or 'your class'}",
         f"{b['section_code'] or 'The activity'} moves from {b['room_code']} to {room} for "
         f"{intervals.fmt_range(start, end)}. Reason: {reason}.",
         now(), b["id"], 1, actor.id))
    _notify_section(conn, b["section_code"], {"booking": booking_id, "message": "Room changed"})
    _audit(conn, actor.id, "booking:displace", "booking", booking_id,
           {"room": b["room_code"], "start": b["start_at"]}, {"room": room, "reason": reason})
    return _ok(200, get_booking(conn, booking_id))


def complete_past(conn) -> int:
    """The system closes intervals whose end has passed."""
    cur = conn.execute(
        "UPDATE booking SET status='COMPLETED', updated_at=? "
        "WHERE status IN ('CONFIRMED','PENDING_APPROVAL') AND end_at < ?",
        (now(), now()))
    return cur.rowcount


# ------------------------------------------------------------------ series
def create_series(conn, actor, room_code, start, end, weekday, weeks, **kwargs) -> dict:
    """Weekly classes are created and cancelled as one action (BOOKING_SERIES)."""
    weeks = int(weeks)
    if weeks < 1 or weeks > 18:
        return _fail(422, "INVALID_SERIES", "A series must run between one and eighteen weeks.")
    cur = conn.execute(
        "INSERT INTO booking_series (recurrence_rule, created_by, created_at) VALUES (?,?,?)",
        (f"WEEKLY:{weekday}:{weeks}", actor.id, now()))
    series_id = cur.lastrowid
    created, failed = [], []
    s0, e0 = intervals.parse_dt(start), intervals.parse_dt(end)
    for week in range(weeks):
        s = s0 + timedelta(weeks=week)
        e = e0 + timedelta(weeks=week)
        result = create(conn, actor, room_code, s, e, series_id=series_id,
                        **{k: v for k, v in kwargs.items()})
        if result["ok"]:
            created.append(result["booking"]["id"])
        else:
            failed.append({"week": week, "code": result["code"], "message": result["message"]})
    if not created:
        conn.execute("DELETE FROM booking_series WHERE id=?", (series_id,))
        return _fail(409, failed[0]["code"], failed[0]["message"], failures=failed)
    return _ok(201, None, series_id=series_id, created=created, failed=failed)


def cancel_series(conn, actor, series_id, reason) -> dict:
    rows = conn.execute(
        "SELECT id FROM booking WHERE series_id=? AND status IN ('CONFIRMED','PENDING_APPROVAL')",
        (series_id,)).fetchall()
    if not rows:
        return _fail(404, "NOT_FOUND", "That series has no live reservations.")
    done, refused = [], []
    for row in rows:
        result = cancel(conn, actor, row["id"], reason)
        (done if result["ok"] else refused).append(row["id"])
    return {"ok": bool(done), "http": 200, "code": "OK", "cancelled": done, "refused": refused}
