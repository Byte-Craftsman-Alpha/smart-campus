"""TC-51..TC-78: creation, approval, refusal, cancellation, reschedule, early
release, displacement and weekly series."""
from datetime import datetime, timedelta

import pytest

from core import booking, intervals, policy


def window(day, start="10:00", minutes=55):
    s = intervals.combine(day, start)
    return s, s + timedelta(minutes=minutes)


def test_tc51_faculty_creates_a_confirmed_booking(conn, faculty, day):
    s, e = window(day, "15:20")
    result = booking.create(conn, faculty, "IET25", s, e, "CLASS", 75, "CSE-2A",
                            idempotency_key="tc51")
    assert result["ok"] and result["http"] == 201
    row = result["booking"]
    assert row["status"] == "CONFIRMED"
    assert row["room_code"] == "IET25"
    assert row["is_test"] == 1, "demonstration rows carry the flag"


def test_tc52_student_cannot_create(conn, student, day):
    s, e = window(day, "16:15")
    result = booking.create(conn, student, "IET25", s, e, "CLASS", 75, "CSE-2A")
    assert result["http"] == 403 and result["code"] == "FORBIDDEN"
    assert "may not" in result["message"]


def test_tc53_room_conflict_returns_three_alternatives(conn, faculty, day):
    s, e = window(day, "11:45")
    first = booking.create(conn, faculty, "IET18", s, e, "CLASS", 75, "CSE-1A")
    assert first["ok"]
    second = booking.create(conn, faculty, "IET18", s, e, "CLASS", 75, "CSE-1B")
    assert second["http"] == 409 and second["code"] == "ROOM_ALREADY_BOOKED"
    assert len(second["alternatives"]) == 3
    for alt in second["alternatives"]:
        assert alt["room"] != "IET18"
        assert alt["reasons"], "an alternative without a reason is a guess"


def test_tc54_section_cannot_be_in_two_rooms(conn, faculty, other_faculty, day):
    s, e = window(day, "10:50")
    assert booking.create(conn, faculty, "IET19", s, e, "CLASS", 75, "CSE-4A")["ok"]
    clash = booking.create(conn, other_faculty, "IET17", s, e, "CLASS", 75, "CSE-4A")
    assert clash["code"] == "SECTION_DOUBLE_BOOKED"
    assert "CSE-4A" in clash["message"]


def test_tc55_faculty_cannot_be_in_two_rooms(conn, faculty, day):
    s, e = window(day, "14:25")
    assert booking.create(conn, faculty, "IET28", s, e, "CLASS", 75, "AIDS-3A")["ok"]
    clash = booking.create(conn, faculty, "IET29", s, e, "CLASS", 75, "IT-1A")
    assert clash["code"] == "FACULTY_DOUBLE_BOOKED"
    assert clash["alternatives"]


def test_tc56_idempotency_key_returns_the_original(conn, faculty, day):
    """Edge case: the same person double-clicks confirm."""
    s, e = window(day, "09:00")
    first = booking.create(conn, faculty, "IET20", s, e, "CLASS", 75, "MECH-1A",
                           idempotency_key="dup-key")
    second = booking.create(conn, faculty, "IET20", s, e, "CLASS", 75, "MECH-1A",
                            idempotency_key="dup-key")
    assert first["http"] == 201 and second["http"] == 200
    assert first["booking"]["id"] == second["booking"]["id"]
    count = conn.execute("SELECT COUNT(*) c FROM booking WHERE idempotency_key='dup-key'"
                         ).fetchone()["c"]
    assert count == 1


def test_tc57_gated_room_needs_approval_then_can_be_approved(conn, faculty, admin, day):
    s, e = window(day, "10:00", 110)
    request = booking.create(conn, faculty, "IET32", s, e, "SEMINAR", 150, None)
    assert request["ok"] and request["booking"]["status"] == "PENDING_APPROVAL"
    approved = booking.approve(conn, admin, request["booking"]["id"], "Approved by the registrar")
    assert approved["ok"] and approved["booking"]["status"] == "CONFIRMED"


def test_tc58_faculty_cannot_approve(conn, faculty, day):
    s, e = window(day, "13:30", 110)
    request = booking.create(conn, faculty, "IET32", s, e, "SEMINAR", 150, None)
    refused = booking.approve(conn, faculty, request["booking"]["id"])
    assert refused["http"] == 403


