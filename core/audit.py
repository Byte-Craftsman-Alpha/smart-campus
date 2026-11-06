"""The audit trail, and the replay that reconstructs a room's past state."""
from __future__ import annotations

import json
from datetime import datetime

from . import intervals

_EVENT_STATUS = {
    "CREATED": None,          # status is carried in the detail prefix
    "APPROVAL_REQUESTED": "PENDING_APPROVAL",
    "APPROVED": "CONFIRMED",
    "REJECTED": "REJECTED",
    "CANCELLED": "CANCELLED",
    "RESCHEDULED": None,
    "EARLY_RELEASE": None,
    "DISPLACED": "DISPLACED",
    "COMPLETED": "COMPLETED",
}


def trail(conn, limit=200, actor=None, entity=None, action=None):
    sql = "SELECT * FROM audit_event WHERE 1=1"
    args = []
    if actor:
        sql += " AND actor = ?"
        args.append(actor)
    if entity:
        sql += " AND entity = ?"
        args.append(entity)
    if action:
        sql += " AND action LIKE ?"
        args.append(action + "%")
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def events_for_booking(conn, booking_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM booking_event WHERE booking_id=? ORDER BY id", (booking_id,))]


def replay_room(conn, room_code, at) -> dict:
    """Reconstruct the room's state at an instant by replaying booking events.

    Nothing is recomputed from current rows: the events are the record.
    """
    cutoff = intervals.parse_dt(at)
    events = conn.execute(
        """SELECT e.*, b.room_code AS current_room, b.start_at, b.end_at, b.section_code,
                  b.purpose, b.headcount, b.faculty_id
           FROM booking_event e JOIN booking b ON b.id = e.booking_id
           WHERE e.at <= ? ORDER BY e.id""", (intervals.to_db(cutoff),)).fetchall()

    state = {}   # booking_id -> {status, room, start, end, ...}
    for ev in events:
        bid = ev["booking_id"]
        row = state.setdefault(bid, {
            "booking_id": bid, "room": ev["current_room"], "status": None,
            "start": ev["start_at"], "end": ev["end_at"],
            "section": ev["section_code"], "purpose": ev["purpose"],
            "headcount": ev["headcount"], "history": [],
        })
        detail = ev["detail"] or ""
        status = _EVENT_STATUS.get(ev["event_type"])
        if ev["event_type"] == "CREATED":
            head = detail.split(" ")[0].upper()
            status = head if head in ("CONFIRMED", "PENDING_APPROVAL") else "CONFIRMED"
        if status:
            row["status"] = status
        row["history"].append({"at": ev["at"], "event": ev["event_type"], "detail": detail})

    # An instant is not an interval: containment, not overlap, is the question.
    occupying = [b for b in state.values()
                 if b["room"] == room_code
                 and b["status"] in ("CONFIRMED", "PENDING_APPROVAL", "DISPLACED")
                 and intervals.parse_dt(b["start"]) <= cutoff < intervals.parse_dt(b["end"])]
    return {
        "room": room_code,
        "at": intervals.to_db(cutoff),
        "occupying": occupying,
        "free": not occupying,
        "replayed_events": len(events),
        "all_bookings_seen": len(state),
    }


def replay_queue_board(conn, at) -> list[dict]:
    """What every room looked like at an instant, from events alone."""
    rows = []
    for room in conn.execute("SELECT code, label FROM room WHERE bookable=1 ORDER BY code"):
        st = replay_room(conn, room["code"], at)
        rows.append({"room": room["code"], "label": room["label"],
                     "free": st["free"], "occupying": st["occupying"]})
    return rows


def _coerce(state):
    """Audit states are JSON, but older rows and hand-written ones are not."""
    if state is None:
        return None
    if isinstance(state, dict):
        return state
    if not isinstance(state, str):
        return {"value": state}
    try:
        parsed = json.loads(state)
    except (TypeError, ValueError):
        return {"value": state}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def diff(before, after) -> list[tuple[str, str, str]]:
    """Field-level difference for the audit view."""
    b, a = _coerce(before), _coerce(after)
    if b is None or a is None:
        return []
    out = []
    for key in sorted(set(b) | set(a)):
        if b.get(key) != a.get(key):
            out.append((key, str(b.get(key)), str(a.get(key))))
    return out
