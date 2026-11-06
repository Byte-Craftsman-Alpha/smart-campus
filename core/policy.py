"""One decision point for the whole application.

`can()` returns not only whether an action is permitted but why it was refused
and whether it needs approval instead (section 5.4). Every surface calls it
before doing any work, and the negative cells of the permission matrix are
tested as hard as the positive ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import config, intervals


@dataclass(frozen=True)
class Actor:
    id: str
    role: str            # student | faculty | admin
    name: str
    section: str | None = None      # students: their own section
    faculty_id: str | None = None   # faculty: their faculty row
    home_building: str = "IET"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    requires_approval: bool = False

    def __bool__(self) -> bool:
        return self.allowed


ALLOW = Decision(True)


def deny(reason: str) -> Decision:
    return Decision(False, reason)


# ------------------------------------------------------------------ actions
#: action -> (student, faculty, admin) as TRUE / FALSE / "own" / "approval"
MATRIX = {
    "schedule:view":        ("yes", "yes", "yes"),
    "rooms:search":         ("yes", "yes", "yes"),
    "booking:create":       ("no", "yes", "yes"),
    "booking:create_gated": ("no", "approval", "yes"),
    "booking:approve":      ("no", "no", "yes"),
    "booking:reschedule":   ("no", "own", "yes"),
    "booking:cancel":       ("no", "own", "yes"),
    "booking:early_release": ("no", "own", "yes"),
    "booking:displace":     ("no", "no", "yes"),
    "notice:publish_section": ("no", "own", "yes"),
    "notice:publish_campus": ("no", "no", "yes"),
    "report:create":        ("yes", "yes", "yes"),
    "report:comment":       ("yes", "yes", "yes"),
    "report:resolve":       ("no", "no", "yes"),
    "room:edit":            ("no", "no", "yes"),
    "room:close":           ("no", "no", "yes"),
    "policy:edit":          ("no", "no", "yes"),
    "audit:read":           ("no", "own", "yes"),
    "demo:reset":           ("no", "no", "yes"),
}

_ACTION_LABEL = {
    "schedule:view": "view a section schedule",
    "rooms:search": "search room availability",
    "booking:create": "reserve a room",
    "booking:create_gated": "request the seminar hall, the library or a large event",
    "booking:approve": "approve a reservation",
    "booking:reschedule": "reschedule a reservation",
    "booking:cancel": "cancel a reservation",
    "booking:early_release": "release the rest of a period",
    "booking:displace": "displace a reservation",
    "notice:publish_section": "publish a notice to a section",
    "notice:publish_campus": "publish a campus-wide notice",
    "report:create": "report a problem",
    "report:comment": "comment on a reservation",
    "report:resolve": "resolve a report",
    "room:edit": "correct room data",
    "room:close": "close a room",
    "policy:edit": "change policy",
    "audit:read": "read the audit trail",
    "demo:reset": "reset demonstration data",
}


def can(actor: Actor, action: str, resource=None) -> Decision:
    """The single authorisation function."""
    if action not in MATRIX:
        return deny(f"Unknown action {action!r}.")

    col = {"student": 0, "faculty": 1, "admin": 2}.get(actor.role)
    if col is None:
        return deny("Unknown role.")

    rule = MATRIX[action][col]
    label = _ACTION_LABEL[action]

    if rule == "no":
        return deny(f"A {actor.role} may not {label}.")
    if rule == "approval":
        return Decision(True, None, requires_approval=True)
    if rule == "own":
        if resource is None:
            return deny("No record was given, so ownership cannot be established.")
        owner_id = _owner_of(resource)
        if owner_id is None:
            return deny(f"A {actor.role} may only {label} their own record.")
        if owner_id != actor.id and owner_id != actor.faculty_id:
            return deny(f"A {actor.role} may only {label} their own record; this one belongs to {owner_id}.")
        return ALLOW
    return ALLOW


def _owner_of(resource) -> str | None:
    if isinstance(resource, dict):
        return (resource.get("created_by") or resource.get("faculty_id")
                or resource.get("owner") or resource.get("id"))
    for attr in ("created_by", "faculty_id", "owner", "id"):
        if hasattr(resource, attr):
            return getattr(resource, attr)
    return None


def gate_reason(room_row, headcount: int, purpose: str) -> str | None:
    """Why a request needs an administrator, or None when it does not."""
    if room_row["room_type"] in config.GATED_ROOM_TYPES:
        return f"{room_row['label']} is {room_row['room_type'].lower()} space and needs administrative approval"
    if purpose == "EVENT" and headcount >= 100:
        return f"an event for {headcount} people is above the approval threshold"
    if room_row["unconfirmed"]:
        return "the room record is still unconfirmed, so the booking is held for review"
    return None


# ------------------------------------------------------------------ settings
def get_setting(conn, key: str):
    row = conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    if row is None:
        raw = config.DEFAULT_SETTINGS.get(key)
    else:
        raw = row["value"]
    default = config.DEFAULT_SETTINGS.get(key)
    if isinstance(default, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(default, int):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default
    return raw


def all_settings(conn) -> dict:
    return {k: get_setting(conn, k) for k in config.DEFAULT_SETTINGS}


def set_setting(conn, key: str, value, actor: str) -> dict:
    """Changing a setting writes an audit record and keeps the previous value."""
    if key not in config.DEFAULT_SETTINGS:
        raise KeyError(f"unknown setting {key!r}")
    old = get_setting(conn, key)
    stamp = datetime.now().strftime(intervals.FMT)
    conn.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), stamp))
    conn.execute(
        "INSERT INTO setting_history (key, old_value, new_value, actor, at) VALUES (?,?,?,?,?)",
        (key, str(old), str(value), actor, stamp))
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES (?,?,?,?,?,?,?)""",
        (actor, "policy:edit", "setting", key, str(old), str(value), stamp))
    return {"key": key, "old": old, "new": value}


def settings_history(conn, key=None):
    if key:
        return conn.execute(
            "SELECT * FROM setting_history WHERE key=? ORDER BY id DESC", (key,)).fetchall()
    return conn.execute("SELECT * FROM setting_history ORDER BY id DESC").fetchall()
