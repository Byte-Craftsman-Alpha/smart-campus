"""TC-97..TC-116: settings and history, room data confirmation, structured
reports, notices, the outbox and the audit replay."""
from datetime import datetime, timedelta

import pytest

from core import audit, intervals, policy, records


def window(day, start="10:00", minutes=55):
    s = intervals.combine(day, start)
    return s, s + timedelta(minutes=minutes)


def test_tc97_setting_change_writes_history_and_audit(conn, admin):
    before = policy.get_setting(conn, "exam_spacing_factor")
    policy.set_setting(conn, "exam_spacing_factor", 0.6, admin.id)
    after = policy.get_setting(conn, "exam_spacing_factor")
    assert (before, after) == (0.5, 0.6)
    history = policy.settings_history(conn, "exam_spacing_factor")
    assert history and history[0]["new_value"] == "0.6"
    row = conn.execute("SELECT * FROM audit_event WHERE action='policy:edit' ORDER BY id DESC"
                       ).fetchone()
    assert row and row["entity_id"] == "exam_spacing_factor"


def test_tc98_unknown_setting_is_refused(conn, admin):
    with pytest.raises(KeyError):
        policy.set_setting(conn, "not_a_setting", 1, admin.id)


def test_tc99_spacing_factor_changes_the_examination_answer(conn, admin, day):
    from core import availability
    s, e = window(day, "10:00", 110)
    strict = availability.search(conn, s, e, 50, "EXAM")
    policy.set_setting(conn, "exam_spacing_factor", 0.8, admin.id)
    lenient = availability.search(conn, s, e, 50, "EXAM")
    assert len(lenient["available"]) >= len(strict["available"])
    # the stored exam capacity is authoritative, so the answer may be unchanged;
    # what must hold is that the fallback honours the factor
    room = dict(availability.room_by_code(conn, "IET20"))
    room["exam_capacity"] = 0
    assert availability.effective_capacity(room, "EXAM", 0.8) == 60


def test_tc100_period_length_setting_is_visible_to_callers(conn, admin):
    policy.set_setting(conn, "period_length_minutes", 50, admin.id)
    assert policy.get_setting(conn, "period_length_minutes") == 50


def test_tc101_room_edit_is_audited_with_before_and_after(conn, admin):
    outcome = records.update_room(conn, admin, "LH13", capacity=60, exam_capacity=30)
    assert outcome["ok"]
    row = conn.execute("SELECT before_state, after_state FROM audit_event "
                       "WHERE action='room:edit' ORDER BY id DESC").fetchone()
    assert '"capacity": 55' in row["before_state"]
    assert '"capacity": 60' in row["after_state"]


def test_tc102_confirming_an_inferred_room_clears_the_flag(conn, admin):
    assert conn.execute("SELECT unconfirmed FROM room WHERE code='LH14'").fetchone()[0] == 1
    outcome = records.confirm_room(conn, admin, "LH14", capacity=55, exam_capacity=27)
    assert outcome["ok"]
    assert conn.execute("SELECT unconfirmed FROM room WHERE code='LH14'").fetchone()[0] == 0


def test_tc103_faculty_cannot_edit_a_room(conn, faculty):
    assert records.update_room(conn, faculty, "LH13", capacity=99)["http"] == 403


def test_tc104_spaced_capacity_above_nominal_is_refused(conn, admin):
    outcome = records.update_room(conn, admin, "LH13", capacity=40, exam_capacity=60)
    assert outcome["code"] == "INVALID_CAPACITY"


def test_tc105_duplicate_reports_merge_with_a_count(conn, student):
    from core import booking, seed
    bid = conn.execute("SELECT id FROM booking WHERE status='CONFIRMED' LIMIT 1").fetchone()["id"]
    first = records.create_report(conn, student, bid, "WRONG_ROOM", "The room shown is wrong")
    assert first["ok"] and first["count"] == 1
    second = records.create_report(conn, student, bid, "WRONG_ROOM", "Still wrong")
    assert second["merged"] is True and second["count"] == 2
    total = conn.execute("SELECT COUNT(*) c FROM report WHERE booking_id=? AND kind='WRONG_ROOM'",
                         (bid,)).fetchone()["c"]
    assert total == 1


def test_tc106_report_kind_must_be_from_the_controlled_list(conn, student):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    assert records.create_report(conn, student, bid, "I_DONT_LIKE_IT", "x")["code"] == "INVALID_KIND"


def test_tc107_report_needs_a_body(conn, student):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    assert records.create_report(conn, student, bid, "OTHER", "  ")["code"] == "BODY_REQUIRED"


def test_tc108_resolving_a_report_notifies_the_reporters(conn, student, admin):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    created = records.create_report(conn, student, bid, "OUTDATED_INFORMATION", "Old timing")
    before = conn.execute("SELECT COUNT(*) c FROM notification").fetchone()["c"]
    outcome = records.resolve(conn, admin, created["report_id"], "Notice republished")
    assert outcome["ok"]
    after = conn.execute("SELECT COUNT(*) c FROM notification").fetchone()["c"]
    assert after > before


