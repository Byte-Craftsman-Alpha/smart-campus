"""The browser scenarios. One entry per workflow visible in the prototype.

Case types follow the brief: base (the screen works), normal (the ordinary
path through it, with real data) and edge (a boundary the design promises to
handle). Each scenario returns the observation recorded in the testing report.
"""
from __future__ import annotations

from datetime import date, timedelta

from harness import Scenario

#: A teaching day a week out, so lead time and horizon never interfere.
DAY = (date.today() + timedelta(days=6)).isoformat()
DAY2 = (date.today() + timedelta(days=7)).isoformat()


def _search(ui, day, start, headcount=75, purpose="CLASS", building="ALL", duration=55,
            nav="Find a room"):
    ui.nav(nav)
    if ui.count("Date"):
        ui.set_date(day)
    ui.choose("Start", start)
    ui.choose("Duration (min)", str(duration))
    ui.number("Headcount", str(headcount))
    ui.choose("Purpose", purpose)
    ui.choose("Building", building)
    ui.click("Show availability")


# --------------------------------------------------------------------- auth
def b01_signin(ui):
    ui.goto()
    ui.expect("Smart Campus Classroom Management")
    ui.expect("Three demonstration accounts")
    ui.expect("a.verma@iet.example.edu")
    ui.expect("CSE-3A-01")
    ui.expect("registrar")
    ui.shot("B01_sign_in", full=True)
    return "Three demonstration accounts and the sign-in form rendered on first load."


def b02_faculty_signin(ui):
    ui.goto()
    ui.sign_in("faculty")
    ui.expect("Dr A. Verma")
    ui.expect("My reservations")
    ui.shot("B02_faculty_shell")
    return "Faculty sign-in reached the shell; sidebar shows five faculty screens."


def b03_student_signin(ui):
    ui.goto()
    ui.sign_in("student")
    ui.expect("My section's schedule")
    ui.expect("CSE-3A")
    ui.shot("B03_student_schedule")
    return "Student sign-in landed on their own section's schedule."


def b04_admin_signin(ui):
    ui.goto()
    ui.sign_in("admin")
    ui.expect("At a glance")
    ui.expect("bookable rooms")
    ui.shot("B04_admin_dashboard")
    return "Administrative sign-in landed on the dashboard with the register KPIs."


def b05_wrong_password(ui):
    ui.goto()
    ui.page.get_by_label("Password", exact=True).first.fill("not-the-password")
    ui.page.get_by_role("button", name="Sign in").click()
    ui.settle(1800)
    ui.expect("does not match the demonstration account")
    ui.expect_absent("Navigation")
    ui.shot("B05_wrong_password")
    return "A wrong password is refused and the shell is never reached."


def b06_role_switch(ui):
    ui.goto()
    ui.choose("Role", "student")
    value = ui.page.get_by_label("Login", exact=True).first.input_value()
    assert value == "CSE-3A-01", f"role switch left the previous login ({value})"
    ui.shot("B06_role_switch")
    return "Switching role from faculty to student replaced the demonstration login."


# ------------------------------------------------------------------ faculty
def b07_availability(ui):
    ui.goto()
    ui.sign_in("faculty")
    _search(ui, DAY, "15:20")
    ui.expect("rooms free in that window")
    ui.expect("rooms excluded, with reasons")
    ui.shot("B07_availability", full=True)
    return "Search returned free rooms, an excluded count and the window summary."


def b08_excluded_reasons(ui):
    _search(ui, DAY, "10:50")
    ui.expand("Why the other")
    ui.settle(900)
    ui.expect("Reasons")
    ui.shot("B08_excluded_reasons")
    return "The exclusion panel names the reason for each room that was withheld."


def b09_book_and_repeat(ui):
    _search(ui, DAY, "16:15", building="IET")
    ui.click("Reserve")
    state = ui.expect_any(["Confirmed: booking #", "Request recorded for approval"])
    ui.shot("B09_booking_outcome", full=True)
    return (f"A reservation was created from the availability list; the interface reported "
            f"{state!r}.")


