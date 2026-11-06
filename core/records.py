"""Closures, announcements, structured reports and the notification outbox."""
from __future__ import annotations

import json
from datetime import datetime

from . import availability, config, intervals, policy


def now() -> str:
    return datetime.now().strftime(intervals.FMT)


# ------------------------------------------------------------------ closures
def affected_by_closure(conn, room_code, start, end):
    """Reservations a closure would silently break (edge case: repairs)."""
    return [dict(r) for r in conn.execute(
        """SELECT b.*, r.label AS room_label FROM booking b JOIN room r ON r.code=b.room_code
           WHERE b.room_code=? AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
             AND ? < b.end_at AND b.start_at < ?
           ORDER BY b.start_at""",
        (room_code, intervals.to_db(intervals.parse_dt(start)),
         intervals.to_db(intervals.parse_dt(end))))]


def create_closure(conn, actor, room_code, start, end, reason, force=False) -> dict:
    decision = policy.can(actor, "room:close")
    if not decision.allowed:
        return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    if not reason or not reason.strip():
        return {"ok": False, "http": 422, "code": "REASON_REQUIRED", "message": "A closure needs a reason."}
    if not intervals.valid(start, end):
        return {"ok": False, "http": 422, "code": "INVALID_WINDOW",
                "message": "The closure must end after it starts."}
    room = availability.room_by_code(conn, room_code)
    if room is None:
        return {"ok": False, "http": 404, "code": "ROOM_NOT_FOUND", "message": "No such room."}
    affected = affected_by_closure(conn, room_code, start, end)
    if affected and not force:
        return {"ok": False, "http": 409, "code": "CLOSURE_WOULD_BREAK_BOOKINGS",
                "message": (f"{len(affected)} reservation(s) sit inside that closure. "
                            "Cancel or move them first; the affected list is shown."),
                "affected": affected}
    cur = conn.execute(
        """INSERT INTO room_closure (room_code, start_at, end_at, reason, created_by, created_at)
           VALUES (?,?,?,?,?,?)""",
        (room_code, intervals.to_db(intervals.parse_dt(start)),
         intervals.to_db(intervals.parse_dt(end)), reason, actor.id, now()))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor.id, "room:close", "room_closure", str(cur.lastrowid), None,
         json.dumps({"room": room_code, "start": str(start), "end": str(end), "reason": reason}), now()))
    return {"ok": True, "http": 201, "code": "OK", "closure_id": cur.lastrowid,
            "affected": affected}


def list_closures(conn, live_only=True):
    sql = """SELECT c.*, r.label AS room_label FROM room_closure c
             JOIN room r ON r.code=c.room_code"""
    if live_only:
        sql += " WHERE c.end_at > ?"
        return [dict(r) for r in conn.execute(sql + " ORDER BY c.start_at", (now(),))]
    return [dict(r) for r in conn.execute(sql + " ORDER BY c.start_at DESC")]


