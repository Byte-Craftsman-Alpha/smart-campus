"""TC-15..TC-33: every cell of the permission matrix, negatives included.

Section 5.4: the matrix is one function, and every cell is asserted so that an
interface change cannot become a privilege leak.
"""
import pytest

from core import policy


ACTIONS = list(policy.MATRIX)


def test_tc15_matrix_covers_every_action_for_every_role():
    for action in ACTIONS:
        assert len(policy.MATRIX[action]) == 3, action


@pytest.mark.parametrize("action", [
    "booking:create", "booking:approve", "booking:displace", "notice:publish_campus",
    "report:resolve", "room:edit", "room:close", "policy:edit", "demo:reset",
])
def test_tc16_student_is_refused_administrative_actions(student, action):
    decision = policy.can(student, action, {"created_by": student.id})
    assert decision.allowed is False
    assert decision.reason, "a refusal always carries a reason"


def test_tc17_student_may_read_schedules_and_search(student):
    assert policy.can(student, "schedule:view").allowed
    assert policy.can(student, "rooms:search").allowed


def test_tc18_student_may_report_and_comment(student):
    assert policy.can(student, "report:create").allowed
    assert policy.can(student, "report:comment").allowed


def test_tc19_student_may_not_create_a_booking(student):
    decision = policy.can(student, "booking:create")
    assert decision.allowed is False
    assert "reserve a room" in decision.reason


def test_tc20_gated_booking_becomes_an_approval_request_for_faculty(faculty):
    decision = policy.can(faculty, "booking:create_gated")
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_tc21_admin_books_gated_space_without_an_approval_step(admin):
    decision = policy.can(admin, "booking:create_gated")
    assert decision.allowed and decision.requires_approval is False


def test_tc22_faculty_may_cancel_only_their_own(faculty, other_faculty):
    own = {"created_by": faculty.id}
    theirs = {"created_by": other_faculty.id}
    assert policy.can(faculty, "booking:cancel", own).allowed
    refused = policy.can(faculty, "booking:cancel", theirs)
    assert refused.allowed is False
    assert other_faculty.id in refused.reason


def test_tc23_admin_may_cancel_anything(admin, faculty):
    assert policy.can(admin, "booking:cancel", {"created_by": faculty.id}).allowed


def test_tc24_ownership_without_a_resource_is_refused(faculty):
    decision = policy.can(faculty, "booking:cancel", None)
    assert decision.allowed is False
    assert "ownership" in decision.reason


def test_tc25_faculty_may_not_approve_or_displace(faculty):
    assert policy.can(faculty, "booking:approve").allowed is False
    assert policy.can(faculty, "booking:displace").allowed is False


def test_tc26_faculty_may_not_publish_a_campus_notice(faculty):
    assert policy.can(faculty, "notice:publish_campus").allowed is False


def test_tc27_faculty_may_not_edit_rooms_or_policy(faculty):
    assert policy.can(faculty, "room:edit").allowed is False
    assert policy.can(faculty, "policy:edit").allowed is False


def test_tc28_faculty_audit_read_is_limited_to_own_actions(faculty, other_faculty):
    assert policy.can(faculty, "audit:read", {"created_by": faculty.id}).allowed
    assert policy.can(faculty, "audit:read", {"created_by": other_faculty.id}).allowed is False


def test_tc29_admin_may_do_everything_administrative(admin):
    for action in ("booking:approve", "report:resolve", "room:edit", "room:close",
                   "policy:edit", "demo:reset", "notice:publish_campus"):
        assert policy.can(admin, action).allowed, action


def test_tc30_unknown_action_is_refused_not_defaulted(admin):
    decision = policy.can(admin, "booking:delete_everything")
    assert decision.allowed is False
    assert "Unknown action" in decision.reason


def test_tc31_unknown_role_is_refused():
    actor = policy.Actor("X", "visitor", "Visitor")
    assert policy.can(actor, "schedule:view").allowed is False


def test_tc32_gate_reason_names_the_reason(conn):
    from core import availability
    seminar = availability.room_by_code(conn, "IET32")
    reason = policy.gate_reason(seminar, 150, "SEMINAR")
    assert reason and "seminar" in reason.lower()
    library = availability.room_by_code(conn, "LIB")
    assert policy.gate_reason(library, 90, "EXAM")
    ordinary = availability.room_by_code(conn, "IET20")
    assert policy.gate_reason(ordinary, 75, "CLASS") is None


def test_tc33_decision_is_truthy_so_callers_cannot_forget_allowed(admin, student):
    assert bool(policy.can(admin, "booking:approve")) is True
    assert bool(policy.can(student, "booking:create")) is False