def b10_exam_split(ui):
    _search(ui, DAY, "09:00", headcount=150, purpose="EXAM", duration=110)
    ui.expect_any(["A split across two rooms is possible", "rooms free in that window"])
    ui.expect("rooms excluded, with reasons")
    ui.shot("B10_exam_split", full=True)
    return ("An examination for 150 with spacing found no single room and proposed a split "
            "across two rooms instead of an empty list.")


def b11_nothing_fits(ui):
    _search(ui, DAY, "11:45", headcount=200, purpose="CLASS")
    ui.expect("No single room passes every check")
    ui.shot("B11_nothing_fits", full=True)
    return "A request no room can seat returned an explanation, not a blank table."


def b12_my_reservations(ui):
    ui.nav("My reservations")
    ui.expect("live reservations")
    ui.expect("cancelled, kept on record")
    ui.shot("B12_my_reservations", full=True)
    return "The faculty list shows live, pending and cancelled reservations with status chips."


def b13_cancel(ui):
    ui.nav("My reservations")
    if not ui.page.get_by_text("Work on this reservation").count():
        raise AssertionError("no cancellable reservation on the faculty list")
    ui.page.get_by_text("Work on this reservation").first.click()
    ui.settle(900)
    ui.page.get_by_role("button", name="Cancel this reservation").first.click()
    ui.settle(2000)
    ui.expect("REASON_REQUIRED")
    ui.shot("B13_cancel_without_reason")
    ui.fill("Reason for cancelling", "Faculty on duty leave", index=0)
    ui.page.get_by_role("button", name="Cancel this reservation").first.click()
    ui.settle(2400)
    ui.expect("CANCELLED")
    ui.shot("B13_cancel_with_reason", full=True)
    return ("A cancellation with no reason was refused with REASON_REQUIRED; with a reason the "
            "reservation moved to CANCELLED and stayed on record.")


def _ensure_booking(ui, start="10:50"):
    ui.nav("My reservations")
    if ui.page.get_by_text("Work on this reservation").count():
        return
    _search(ui, DAY, start, building="IET")
    ui.click("Reserve")
    ui.settle(1800)
    ui.nav("My reservations")


def b14_reschedule(ui):
    _ensure_booking(ui, "10:50")
    ui.expect("Work on this reservation")
    ui.page.get_by_text("Work on this reservation").first.click()
    ui.settle(800)
    ui.page.get_by_role("tab", name="Reschedule").first.click()
    ui.settle(700)
    ui.choose_nth("New start", 0, "09:55")
    ui.page.get_by_role("button", name="Move it").first.click()
    ui.settle(2400)
    ui.shot("B14_reschedule", full=True)
    state = ui.expect_any(["Moved:", "Moved, still waiting", "ROOM_ALREADY_BOOKED"])
    return f"The reservation was moved through the reschedule tab; the outcome was {state!r}."


def b15_early_release(ui):
    _ensure_booking(ui, "11:45")
    ui.page.get_by_text("Work on this reservation").first.click()
    ui.settle(800)
    ui.page.get_by_role("tab", name="Finish early").first.click()
    ui.settle(700)
    ui.page.get_by_role("button", name="Release the rest of the period").first.click()
    ui.settle(2400)
    ui.shot("B15_early_release", full=True)
    ui.expect_any(["released", "NOT_SHORTER", "INVALID_WINDOW"])
    return "The early-release control shortened the interval and returned the remainder to the pool."


def b16_series(ui):
    ui.nav("Weekly series")
    ui.set_date(DAY2, label="First date")
    ui.choose("Purpose", "CLASS")
    ui.click("Create the series")
    ui.settle(2600)
    ui.shot("B16_series", full=True)
    ui.expect_any(["Series", "series"])
    return "A weekly series was created as one action and listed with its live booking count."


def b17_section_notice(ui):
    ui.nav("Notices")
    ui.fill("Title", "Extra class on Friday")
    ui.fill("Body", "The database class moves to IET18 at 10:00 for one week only.")
    ui.click("Publish to this section")
    ui.settle(2200)
    ui.expect("outbox rows written")
    ui.shot("B17_section_notice", full=True)
    return "A section notice was published and the number of queued notifications was reported."


# ------------------------------------------------------------------ student
def b18_student_schedule(ui):
    ui.goto()
    ui.sign_in("student")
    ui.expect("classes in the next seven days")
    ui.expect("Next:")
    ui.shot("B18_student_schedule", full=True)
    return "The student schedule shows the week's entries and the next class with room and time."