# ------------------------------------------------------------------ announcements
def publish(conn, actor, title, body, scope="CAMPUS", scope_id=None, severity="INFO",
            expires_at=None, supersedes_booking_id=None) -> dict:
    action = "notice:publish_campus" if scope in ("CAMPUS", "BUILDING") else "notice:publish_section"
    decision = policy.can(actor, action, {"created_by": actor.id, "id": actor.id})
    if not decision.allowed:
        # a member of faculty may address their own sections
        if not (actor.role == "faculty" and scope == "SECTION"):
            return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    if scope == "SECTION" and actor.role == "faculty":
        owns = conn.execute(
            """SELECT 1 FROM booking WHERE section_code=? AND faculty_id=?
               UNION SELECT 1 FROM timetable_slot t JOIN course c ON c.code=t.course_code
               WHERE t.section_code=? AND c.branch=(SELECT branch FROM section WHERE code=?)""",
            (scope_id, actor.faculty_id, scope_id, scope_id)).fetchone()
        if not owns:
            return {"ok": False, "http": 403, "code": "FORBIDDEN",
                    "message": f"You do not teach {scope_id}, so you may not publish to it."}
    if not title.strip() or not body.strip():
        return {"ok": False, "http": 422, "code": "INVALID_NOTICE",
                "message": "A notice needs a title and a body."}
    version = 1
    if supersedes_booking_id:
        prior = conn.execute(
            "SELECT MAX(version) v FROM announcement WHERE supersedes_booking_id=?",
            (supersedes_booking_id,)).fetchone()
        version = (prior["v"] or 0) + 1
    cur = conn.execute(
        """INSERT INTO announcement (scope, scope_id, severity, title, body, publish_at,
                                     expires_at, supersedes_booking_id, version, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (scope, scope_id, severity, title, body, now(), expires_at,
         supersedes_booking_id, version, actor.id))
    targets = notifications_for_scope(conn, scope, scope_id)
    for user in targets:
        conn.execute(
            """INSERT INTO notification (user_id, channel, payload, status, attempts, created_at)
               VALUES (?,?,?,?,?,?)""",
            (user, "EMAIL", json.dumps({"announcement": cur.lastrowid, "title": title}),
             "QUEUED", 0, now()))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor.id, "notice:publish", "announcement", str(cur.lastrowid), None,
         json.dumps({"scope": scope, "scope_id": scope_id, "title": title}), now()))
    return {"ok": True, "http": 201, "code": "OK", "announcement_id": cur.lastrowid,
            "notified": len(targets), "version": version}


def notifications_for_scope(conn, scope, scope_id):
    if scope == "SECTION" and scope_id:
        return [r["roll_number"] for r in conn.execute(
            "SELECT roll_number FROM student WHERE section_code=?", (scope_id,))]
    if scope == "CAMPUS":
        return [r["roll_number"] for r in conn.execute("SELECT roll_number FROM student")]
    if scope == "BUILDING" and scope_id:
        return [r["roll_number"] for r in conn.execute(
            """SELECT s.roll_number FROM student s
               JOIN booking b ON b.section_code = s.section_code
               JOIN room r ON r.code = b.room_code
               JOIN floor f ON f.id = r.floor_id
               WHERE f.building_code = ?""", (scope_id,))]
    return []


def list_announcements(conn, section_code=None, limit=50):
    if section_code:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM announcement
               WHERE scope='CAMPUS' OR (scope='SECTION' AND scope_id=?)
               ORDER BY id DESC LIMIT ?""", (section_code, limit))]
    return [dict(r) for r in conn.execute(
        "SELECT * FROM announcement ORDER BY id DESC LIMIT ?", (limit,))]


