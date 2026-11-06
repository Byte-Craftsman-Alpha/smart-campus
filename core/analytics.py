"""The arithmetic of scarcity (section 9), computed from the live register so
the numbers in the document can be re-checked against the running system."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from . import availability, config, intervals, policy


def register_summary(conn) -> dict:
    rooms = availability.rooms(conn, bookable_only=False)
    bookable = [r for r in rooms if r["bookable"]]
    by_room_type = {}
    for r in rooms:
        by_room_type.setdefault(r["room_type"], []).append(r["code"])
    return {
        "rooms_recorded": len(rooms),
        "bookable": len(bookable),
        "offices_or_service": len(rooms) - len(bookable),
        "full_section": sum(1 for r in bookable if r["capacity"] >= 75),
        "exam_capable": sum(1 for r in bookable if r["exam_capacity"] >= 75),
        "smaller_than_section": sum(1 for r in bookable if r["capacity"] < 75),
        "by_room_type": {k: len(v) for k, v in by_room_type.items()},
        "unconfirmed": [r["code"] for r in rooms if r["unconfirmed"]],
        "total_nominal_seats": sum(r["capacity"] for r in bookable),
        "total_exam_seats": sum(r["exam_capacity"] for r in bookable),
    }


def demand_supply(conn) -> dict:
    periods = int(policy.get_setting(conn, "periods_per_day"))
    rooms = register_summary(conn)["bookable"]
    sections = conn.execute("SELECT COUNT(*) c, MAX(strength) s FROM section").fetchone()
    supply = rooms * periods
    out = {"rooms": rooms, "periods": periods, "sections": sections["c"],
           "largest_section": sections["s"], "supply": supply, "rows": []}
    for used in (6, 7, 8):
        demand = sections["c"] * used
        out["rows"].append({
            "periods_per_section": used,
            "demand": demand,
            "utilisation": demand / supply if supply else 0,
            "free": supply - demand,
        })
    busiest = max(out["rows"], key=lambda r: r["utilisation"])
    out["peak_utilisation"] = busiest["utilisation"]
    out["peak_periods"] = busiest["periods_per_section"]
    # the concurrency ceiling: one period cannot host more sections than rooms
    out["concurrency_ceiling"] = out["peak_utilisation"]
    out["oversubscribed_by"] = (sections["c"] / rooms) if rooms else 0
    return out


def live_day_load(conn, day: date) -> dict:
    """Actual occupancy on one day: room-periods consumed by timetable and bookings."""
    grid = availability.period_grid(conn)
    weekday = config.WEEKDAYS[day.weekday()]
    rooms = availability.rooms(conn)
    total = len(rooms) * len(grid)
    used, per_period = 0, {}
    for room in rooms:
        lo = intervals.combine(day, grid[0]["start"])
        hi = intervals.combine(day, grid[-1]["end"])
        windows = availability.occupied_windows(conn, room["code"], lo, hi)
        for p in grid:
            p_start = intervals.combine(day, p["start"])
            p_end = intervals.combine(day, p["end"])
            busy = any(intervals.overlaps(w["start"], w["end"], p_start, p_end) for w in windows)
            if busy:
                used += 1
                per_period[p["id"]] = per_period.get(p["id"], 0) + 1
    peak_period = max(per_period, key=per_period.get) if per_period else None
    peak_value = per_period.get(peak_period, 0) if peak_period else 0
    return {"day": day.isoformat(), "weekday": weekday, "capacity_room_periods": total,
            "used_room_periods": used, "idle_room_periods": total - used,
            "utilisation": used / total if total else 0,
            "per_period": per_period, "peak_period": peak_period,
            "peak_concurrent": peak_value,
            "peak_ratio": (peak_value / len(rooms)) if rooms else 0}


def clash_probability(n_bookings: int, room_terms: int) -> float:
    """P(at least one collision) for n uniform bookings over M room-terms."""
    if room_terms <= 0:
        return 0.0
    pairs = n_bookings * (n_bookings - 1) / 2
    return 1 - (1 - 1 / room_terms) ** pairs


def clash_table(conn) -> dict:
    ds = demand_supply(conn)
    m = ds["supply"]
    rows = []
    for n in (15, 30, 45, 60):
        p = clash_probability(n, m)
        rows.append({"n": n, "probability": p,
                     "sessions": 18 * 6,
                     "expected_clashes": p * 18 * 6})
    return {"room_terms": m, "rows": rows}


def exam_placement(conn) -> dict:
    rooms = [r for r in availability.rooms(conn) if r["bookable"]]
    qualifying = sorted([r for r in rooms if r["exam_capacity"] >= 75],
                        key=lambda r: -r["exam_capacity"])
    sections = conn.execute("SELECT COUNT(*) c FROM section").fetchone()["c"]
    per_day = 3
    if not qualifying:
        return {"qualifying": [], "sittings": None, "days": None, "per_day": per_day}
    sittings = math.ceil(sections / len(qualifying))
    days = math.ceil(sittings / per_day)
    return {
        "qualifying": [{"code": r["code"], "exam_capacity": r["exam_capacity"]} for r in qualifying],
        "sections": sections,
        "sittings": sittings,
        "days": days,
        "per_day": per_day,
        "splittable": sum(1 for r in rooms if r["exam_capacity"] >= 37),
    }


def staff_time(conn) -> dict:
    bookings = conn.execute("SELECT COUNT(*) c FROM booking").fetchone()["c"]
    manual_minutes, system_seconds = 15, 45
    saved_per_booking = manual_minutes - system_seconds / 60
    return {"bookings": bookings,
            "minutes_saved_per_booking": saved_per_booking,
            "hours_saved": bookings * saved_per_booking / 60,
            "semester_projection_hours": 320 * saved_per_booking / 60}


def notification_health(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) c FROM notification GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


def health(conn) -> dict:
    summary = register_summary(conn)
    sections = conn.execute("SELECT COUNT(*) c FROM section").fetchone()["c"]
    bookings = conn.execute("SELECT COUNT(*) c FROM booking").fetchone()["c"]
    live = conn.execute(
        "SELECT COUNT(*) c FROM booking WHERE status IN ('CONFIRMED','PENDING_APPROVAL')"
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM booking WHERE status='PENDING_APPROVAL'").fetchone()["c"]
    reports = conn.execute("SELECT COUNT(*) c FROM report WHERE status='OPEN'").fetchone()["c"]
    return {
        "register": summary,
        "sections": sections,
        "bookings": bookings,
        "live_bookings": live,
        "pending_approvals": pending,
        "open_reports": reports,
        "settings": policy.all_settings(conn),
        "notifications": notification_health(conn),
        "generated_at": datetime.now().strftime(intervals.FMT),
    }