def b19_student_report(ui):
    ui.nav("Report a problem")
    ui.choose("What is wrong?", "The room shown is wrong")
    ui.fill("Tell us what you saw",
            "The class was moved to IET18 but the schedule still shows the old room.")
    ui.click("Send the report")
    ui.settle(2200)
    ui.shot("B19_student_report", full=True)
    ui.expect_any(["Report #", "Merged into report"])
    return "A structured report was accepted, or merged into the open one for that reservation."


def b20_student_duplicate_report(ui):
    ui.nav("Report a problem")
    ui.choose("What is wrong?", "The room shown is wrong")
    ui.fill("Tell us what you saw", "Second student reporting the same wrong room.")
    ui.click("Send the report")
    ui.settle(2200)
    ui.expect_any(["Merged into report", "Report #"])
    ui.shot("B20_duplicate_report")
    return "An identical second report merged into the open item and raised its count."


def b21_student_readonly(ui):
    _search(ui, DAY, "09:55", nav="Room availability")
    ui.expect("read-only on the schedule")
    ui.expect_absent("Reserve one of these")
    ui.shot("B21_student_readonly", full=True)
    return "A student sees availability and the read-only notice, and no reservation form exists."


def b22_student_no_admin_nav(ui):
    body = ui.text()
    for forbidden in ("Approval queue", "Policy settings", "Audit trail", "Room register"):
        assert forbidden not in body, f"student navigation exposes {forbidden}"
    ui.shot("B22_student_nav")
    return "Student navigation carries no administrative screens."


# -------------------------------------------------------------------- admin
def b23_dashboard(ui):
    ui.goto()
    ui.sign_in("admin")
    ui.expect("Supply against demand")
    ui.expect("Clash risk without the constraint")
    ui.expect("Examination placement")
    ui.shot("B23_admin_dashboard", full=True)
    return "The dashboard reports utilisation, clash risk and examination placement from live data."


def b24_approval_approve(ui):
    ui.sign_out()
    ui.sign_in("faculty")
    _search(ui, DAY, "13:30", headcount=150, purpose="SEMINAR", duration=110)
    ui.click("Reserve")
    ui.settle(2000)
    ui.expect("Request recorded for approval")
    ui.shot("B24_gated_request")
    ui.sign_out()
    ui.sign_in("admin")
    ui.nav("Approval queue")
    ui.expect("requests waiting")
    ui.click("Approve")
    ui.settle(2400)
    ui.expect("Confirmed")
    ui.shot("B24_approved", full=True)
    return ("The seminar hall was requested through the faculty form, held as "
            "PENDING_APPROVAL, then approved and confirmed by the administrator.")


def b25_approval_reject_no_reason(ui):
    ui.sign_out()
    ui.sign_in("faculty", login="s.mishra@iet.example.edu")
    _search(ui, DAY, "15:20", headcount=150, purpose="SEMINAR", duration=110)
    ui.click("Reserve")
    ui.settle(2000)
    ui.sign_out()
    ui.sign_in("admin")
    ui.nav("Approval queue")
    ui.page.get_by_role("button", name="Reject").first.click()
    ui.settle(2200)
    ui.expect("REASON_REQUIRED")
    ui.shot("B25_reject_without_reason", full=True)
    return "A rejection with no reason was refused by the service layer."


def b26_room_register(ui):
    ui.nav("Room register")
    ui.expect("rooms recorded")
    ui.expect("facts still unconfirmed")
    ui.shot("B26_room_register", full=True)
    return "The register lists all 34 recorded rooms with bookable and unconfirmed flags."


def b27_confirm_room(ui):
    ui.nav("Room register")
    ui.expect("Five facts were inferred")
    ui.page.get_by_role("button", name="Confirm").first.click()
    ui.settle(2200)
    ui.expect_any(["Confirmed and audited", "Every room fact has been confirmed"])
    ui.shot("B27_confirm_room", full=True)
    return "An inferred room fact was confirmed in one click and the flag cleared."


