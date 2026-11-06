"""TC-79..TC-96: the edge cases of section 10, plus the validation boundaries
that guard them."""
from datetime import date, datetime, timedelta

import pytest

from core import availability, booking, intervals, policy, records


def window(day, start="10:00", minutes=55):
    s = intervals.combine(day, start)
    return s, s + timedelta(minutes=minutes)


def test_tc79_back_to_back_reservations_both_stand(conn, faculty, day):
    end_of_first = intervals.combine(day, "11:00")
    first = booking.create(conn, faculty, "IET18", intervals.combine(day, "10:05"),
                           end_of_first, "CLASS", 75, "CSE-4A")
    assert first["ok"]
    second = booking.create(conn, faculty, "IET18", end_of_first,
                            end_of_first + timedelta(minutes=55), "CLASS", 75, "CSE-4B")
    assert second["ok"], second


def test_tc80_one_minute_overlap_is_refused(conn, faculty, day):
    first = booking.create(conn, faculty, "IET18", intervals.combine(day, "10:05"),
                           intervals.combine(day, "11:00"), "CLASS", 75, "CSE-4A")
    assert first["ok"]
    second = booking.create(conn, faculty, "IET18", intervals.combine(day, "10:55"),
                            intervals.combine(day, "11:50"), "CLASS", 75, "CSE-4B")
    assert second["code"] == "ROOM_ALREADY_BOOKED"


def test_tc81_examination_beyond_spaced_capacity_is_refused_with_a_split(conn, faculty, day):
    """Edge case: a request that fits the room but exceeds its spaced capacity."""
    s, e = window(day, "10:00", 110)
    outcome = booking.create(conn, faculty, "IET20", s, e, "EXAM", 75)
    assert outcome["code"] == "EXAM_CAPACITY_EXCEEDED"
    assert outcome["split"], "the refusal must propose a split sitting"
    seats = sum(part["seats"] for part in outcome["split"])
    assert seats == 75


def test_tc82_nominal_capacity_is_still_refused_when_exceeded(conn, faculty, day):
    s, e = window(day, "11:45")
    outcome = booking.create(conn, faculty, "LH03", s, e, "CLASS", 60)
    assert outcome["code"] == "CAPACITY_EXCEEDED"
    assert "45" in outcome["message"]


def test_tc83_headcount_zero_and_negative_are_refused(conn, faculty, day):
    s, e = window(day, "13:30")
    assert booking.create(conn, faculty, "LH04", s, e, "CLASS", 0)["code"] == "INVALID_HEADCOUNT"
    assert booking.create(conn, faculty, "LH04", s, e, "CLASS", -5)["code"] == "INVALID_HEADCOUNT"


def test_tc84_headcount_beyond_the_model_is_refused(conn, faculty, day):
    s, e = window(day, "13:30")
    assert booking.create(conn, faculty, "IET32", s, e, "SEMINAR", 2000)["code"] == "INVALID_HEADCOUNT"


def test_tc85_end_before_start_is_refused(conn, faculty, day):
    s, e = window(day, "14:25")
    assert booking.create(conn, faculty, "IET25", e, s, "CLASS", 75)["code"] == "INVALID_WINDOW"


def test_tc86_zero_length_window_is_refused(conn, faculty, day):
    s, _ = window(day, "14:25")
    assert booking.create(conn, faculty, "IET25", s, s, "CLASS", 75)["code"] == "INVALID_WINDOW"


def test_tc87_off_grid_times_are_refused(conn, faculty, day):
    s = intervals.combine(day, "14:25") + timedelta(minutes=2)
    assert booking.create(conn, faculty, "IET25", s, s + timedelta(minutes=55),
                          "CLASS", 75)["code"] == "INVALID_WINDOW"


def test_tc88_window_in_the_past_is_refused(conn, faculty):
    past = datetime.now() - timedelta(days=1)
    outcome = booking.create(conn, faculty, "IET25", past, past + timedelta(minutes=55), "CLASS", 75)
    assert outcome["code"] == "INVALID_WINDOW"