def test_tc59_rejection_needs_a_reason_and_notifies(conn, faculty, admin, day):
    s, e = window(day, "15:20", 110)
    request = booking.create(conn, faculty, "LIB", s, e, "EXAM", 90, None)
    no_reason = booking.reject(conn, admin, request["booking"]["id"], "")
    assert no_reason["code"] == "REASON_REQUIRED"
    rejected = booking.reject(conn, admin, request["booking"]["id"], "Library is in use that hour")
    assert rejected["ok"] and rejected["booking"]["status"] == "REJECTED"
    row = conn.execute("SELECT * FROM booking WHERE id=?", (request["booking"]["id"],)).fetchone()
    assert row["reason"] == "Library is in use that hour"


def test_tc60_cancellation_writes_status_reason_notice_and_notifications(conn, faculty, day):
    s, e = window(day, "16:15")
    created = booking.create(conn, faculty, "LH05", s, e, "CLASS", 45, "ECE-2A")
    bid = created["booking"]["id"]
    outcome = booking.cancel(conn, faculty, bid, "Faculty on duty leave")
    assert outcome["ok"]
    assert outcome["booking"]["status"] == "CANCELLED"
    assert outcome["announcement_id"], "a cancellation publishes a notice"
    notices = conn.execute("SELECT * FROM announcement WHERE supersedes_booking_id=?",
                           (bid,)).fetchall()
    assert notices, "the notice points at the reservation it supersedes"
    queued = conn.execute("SELECT COUNT(*) c FROM notification WHERE status='QUEUED'"
                          ).fetchone()["c"]
    assert queued > 0


def test_tc61_cancellation_is_never_a_delete(conn, faculty, day):
    from core import availability
    s, e = window(day, "09:00")
    free = availability.search(conn, s, e, 45, "CLASS", building="DB")["available"]
    assert free, "the seeded timetable leaves no Deeksha room free at that hour"
    room = free[0]["code"]
    bid = booking.create(conn, faculty, room, s, e, "CLASS", 45, "ECE-2A")["booking"]["id"]
    booking.cancel(conn, faculty, bid, "Room double-booked by the department")
    row = conn.execute("SELECT * FROM booking WHERE id=?", (bid,)).fetchone()
    assert row is not None and row["status"] == "CANCELLED"


def test_tc62_cancellation_requires_a_reason(conn, faculty, day):
    s, e = window(day, "10:50")
    bid = booking.create(conn, faculty, "LH07", s, e, "CLASS", 45, "ECE-4A")["booking"]["id"]
    outcome = booking.cancel(conn, faculty, bid, "   ")
    assert outcome["code"] == "REASON_REQUIRED"


def test_tc63_cannot_cancel_someone_elses_booking(conn, faculty, other_faculty, day):
    s, e = window(day, "11:45")
    bid = booking.create(conn, other_faculty, "IET24", s, e, "CLASS", 75, "AIDS-2A"
                         )["booking"]["id"]
    refused = booking.cancel(conn, faculty, bid, "I want the room")
    assert refused["http"] == 403 and "own" in refused["message"]


def test_tc64_cancelling_twice_is_refused(conn, faculty, day):
    s, e = window(day, "13:30")
    bid = booking.create(conn, faculty, "IET30", s, e, "CLASS", 75, "AIDS-1A")["booking"]["id"]
    assert booking.cancel(conn, faculty, bid, "First cancellation")["ok"]
    again = booking.cancel(conn, faculty, bid, "Second attempt")
    assert again["code"] == "NOT_LIVE"


def test_tc65_cancellation_after_the_start_needs_an_administrator(conn, admin, day):
    """Edge case: cancellation attempted after the start time."""
    past_start = datetime.now() - timedelta(hours=2)
    past_end = past_start + timedelta(minutes=55)
    # No section and no faculty row: this test is about the clock, and the seeded
    # demonstration bookings already occupy real faculty at nearby times.
    conn.execute(
        """INSERT INTO booking (room_code, section_code, faculty_id, start_at, end_at, purpose,
                                headcount, status, is_test, version, created_by, created_at, updated_at)
           VALUES ('IET22',NULL,NULL,?,?,'CLASS',75,'CONFIRMED',1,1,'FAC-01',?,?)""",
        (intervals.to_db(past_start), intervals.to_db(past_end),
         intervals.to_db(past_start), intervals.to_db(past_start)))
    bid = conn.execute("SELECT MAX(id) m FROM booking").fetchone()["m"]
    faculty_actor = policy.Actor("a.verma@iet.example.edu", "faculty", "Dr A. Verma",
                                 faculty_id="FAC-01")
    refused = booking.cancel(conn, faculty_actor, bid, "Late change")
    assert refused["code"] == "AFTER_START" and refused["http"] == 403
    allowed = booking.cancel(conn, admin, bid, "Correction after the fact")
    assert allowed["ok"]