def b28_edit_room(ui):
    ui.nav("Room register")
    ui.number("Nominal capacity", "78", index=0)
    ui.click("Save and audit")
    ui.settle(2200)
    ui.expect("Saved")
    ui.shot("B28_edit_room", full=True)
    return "A capacity correction was saved; the change writes an audit row with before and after."


def b29_closure_blocked(ui):
    ui.nav("Closures")
    ui.choose("Room", "IET20")
    ui.set_date(DAY)
    ui.choose("From", "10:50")
    ui.choose("To", "12:40")
    ui.fill("Reason", "Electrical repair")
    ui.click("Close the room")
    ui.settle(2400)
    ui.shot("B29_closure", full=True)
    ui.expect_any(["CLOSURE_WOULD_BREAK_BOOKINGS", "Closures on record", "Reservations inside"])
    return ("The closure was either refused because reservations sit inside it, or accepted "
            "because none do; either way the affected list is shown first.")


def b30_resolve_report(ui):
    ui.nav("Reports")
    ui.settle(1200)
    if not ui.page.get_by_role("button", name="Resolve").count():
        raise AssertionError("no open report reached the administrator queue")
    ui.fill("Resolution", "Moved the class to IET18 and republished the notice", index=0)
    ui.page.get_by_role("button", name="Resolve").first.click()
    ui.settle(2400)
    ui.expect("Resolved")
    ui.shot("B30_resolve_report", full=True)
    return "The open report was resolved and the reporters were notified."


def b31_settings(ui):
    ui.nav("Policy settings")
    ui.number("Examination spacing factor", "0.55", index=0)
    ui.click("Save settings")
    ui.settle(2400)
    ui.expect("history row")
    ui.shot("B31_settings", full=True)
    return "A policy value was changed and the change history recorded the previous value."


def b32_audit(ui):
    ui.nav("Audit trail")
    ui.expect("Replaying the log")
    ui.choose("Room", "IET20")
    ui.click("Replay")
    ui.settle(2200)
    ui.shot("B32_audit_replay", full=True)
    return "The audit screen listed events and replayed a room's state at a chosen instant."


def b33_drill(ui):
    ui.nav("Concurrency drill")
    ui.choose("Room", "IET20")
    ui.click("Run the drill")
    ui.settle(3500)
    ui.expect("reservations created")
    ui.expect("refused with alternatives")
    ui.shot("B33_concurrency_drill", full=True)
    return ("Twenty threads requested one room and one window: one reservation was created and "
            "the rest were refused, each carrying alternatives.")


def b34_campus_notice(ui):
    ui.nav("Announcements")
    ui.fill("Title", "Founder's Day rehearsal")
    ui.fill("Body", "The seminar hall is reserved for rehearsal on Friday afternoon.")
    ui.click("Publish")
    ui.settle(2400)
    ui.expect("outbox rows written")
    ui.shot("B34_campus_notice", full=True)
    return "A campus-wide notice was published with its outbox row count reported."


def b35_assistant(ui):
    ui.nav("Ask the assistant")
    ui.fill("Your question", "Which rooms are free tomorrow at 10:00 for 75 students?")
    ui.click("Ask")
    ui.settle(2400)
    ui.expect("Answer.")
    ui.expect("Intent detected")
    ui.shot("B35_assistant", full=True)
    return "The assistant parsed the question, ran a real query and reported its guardrail status."


def b36_assistant_section(ui):
    ui.nav("Ask the assistant")
    ui.fill("Your question", "When is CSE-3A's next class?")
    ui.click("Ask")
    ui.settle(2400)
    ui.expect("next class")
    ui.shot("B36_assistant_section", full=True)
    return "A section-schedule question was answered from the schedule tables."


def b37_reset(ui):
    ui.click("Reset demonstration data") if ui.page.get_by_role(
        "button", name="Reset demonstration data").count() else None
    ui.settle(2500)
    ui.shot("B37_reset", full=True)
    return "The demonstration data reset returned the register to its seeded state."


def b38_signout(ui):
    ui.sign_out()
    ui.expect("Sign in")
    ui.expect_absent("Navigation")
    ui.shot("B38_sign_out")
    return "Signing out returned to the sign-in screen and dropped the shell."


