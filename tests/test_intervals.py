"""TC-01..TC-14: interval arithmetic, snapping and the half-open rule."""
from datetime import datetime, timedelta

import pytest

from core import intervals


def dt(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def test_tc01_back_to_back_does_not_overlap():
    """Edge case: one ends at 11:00, the next begins at 11:00."""
    assert intervals.overlaps(dt("2026-11-10 10:00"), dt("2026-11-10 11:00"),
                              dt("2026-11-10 11:00"), dt("2026-11-10 11:55")) is False


def test_tc02_one_minute_overlap_is_an_overlap():
    assert intervals.overlaps(dt("2026-11-10 10:00"), dt("2026-11-10 11:00"),
                              dt("2026-11-10 10:59"), dt("2026-11-10 11:55")) is True


def test_tc03_contained_interval_overlaps():
    assert intervals.overlaps(dt("2026-11-10 09:00"), dt("2026-11-10 12:00"),
                              dt("2026-11-10 10:00"), dt("2026-11-10 11:00")) is True


def test_tc04_identical_intervals_overlap():
    a = (dt("2026-11-10 10:00"), dt("2026-11-10 11:00"))
    assert intervals.overlaps(*a, *a) is True


def test_tc05_parse_accepts_iso_with_t_and_without():
    assert intervals.parse_dt("2026-11-10T10:00") == intervals.parse_dt("2026-11-10 10:00")


def test_tc06_parse_rejects_nonsense():
    with pytest.raises(intervals.IntervalError):
        intervals.parse_dt("half past ten")


def test_tc07_snap_down_and_up():
    t = dt("2026-11-10 10:07")
    assert intervals.snap(t, 5, "down") == dt("2026-11-10 10:05")
    assert intervals.snap(t, 5, "up") == dt("2026-11-10 10:10")


def test_tc08_snap_leaves_aligned_values_alone():
    t = dt("2026-11-10 10:15")
    assert intervals.snap(t, 5, "down") == t == intervals.snap(t, 5, "up")


def test_tc09_subtract_produces_the_remainder():
    """The arithmetic behind early release."""
    target = (dt("2026-11-10 10:00"), dt("2026-11-10 11:00"))
    blockers = [(dt("2026-11-10 10:20"), dt("2026-11-10 10:40"))]
    assert intervals.subtract(target, blockers) == [
        (dt("2026-11-10 10:00"), dt("2026-11-10 10:20")),
        (dt("2026-11-10 10:40"), dt("2026-11-10 11:00")),
    ]


def test_tc10_subtract_full_cover_returns_nothing():
    target = (dt("2026-11-10 10:00"), dt("2026-11-10 11:00"))
    assert intervals.subtract(target, [target]) == []


def test_tc11_subtract_ignores_blockers_outside():
    target = (dt("2026-11-10 10:00"), dt("2026-11-10 11:00"))
    blockers = [(dt("2026-11-10 12:00"), dt("2026-11-10 13:00"))]
    assert intervals.subtract(target, blockers) == [target]


def test_tc12_merge_collapses_touching_intervals():
    merged = intervals.merge([("2026-11-10 10:00", "2026-11-10 10:30"),
                              ("2026-11-10 10:30", "2026-11-10 11:00")])
    assert merged == [(dt("2026-11-10 10:00"), dt("2026-11-10 11:00"))]


def test_tc13_duration_and_validity():
    assert intervals.duration_minutes("2026-11-10 10:00", "2026-11-10 10:55") == 55
    assert intervals.valid("2026-11-10 10:00", "2026-11-10 10:55") is True
    assert intervals.valid("2026-11-10 11:00", "2026-11-10 11:00") is False


def test_tc14_formatting_is_human_readable():
    text = intervals.fmt_range("2026-11-10 10:00", "2026-11-10 10:55")
    assert "10:00" in text and "10:55" in text and "–" in text