def test_tc109_student_cannot_resolve_a_report(conn, student):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    created = records.create_report(conn, student, bid, "OTHER", "Something")
    assert records.resolve(conn, student, created["report_id"], "fixed")["http"] == 403


def test_tc110_already_resolved_report_is_refused(conn, student, admin):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    created = records.create_report(conn, student, bid, "OTHER", "Something")
    records.resolve(conn, admin, created["report_id"], "done")
    again = records.resolve(conn, admin, created["report_id"], "done again")
    assert again["code"] == "ALREADY_RESOLVED"


def test_tc111_comment_creates_a_thread(conn, student):
    bid = conn.execute("SELECT id FROM booking LIMIT 1").fetchone()["id"]
    outcome = records.comment(conn, student, bid, "Is this class still on?")
    assert outcome["ok"]
    thread = records.report_thread(conn, outcome["report_id"])
    assert len(thread) == 1 and thread[0]["author"] == student.id


def test_tc112_faculty_section_notice_is_scoped_and_notified(conn, faculty):
    outcome = records.publish(conn, faculty, "Extra class", "Moved to IET18", scope="SECTION",
                              scope_id="CSE-3A", severity="IMPORTANT")
    assert outcome["ok"] and outcome["notified"] >= 1
    rows = conn.execute("SELECT * FROM notification WHERE payload LIKE '%Extra class%'").fetchall()
    assert rows


def test_tc113_faculty_cannot_publish_campus_wide(conn, faculty):
    outcome = records.publish(conn, faculty, "Holiday", "Campus closed", scope="CAMPUS")
    assert outcome["http"] == 403


def test_tc114_faculty_cannot_publish_to_a_section_they_do_not_teach(conn, faculty):
    outcome = records.publish(conn, faculty, "Notice", "Body", scope="SECTION",
                              scope_id="ZZZ-9Z")
    assert outcome["http"] == 403


def test_tc115_notice_needs_a_title_and_a_body(conn, admin):
    assert records.publish(conn, admin, "", "Body", scope="CAMPUS")["code"] == "INVALID_NOTICE"


def test_tc116_outbox_failure_does_not_undo_the_booking(conn, faculty):
    from core import availability, booking, seed
    day = seed.next_teaching_day(__import__("datetime").date.today(), 6)
    s, e = window(day, "10:00")
    free = availability.search(conn, s, e, 75, "CLASS")["available"]
    assert free
    bid = booking.create(conn, faculty, free[0]["code"], s, e, "CLASS", 75,
                         "IT-1A")["booking"]["id"]
    outcome = records.deliver_notifications(conn, fail_first=3)
    assert outcome["failed"] >= 1
    still_there = conn.execute("SELECT status FROM booking WHERE id=?", (bid,)).fetchone()
    assert still_there["status"] in ("CONFIRMED", "PENDING_APPROVAL"), \
        "a failed notification must never touch the reservation"


def test_tc117_audit_replay_reconstructs_a_room(conn, faculty, day):
    from core import availability, booking
    s, e = window(day, "16:15")
    free = availability.search(conn, s, e, 75, "CLASS")["available"]
    assert free, "no room is free at that hour"
    room = free[0]["code"]
    bid = booking.create(conn, faculty, room, s, e, "CLASS", 75, "AIDS-2A")["booking"]["id"]
    state = audit.replay_room(conn, room, s)
    assert state["free"] is False
    assert any(b["booking_id"] == bid for b in state["occupying"])
    booking.cancel(conn, faculty, bid, "Cancelled after the replay instant was taken")
    later = audit.replay_room(conn, room, e + timedelta(minutes=300))
    assert later["free"] is True


def test_tc118_audit_trail_filters_by_actor_and_entity(conn, admin, faculty):
    rows = audit.trail(conn, actor=admin.id)
    assert isinstance(rows, list)
    booking_rows = audit.trail(conn, entity="booking")
    assert all(r["entity"] == "booking" for r in booking_rows)


def test_tc119_every_audit_row_has_a_timestamp_and_actor(conn, admin):
    policy.set_setting(conn, "min_lead_time_minutes", 20, admin.id)
    rows = conn.execute("SELECT * FROM audit_event").fetchall()
    assert rows
    for row in rows:
        assert row["actor"] and row["at"] and row["action"]


def test_tc141_audit_diff_survives_non_json_states(conn, admin):
    """Rows written by other code paths carry plain strings; the view must not
    raise on them."""
    conn.execute(
        """INSERT INTO audit_event (actor, action, entity, entity_id, before_state, after_state, at)
           VALUES ('ADM-01','booking:create','booking','99','2026-11-06 09:00','2026-11-06 10:00','2026-11-06 10:00')""")
    rows = audit.trail(conn, entity="booking", limit=50)
    for row in rows:
        audit.diff(row["before_state"], row["after_state"])   # must not raise
    changes = audit.diff('{"status": "OPEN"}', '{"status": "RESOLVED"}')
    assert changes == [("status", "OPEN", "RESOLVED")]