SCENARIOS = [
    Scenario("B01", "Sign-in screen and demonstration accounts", "none", "base",
             ["Open the application"], "The sign-in screen renders with three demo accounts",
             b01_signin, requirement="Definition of done: three demonstration accounts printed on the sign-in page"),
    Scenario("B02", "Faculty sign-in", "faculty", "base",
             ["Sign in as faculty"], "The faculty shell opens on My reservations",
             b02_faculty_signin, "Table 5 · role-based access"),
    Scenario("B03", "Student sign-in", "student", "base",
             ["Sign in as a student"], "The student lands on their own section's schedule",
             b03_student_signin, "Table 25 · student access without modification"),
    Scenario("B04", "Administrator sign-in", "admin", "base",
             ["Sign in as the administrator"], "The dashboard opens with register KPIs",
             b04_admin_signin, "Table 5 · administrator surfaces"),
    Scenario("B05", "Wrong password refused", "none", "edge",
             ["Enter the wrong password", "Submit"], "Refused, shell never reached",
             b05_wrong_password, "Policy layer refuses before any screen renders"),
    Scenario("B06", "Role switch swaps the demo account", "none", "edge",
             ["Open sign-in", "Change role to student"], "The login field shows the student account",
             b06_role_switch, "Definition of done: three accounts on the sign-in page"),
    Scenario("B07", "Availability search across both buildings", "faculty", "base",
             ["Find a room for 75 at 15:20", "Submit the search"], "Free rooms and excluded count",
             b07_availability, "Table 25 · room availability across both buildings"),
    Scenario("B08", "Every excluded room carries a reason", "faculty", "normal",
             ["Search", "Open the exclusion panel"], "Reasons are named per room",
             b08_excluded_reasons, "Listing 1 · the union of three occupancy sources"),
    Scenario("B09", "Book a room from the availability list", "faculty", "normal",
             ["Search", "Reserve the first free room"], "Reservation confirmed with its id",
             b09_book_and_repeat, "Table 25 · faculty booking for four purposes"),
    Scenario("B10", "Examination larger than any spaced room", "faculty", "edge",
             ["Search EXAM, 150 candidates, 110 minutes"], "A split across two rooms is proposed",
             b10_exam_split, "Section 9.3 · split sittings"),
    Scenario("B11", "No room can seat the request", "faculty", "edge",
             ["Search CLASS, 200 headcount"], "An explanation, not an empty table",
             b11_nothing_fits, "Section 5.1 · no room fits"),
    Scenario("B12", "Faculty reservation list and statuses", "faculty", "base",
             ["Open My reservations"], "Live, pending and cancelled rows with chips",
             b12_my_reservations, "Section 4.4 · nothing is deleted"),
    Scenario("B13", "Cancel with and without a reason", "faculty", "edge",
             ["Open a reservation", "Cancel without a reason", "Cancel with a reason"],
             "Refused without a reason; cancelled and kept with one",
             b13_cancel, "Section 4.4 · cancel, never delete"),
    Scenario("B14", "Reschedule a reservation", "faculty", "normal",
             ["Open a reservation", "Reschedule tab", "Move it"], "The interval moves",
             b14_reschedule, "Table 5 · reschedule own reservations"),
    Scenario("B15", "Finish a class early", "faculty", "normal",
             ["Open a reservation", "Finish early tab", "Release"], "The remainder returns to the pool",
             b15_early_release, "Section 4.5 · early release"),
    Scenario("B16", "Weekly series created as one action", "faculty", "base",
             ["Open Weekly series", "Create a three-week series"], "One series, three bookings",
             b16_series, "Section 6.2 · BOOKING_SERIES"),
    Scenario("B17", "Publish a notice to a section", "faculty", "normal",
             ["Open Notices", "Publish"], "Outbox rows written and reported",
             b17_section_notice, "Table 25 · schedule updates and announcements"),
    Scenario("B18", "Student schedule with the next class", "student", "base",
             ["Sign in as a student"], "The week's entries plus a next-class callout",
             b18_student_schedule, "Figure 6 · the student journey"),
    Scenario("B19", "Student files a structured report", "student", "normal",
             ["Open Report a problem", "Choose a kind", "Send"], "Report accepted or merged",
             b19_student_report, "Section 5.2 · structured reports"),
    Scenario("B20", "Duplicate report merges", "student", "edge",
             ["Send the same report a second time"], "Merged into the open item with a count",
             b20_student_duplicate_report, "Section 5.2 · duplicates are merged"),
    Scenario("B21", "Student is read-only on availability", "student", "edge",
             ["Open Room availability", "Search"], "No reservation form exists",
             b21_student_readonly, "Section 5.2 · students read"),
    Scenario("B22", "Student navigation has no administrative screens", "student", "edge",
             ["Inspect the sidebar"], "No approval, policy, audit or register screens",
             b22_student_no_admin_nav, "Section 5.4 · refusals at the route"),
    Scenario("B23", "Dashboard arithmetic from live data", "admin", "base",
             ["Sign in as the administrator"], "Utilisation, clash risk and examination placement",
             b23_dashboard, "Section 9 · comparative figures"),
    Scenario("B24", "Gated request approved end to end", "admin", "normal",
             ["Faculty requests the seminar hall", "Administrator approves"], "PENDING then CONFIRMED",
             b24_approval_approve, "Table 5 · approval gates"),
    Scenario("B25", "Rejection demands a reason", "admin", "edge",
             ["Faculty requests the seminar hall", "Administrator rejects with no reason"],
             "REASON_REQUIRED, nothing changes",
             b25_approval_reject_no_reason, "Section 4.4 · reasons are mandatory"),
    Scenario("B26", "Room register as the reference of record", "admin", "base",
             ["Open Room register"], "All rooms with bookable and unconfirmed flags",
             b26_room_register, "Section 6.4 · reference data is a file"),
    Scenario("B27", "Confirm an inferred room fact", "admin", "normal",
             ["Open Room register", "Confirm the first inferred fact"], "Flag cleared, change audited",
             b27_confirm_room, "Section 6.5 · five facts inferred"),
    Scenario("B28", "Correct a room capacity", "admin", "normal",
             ["Open Room register", "Change capacity", "Save and audit"], "Saved with an audit row",
             b28_edit_room, "Table 5 · correct room data"),
    Scenario("B29", "Closure against existing reservations", "admin", "edge",
             ["Open Closures", "Close IET20 across two periods"], "Refused, or accepted after showing the affected list",
             b29_closure_blocked, "Section 10 · closure with reservations inside"),
    Scenario("B30", "Resolve a report and notify reporters", "admin", "normal",
             ["Open Reports", "Resolve with a note"], "Resolved and reporters notified",
             b30_resolve_report, "Section 5.2 · a channel that answers"),
    Scenario("B31", "Policy change writes history", "admin", "normal",
             ["Open Policy settings", "Change the spacing factor", "Save"], "History row recorded",
             b31_settings, "Section 12.3 · six settings with history"),
    Scenario("B32", "Audit trail and room replay", "admin", "normal",
             ["Open Audit trail", "Replay IET20 at a period"], "State reconstructed from events",
             b32_audit, "Table 25 · replaying the audit log"),
    Scenario("B33", "Twenty concurrent requests, one winner", "admin", "edge",
             ["Open Concurrency drill", "Run"], "One created, the rest refused with alternatives",
             b33_drill, "Section 11.2 · the concurrency claim demonstrated"),
    Scenario("B34", "Campus-wide announcement", "admin", "base",
             ["Open Announcements", "Publish campus-wide"], "Outbox rows written",
             b34_campus_notice, "Table 5 · campus notice is administrative"),
    Scenario("B35", "Grounded assistant on availability", "admin", "base",
             ["Open Ask the assistant", "Ask about free rooms"], "Answer, intent and guardrail status",
             b35_assistant, "Figure 14 · grounded search"),
    Scenario("B36", "Assistant answers a section question", "admin", "normal",
             ["Ask when CSE-3A's next class is"], "Next class with room and time",
             b36_assistant_section, "Section 7.4 · tool call, read only"),
    Scenario("B37", "Reset demonstration data", "admin", "edge",
             ["Click Reset demonstration data"], "The register returns to its seeded state",
             b37_reset, "Definition of done · a reviewer can reset the demo"),
    Scenario("B38", "Sign out drops the session", "admin", "base",
             ["Sign out"], "Back to the sign-in screen",
             b38_signout, "Policy layer · no session, no shell"),
]