def test_tc66_reschedule_moves_a_reservation(conn, faculty, day):
    s, e = window(day, "15:20")
    bid = booking.create(conn, faculty, "IET23", s, e, "CLASS", 75, "MECH-3A")["booking"]["id"]
    new_start = intervals.combine(day, "16:15")
    outcome = booking.reschedule(conn, faculty, bid, new_start,
                                 new_start + timedelta(minutes=55), "Room needed elsewhere")
    assert outcome["ok"]
    assert outcome["booking"]["start_at"] == intervals.to_db(new_start)


def test_tc67_reschedule_into_an_occupied_window_is_refused_with_alternatives(conn, faculty, other_faculty, day):
    from core import availability
    later_start = intervals.combine(day, "14:25")
    later_end = intervals.combine(day, "15:20")
    free_rooms = [r["code"] for r in availability.search(
        conn, later_start, later_end, 75, "CLASS", building="IET")["available"]]
    assert free_rooms, "no free IET room at 14:25"
    room = free_rooms[0]
    booking.create(conn, other_faculty, room, later_start, later_end, "CLASS", 75, "AIDS-4A")
    mine = booking.create(conn, faculty, room, intervals.combine(day, "16:15"),
                          intervals.combine(day, "17:10"), "CLASS", 75, "CSE-2B")
    assert mine["ok"], mine
    refused = booking.reschedule(conn, faculty, mine["booking"]["id"], later_start, later_end)
    assert refused["code"] == "ROOM_ALREADY_BOOKED"
    assert len(refused["alternatives"]) >= 3


def test_tc68_early_release_shortens_and_returns_the_remainder(conn, faculty, day):
    s = intervals.combine(day, "10:00")
    e = intervals.combine(day, "11:00")
    bid = booking.create(conn, faculty, "IET14", s, e, "PRACTICAL", 75, "CSE-1B")["booking"]["id"]
    outcome = booking.early_release(conn, faculty, bid, intervals.combine(day, "10:30"))
    assert outcome["ok"]
    assert outcome["booking"]["end_at"] == intervals.to_db(intervals.combine(day, "10:30"))
    assert outcome["released"] == [intervals.to_db(intervals.combine(day, "10:30")),
                                   intervals.to_db(e)]


def test_tc69_early_release_cannot_lengthen(conn, faculty, day):
    s = intervals.combine(day, "11:45")
    e = intervals.combine(day, "12:40")
    bid = booking.create(conn, faculty, "IET15", s, e, "PRACTICAL", 75, "CSE-2A")["booking"]["id"]
    refused = booking.early_release(conn, faculty, bid, e + timedelta(minutes=10))
    assert refused["code"] == "NOT_SHORTER"


def test_tc70_early_release_cannot_erase_the_whole_reservation(conn, faculty, day):
    s = intervals.combine(day, "13:30")
    e = intervals.combine(day, "14:25")
    bid = booking.create(conn, faculty, "IET16", s, e, "PRACTICAL", 75, "CSE-3B")["booking"]["id"]
    refused = booking.early_release(conn, faculty, bid, s)
    assert refused["code"] == "INVALID_WINDOW"


def test_tc71_displacement_moves_the_room_and_announces(conn, faculty, admin, day):
    s, e = window(day, "09:00")
    bid = booking.create(conn, faculty, "IET28", s, e, "CLASS", 75, "IT-2A")["booking"]["id"]
    outcome = booking.displace(conn, admin, bid, "Director's meeting needs the room",
                               new_room="IET29")
    assert outcome["ok"]
    assert outcome["booking"]["status"] == "DISPLACED"
    assert outcome["booking"]["room_code"] == "IET29"
    notice = conn.execute("SELECT * FROM announcement WHERE supersedes_booking_id=?",
                          (bid,)).fetchone()
    assert notice and "IET29" in notice["body"]


def test_tc72_displacement_requires_a_reason_and_an_admin(conn, faculty, admin, day):
    s, e = window(day, "10:50")
    bid = booking.create(conn, faculty, "IET20", s, e, "CLASS", 75, "CSE-1A")["booking"]["id"]
    assert booking.displace(conn, faculty, bid, "my meeting")["http"] == 403
    assert booking.displace(conn, admin, bid, "")["code"] == "REASON_REQUIRED"