# ------------------------------------------------------------------ reports
def create_report(conn, actor, booking_id, kind, body, target_room=None) -> dict:
    decision = policy.can(actor, "report:create")
    if not decision.allowed:
        return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    if kind not in config.REPORT_KINDS:
        return {"ok": False, "http": 422, "code": "INVALID_KIND",
                "message": f"{kind!r} is not a report kind."}
    if not body or not body.strip():
        return {"ok": False, "http": 422, "code": "BODY_REQUIRED", "message": "A report needs a description."}
    booking = conn.execute("SELECT * FROM booking WHERE id=?", (booking_id,)).fetchone()
    if booking is None:
        return {"ok": False, "http": 404, "code": "NOT_FOUND", "message": "No such reservation."}
    if booking["status"] == "CANCELLED" and kind != "CANCELLED_STILL_SHOWING":
        pass  # a cancellation can still be reported, just not as a clash
    existing = conn.execute(
        "SELECT * FROM report WHERE booking_id=? AND kind=? AND status='OPEN'",
        (booking_id, kind)).fetchone()
    if existing:
        conn.execute("UPDATE report SET report_count=report_count+1 WHERE id=?", (existing["id"],))
        conn.execute("INSERT INTO report_entry (report_id, author, body, at) VALUES (?,?,?,?)",
                     (existing["id"], actor.id, body, now()))
        conn.execute(
            """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
               VALUES (?,?,?,?,?,?,?)""",
            (actor.id, "report:merge", "report", str(existing["id"]), None,
             json.dumps({"count": existing["report_count"] + 1}), now()))
        return {"ok": True, "http": 200, "code": "MERGED", "report_id": existing["id"],
                "merged": True, "count": existing["report_count"] + 1,
                "message": "Merged into the open report for this reservation."}
    cur = conn.execute(
        """INSERT INTO report (booking_id, kind, status, reporter, created_at)
           VALUES (?,?,?,?,?)""",
        (booking_id, kind, "OPEN", actor.id, now()))
    conn.execute("INSERT INTO report_entry (report_id, author, body, at) VALUES (?,?,?,?)",
                 (cur.lastrowid, actor.id, body, now()))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor.id, "report:create", "report", str(cur.lastrowid), None,
         json.dumps({"booking": booking_id, "kind": kind}), now()))
    return {"ok": True, "http": 201, "code": "OK", "report_id": cur.lastrowid, "merged": False,
            "count": 1}


def comment(conn, actor, booking_id, body) -> dict:
    decision = policy.can(actor, "report:comment")
    if not decision.allowed:
        return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    if not body or not body.strip():
        return {"ok": False, "http": 422, "code": "BODY_REQUIRED", "message": "A comment needs text."}
    report = conn.execute(
        "SELECT * FROM report WHERE booking_id=? AND status='OPEN'", (booking_id,)).fetchone()
    if report is None:
        cur = conn.execute(
            """INSERT INTO report (booking_id, kind, status, reporter, created_at)
               VALUES (?,?,?,?,?)""", (booking_id, "OTHER", "OPEN", actor.id, now()))
        report_id = cur.lastrowid
    else:
        report_id = report["id"]
    conn.execute("INSERT INTO report_entry (report_id, author, body, at) VALUES (?,?,?,?)",
                 (report_id, actor.id, body, now()))
    return {"ok": True, "http": 201, "code": "OK", "report_id": report_id}


def resolve(conn, actor, report_id, resolution) -> dict:
    decision = policy.can(actor, "report:resolve")
    if not decision.allowed:
        return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    report = conn.execute("SELECT * FROM report WHERE id=?", (report_id,)).fetchone()
    if report is None:
        return {"ok": False, "http": 404, "code": "NOT_FOUND", "message": "No such report."}
    if report["status"] == "RESOLVED":
        return {"ok": False, "http": 409, "code": "ALREADY_RESOLVED", "message": "That report is already resolved."}
    conn.execute(
        "UPDATE report SET status='RESOLVED', resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
        (resolution, actor.id, now(), report_id))
    reporters = [r["author"] for r in conn.execute(
        "SELECT DISTINCT author FROM report_entry WHERE report_id=?", (report_id,))]
    for person in reporters:
        conn.execute(
            """INSERT INTO notification (user_id, channel, payload, status, attempts, created_at)
               VALUES (?,?,?,?,?,?)""",
            (person, "EMAIL", json.dumps({"report": report_id, "resolution": resolution}),
             "QUEUED", 0, now()))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor.id, "report:resolve", "report", str(report_id), json.dumps({"status": "OPEN"}),
         json.dumps({"status": "RESOLVED", "resolution": resolution}), now()))
    return {"ok": True, "http": 200, "code": "OK", "notified": len(reporters)}


def open_reports(conn):
    return [dict(r) for r in conn.execute(
        """SELECT rp.*, b.room_code, b.start_at, b.end_at, b.section_code, b.status AS booking_status
           FROM report rp LEFT JOIN booking b ON b.id = rp.booking_id
           WHERE rp.status='OPEN' ORDER BY rp.report_count DESC, rp.id""")]