def test_tc89_window_beyond_the_horizon_is_refused(conn, faculty):
    far = intervals.snap(datetime.now() + timedelta(
        days=int(policy.get_setting(conn, "booking_horizon_days")) + 5), 5, "up")
    outcome = booking.create(conn, faculty, "IET25", far, far + timedelta(minutes=55), "CLASS", 75)
    assert outcome["code"] == "INVALID_WINDOW"
    assert "horizon" in outcome["message"]


def test_tc90_lead_time_is_respected(conn, faculty, admin):
    """A window that closes inside the lead time is refused; one that ends later
    is allowed even if it starts almost immediately."""
    policy.set_setting(conn, "min_lead_time_minutes", 120, admin.id)
    soon = intervals.snap(datetime.now() + timedelta(minutes=30), 5, "up")
    refused = booking.create(conn, faculty, "IET25", soon, soon + timedelta(minutes=55),
                             "CLASS", 75)
    assert refused["code"] == "INVALID_WINDOW"
    assert "lead time" in refused["message"]
    later = intervals.snap(datetime.now() + timedelta(minutes=150), 5, "up")
    allowed = booking.create(conn, faculty, "IET25", later, later + timedelta(minutes=55),
                             "CLASS", 75)
    assert allowed["ok"], allowed


def test_tc91_unknown_room_is_a_404(conn, faculty, day):
    s, e = window(day, "10:00")
    outcome = booking.create(conn, faculty, "XX99", s, e, "CLASS", 10)
    assert outcome["http"] == 404 and outcome["code"] == "ROOM_NOT_FOUND"


def test_tc92_office_is_not_bookable(conn, faculty, day):
    s, e = window(day, "10:00")
    outcome = booking.create(conn, faculty, "TO", s, e, "INTERVIEW", 5)
    assert outcome["code"] == "ROOM_NOT_BOOKABLE"


def test_tc93_wrong_purpose_for_the_room_is_refused(conn, faculty, day):
    s, e = window(day, "10:00")
    outcome = booking.create(conn, faculty, "IET32", s, e, "PRACTICAL", 100)
    assert outcome["code"] == "PURPOSE_NOT_PERMITTED"


def test_tc94_unknown_purpose_is_refused(conn, faculty, day):
    s, e = window(day, "10:00")
    outcome = booking.create(conn, faculty, "IET20", s, e, "PICNIC", 75)
    assert outcome["code"] == "INVALID_PURPOSE"


def test_tc95_closure_over_existing_bookings_is_refused_until_cleared(conn, faculty, admin, day):
    """Edge case: a room closed for repair while reservations exist inside."""
    s, e = window(day, "15:20")
    bid = booking.create(conn, faculty, "IET23", s, e, "CLASS", 75, "MECH-4A")["booking"]["id"]
    refused = records.create_closure(conn, admin, "IET23",
                                     intervals.combine(day, "15:00"),
                                     intervals.combine(day, "16:15"), "Repair")
    assert refused["code"] == "CLOSURE_WOULD_BREAK_BOOKINGS"
    assert refused["affected"] and refused["affected"][0]["id"] == bid
    booking.cancel(conn, admin, bid, "Room needed for repair")
    allowed = records.create_closure(conn, admin, "IET23",
                                     intervals.combine(day, "15:00"),
                                     intervals.combine(day, "16:15"), "Repair")
    assert allowed["ok"]


def test_tc96_closure_over_a_timetable_slot_is_allowed_but_still_warns(conn, admin):
    slot = conn.execute("SELECT * FROM timetable_slot LIMIT 1").fetchone()
    grid = availability.period_grid(conn)
    period = next(p for p in grid if p["id"] == slot["period"])
    outcome = records.create_closure(conn, admin, slot["room_code"],
                                     intervals.combine(date.today(), period["start"]),
                                     intervals.combine(date.today(), period["end"]),
                                     "Painting", force=True)
    assert outcome["ok"], "a closure may not be blocked by a recurring slot, but it is recorded"