def test_tc73_series_creates_one_booking_per_week(conn, faculty, day):
    from core import availability
    s = intervals.combine(day, "14:25")
    free = availability.search(conn, s, s + timedelta(minutes=55), 45, "CLASS",
                               building="DB")["available"]
    assert free, "no Deeksha room free at 14:25"
    outcome = booking.create_series(conn, faculty, free[0]["code"], s, s + timedelta(minutes=55),
                                    weekday="TUE", weeks=4, purpose="CLASS", headcount=45,
                                    section_code="AIML-2A")
    assert outcome["ok"], outcome
    assert len(outcome["created"]) == 4
    rows = conn.execute("SELECT COUNT(*) c FROM booking WHERE series_id=?",
                        (outcome["series_id"],)).fetchone()["c"]
    assert rows == 4


def test_tc74_series_reports_the_weeks_it_could_not_place(conn, faculty, day):
    from core import availability
    s = intervals.combine(day, "15:20")
    free = availability.search(conn, s, s + timedelta(minutes=55), 45, "CLASS",
                               building="DB")["available"]
    assert free
    room = free[0]["code"]
    # a one-off booking in the second week of the series blocks exactly one week
    booking.create(conn, faculty, room, s + timedelta(weeks=1),
                   s + timedelta(weeks=1, minutes=55), "CLASS", 45, "ECE-1A")
    outcome = booking.create_series(conn, faculty, room, s, s + timedelta(minutes=55),
                                    weekday="WED", weeks=3, purpose="CLASS", headcount=45,
                                    section_code="AIML-3B")
    assert outcome["ok"]
    assert len(outcome["created"]) + len(outcome["failed"]) == 3
    assert outcome["failed"], "the week that collides must be reported, not swallowed"


def test_tc75_cancel_series_cancels_every_live_week(conn, faculty, day):
    s = intervals.combine(day, "16:15")
    outcome = booking.create_series(conn, faculty, "LH11", s, s + timedelta(minutes=55),
                                    weekday="THU", weeks=3, purpose="TUTORIAL", headcount=45,
                                    section_code="ECE-3A")
    cancelled = booking.cancel_series(conn, faculty, outcome["series_id"], "Course ended early")
    assert len(cancelled["cancelled"]) == 3
    live = conn.execute(
        "SELECT COUNT(*) c FROM booking WHERE series_id=? AND status IN ('CONFIRMED','PENDING_APPROVAL')",
        (outcome["series_id"],)).fetchone()["c"]
    assert live == 0


def test_tc76_series_length_is_bounded(conn, faculty, day):
    s = intervals.combine(day, "09:00")
    too_long = booking.create_series(conn, faculty, "LH12", s, s + timedelta(minutes=55),
                                     weekday="FRI", weeks=30, purpose="CLASS", headcount=45,
                                     section_code="IT-4A")
    assert too_long["code"] == "INVALID_SERIES"


def test_tc77_complete_past_closes_finished_intervals(conn, faculty, day):
    past = datetime.now() - timedelta(days=1)
    conn.execute(
        """INSERT INTO booking (room_code, section_code, faculty_id, start_at, end_at, purpose,
                                headcount, status, is_test, version, created_by, created_at, updated_at)
           VALUES ('IET17','IT-4A','FAC-01',?,?,'CLASS',75,'CONFIRMED',1,1,'FAC-01',?,?)""",
        (intervals.to_db(past), intervals.to_db(past + timedelta(minutes=55)),
         intervals.to_db(past), intervals.to_db(past)))
    assert booking.complete_past(conn) >= 1
    statuses = {r["status"] for r in conn.execute(
        "SELECT status FROM booking WHERE end_at < ?", (intervals.to_db(datetime.now()),))}
    assert "CONFIRMED" not in statuses


def test_tc78_booking_version_increments_on_every_change(conn, faculty, day):
    s = intervals.combine(day, "10:00")
    bid = booking.create(conn, faculty, "IET19", s, s + timedelta(minutes=55), "CLASS", 75,
                         "CSE-3A")["booking"]["id"]
    booking.reschedule(conn, faculty, bid, s, s + timedelta(minutes=110), "Longer session")
    version = conn.execute("SELECT version FROM booking WHERE id=?", (bid,)).fetchone()["version"]
    assert version >= 2