def report_thread(conn, report_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM report_entry WHERE report_id=? ORDER BY id", (report_id,))]


# ------------------------------------------------------------------ outbox
def deliver_notifications(conn, fail_first=0):
    """A scheduled job drains the outbox. A mail failure never undoes a booking."""
    rows = conn.execute("SELECT * FROM notification WHERE status='QUEUED' ORDER BY id").fetchall()
    sent = failed = 0
    for i, row in enumerate(rows):
        attempts = row["attempts"] + 1
        if i < fail_first:
            conn.execute("UPDATE notification SET status='FAILED', attempts=? WHERE id=?",
                         (attempts, row["id"]))
            failed += 1
        else:
            conn.execute(
                "UPDATE notification SET status='SENT', attempts=?, sent_at=? WHERE id=?",
                (attempts, now(), row["id"]))
            sent += 1
    return {"sent": sent, "failed": failed}


def notification_stats(conn):
    rows = conn.execute("SELECT status, COUNT(*) c FROM notification GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


# ------------------------------------------------------------------ room data
EDITABLE_ROOM_FIELDS = ("capacity", "exam_capacity", "room_type", "bookable",
                        "accessibility", "permitted_uses", "features", "notes",
                        "unconfirmed")


def update_room(conn, actor, code, **fields) -> dict:
    """Correcting the register. Five facts were inferred, not stated, and each
    can be corrected in one click (section 5.3)."""
    decision = policy.can(actor, "room:edit")
    if not decision.allowed:
        return {"ok": False, "http": 403, "code": "FORBIDDEN", "message": decision.reason}
    room = availability.room_by_code(conn, code)
    if room is None:
        return {"ok": False, "http": 404, "code": "ROOM_NOT_FOUND", "message": "No such room."}
    updates = {k: v for k, v in fields.items() if k in EDITABLE_ROOM_FIELDS}
    if not updates:
        return {"ok": False, "http": 422, "code": "NOTHING_TO_CHANGE", "message": "No editable field was given."}
    if "capacity" in updates and int(updates["capacity"]) < 0:
        return {"ok": False, "http": 422, "code": "INVALID_CAPACITY", "message": "Capacity cannot be negative."}
    if "exam_capacity" in updates and "capacity" in updates:
        if int(updates["exam_capacity"]) > int(updates["capacity"]):
            return {"ok": False, "http": 422, "code": "INVALID_CAPACITY",
                    "message": "Spaced capacity cannot exceed nominal capacity."}
    if updates.get("unconfirmed") is not None:
        updates["unconfirmed"] = 1 if updates["unconfirmed"] else 0
    before = {k: room[k] for k in updates}
    assignments = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE room SET {assignments} WHERE code=?",
                 (*[updates[k] for k in updates], code))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor.id, "room:edit", "room", code, json.dumps(before, default=str),
         json.dumps(updates, default=str), now()))
    return {"ok": True, "http": 200, "code": "OK", "before": before, "after": updates}


def confirm_room(conn, actor, code, capacity=None, exam_capacity=None) -> dict:
    """Accept the inferred values, or replace them, and clear the flag."""
    room = availability.room_by_code(conn, code)
    if room is None:
        return {"ok": False, "http": 404, "code": "ROOM_NOT_FOUND", "message": "No such room."}
    fields = {"unconfirmed": 0}
    if capacity is not None:
        fields["capacity"] = int(capacity)
    if exam_capacity is not None:
        fields["exam_capacity"] = int(exam_capacity)
    return update_room(conn, actor, code, **fields)


def unconfirmed_rooms(conn):
    return [dict(r) for r in conn.execute(
        """SELECT r.*, f.building_code, f.level AS floor_level
           FROM room r JOIN floor f ON f.id=r.floor_id
           WHERE r.unconfirmed=1 ORDER BY r.code""")]
