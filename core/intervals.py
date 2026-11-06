"""Interval arithmetic. Pure functions, no database, no framework.

The whole design rests on one decision: an interval is half-open, [start, end).
A reservation ending at 11:00 and one beginning at 11:00 do not collide.
Everything in this module preserves that property.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

FMT = "%Y-%m-%d %H:%M"
FMT_DAY = "%Y-%m-%d"


class IntervalError(ValueError):
    """Raised when a caller hands us something that is not a usable interval."""


# ------------------------------------------------------------------ parsing
def parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0))
    if isinstance(value, str):
        txt = value.strip().replace("T", " ")
        for fmt in (FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(txt, fmt)
            except ValueError:
                continue
    raise IntervalError(f"not a timestamp: {value!r}")


def to_db(dt: datetime) -> str:
    """Canonical string form. ISO minus the 'T', so string order == time order."""
    return dt.strftime(FMT)


def parse_time_of_day(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def combine(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, parse_time_of_day(hhmm))


# ------------------------------------------------------------------ snapping
def snap(dt: datetime, minutes: int = 5, mode: str = "down") -> datetime:
    """Snap to a five-minute grid: tidy data entry, exact comparison."""
    if minutes <= 0:
        return dt
    total = dt.hour * 60 + dt.minute
    if mode == "down":
        total -= total % minutes
    elif mode == "up":
        total += (-total) % minutes
    else:
        total = int(round(total / minutes)) * minutes
    base = datetime.combine(dt.date(), time(0, 0))
    return base + timedelta(minutes=total)


def snap_interval(start: datetime, end: datetime, minutes: int = 5):
    return snap(start, minutes, "down"), snap(end, minutes, "down")


# ------------------------------------------------------------------ algebra
def overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Half-open overlap: shared boundary is not an overlap."""
    a_start, a_end = parse_dt(a_start), parse_dt(a_end)
    b_start, b_end = parse_dt(b_start), parse_dt(b_end)
    return a_start < b_end and b_start < a_end


def intersect(a, b):
    """Return the overlapping interval, or None."""
    a_start, a_end = parse_dt(a[0]), parse_dt(a[1])
    b_start, b_end = parse_dt(b[0]), parse_dt(b[1])
    lo, hi = max(a_start, b_start), min(a_end, b_end)
    return (lo, hi) if lo < hi else None


def subtract(target, blockers):
    """target minus a list of intervals -> list of remaining free intervals.

    This is the function behind "the remainder of the interval returns to the
    pool" in early release, and behind free-window reporting.
    """
    lo, hi = parse_dt(target[0]), parse_dt(target[1])
    if lo >= hi:
        return []
    cuts = []
    for b in blockers:
        piece = intersect((lo, hi), b)
        if piece:
            cuts.append(piece)
    cuts.sort()
    out, cursor = [], lo
    for c_start, c_end in cuts:
        if c_start > cursor:
            out.append((cursor, c_start))
        cursor = max(cursor, c_end)
    if cursor < hi:
        out.append((cursor, hi))
    return out


def merge(intervals):
    """Union of intervals, sorted and non-touching."""
    spans = sorted(
        ((parse_dt(a), parse_dt(b)) for a, b in intervals if parse_dt(a) < parse_dt(b))
    )
    out = []
    for start, end in spans:
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def duration_minutes(start, end) -> int:
    return int((parse_dt(end) - parse_dt(start)).total_seconds() // 60)


def valid(start, end) -> bool:
    try:
        return parse_dt(start) < parse_dt(end)
    except IntervalError:
        return False


def fmt_range(start, end) -> str:
    s, e = parse_dt(start), parse_dt(end)
    return f"{s:%a %d %b, %H:%M}–{e:%H:%M}"


def day_bounds(day: date):
    lo = datetime.combine(day, time(0, 0))
    return lo, lo + timedelta(days=1)


def fee_windows(day: date, periods):
    """The eight teaching periods of the registry grid, as datetimes."""
    return [(combine(day, p["start"]), combine(day, p["end"])) for p in periods]


def hhmm_between(start, end) -> list[str]:
    """Half-hour ticks for a select box, inclusive of both ends."""
    out, cur = [], parse_dt(start)
    end = parse_dt(end)
    while cur <= end:
        out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return out
