"""TC-120..TC-140: the grounded assistant, the comparative arithmetic, and the
concurrency drill."""
from datetime import date, timedelta

import pytest

from core import analytics, assistant, availability, drill, intervals, policy


# ------------------------------------------------------------------ assistant
def test_tc120_find_rooms_parses_day_time_headcount(conn):
    answer = assistant.ask(conn, "Which rooms are free tomorrow at 10:00 for 75 students?")
    assert answer["intent"] == "find_rooms"
    assert answer["parsed"]["headcount"] == 75
    assert answer["parsed"]["time"] == "10:00"
    assert str(date.today() + timedelta(days=1)) == answer["parsed"]["day"]


def test_tc121_clock_numbers_are_not_headcounts(conn):
    answer = assistant.ask(conn, "Which rooms are free on Monday at 15:20 for 45 students?")
    assert answer["parsed"]["headcount"] == 45
    assert answer["parsed"]["time"] == "15:20"


def test_tc122_room_free_intent(conn, day):
    answer = assistant.ask(conn, f"Is IET20 free on {day} at 10:00?")
    assert answer["intent"] == "room_free"
    assert "IET20" in answer["answer"]


def test_tc123_section_schedule_intent(conn):
    answer = assistant.ask(conn, "When is CSE-3A's next class?")
    assert answer["intent"] == "section_schedule"
    assert "CSE-3A" in answer["answer"]


def test_tc124_capacity_lookup_intent(conn):
    answer = assistant.ask(conn, "Which rooms seat 200 people?")
    assert answer["intent"] in ("capacity_lookup", "count_rooms")
    assert "IET32" in answer["answer"]


def test_tc125_exam_question_uses_spaced_capacity(conn):
    answer = assistant.ask(conn, "How many rooms can hold 90 candidates for an exam?")
    assert answer["intent"] == "count_rooms"
    assert "LIB" in answer["answer"] or "IET32" in answer["answer"]


def test_tc126_guardrail_replaces_a_room_that_was_not_offered(conn):
    """If a drafted answer names a room outside the result set, it is replaced."""
    codes = [r["code"] for r in availability.rooms(conn)]
    drafted = "IET20 is free at 10:00, and so is LH04."
    text, triggered = assistant.apply_guardrail(drafted, ["LH04"], codes)
    assert triggered is True
    assert "plain result list" in text
    assert "LH04" in text and "IET20" not in text


def test_tc126b_guardrail_keeps_a_clean_answer(conn):
    codes = [r["code"] for r in availability.rooms(conn)]
    drafted = "LH04 and LH05 are free at 10:00."
    text, triggered = assistant.apply_guardrail(drafted, ["LH04", "LH05"], codes)
    assert triggered is False and text == drafted


def test_tc127_guardrail_is_quiet_on_a_clean_answer(conn):
    answer = assistant.ask(conn, "Which rooms are free tomorrow at 10:00 for 75 students?")
    assert answer["guardrail_triggered"] is False


def test_tc128_empty_question_is_handled(conn):
    answer = assistant.ask(conn, "   ")
    assert answer["intent"] == "none"


def test_tc129_assistant_has_no_write_path():
    """Section 7.1: propose, never commit."""
    source = open(assistant.__file__, encoding="utf-8").read()
    for forbidden in ("INSERT INTO", "UPDATE booking", "DELETE FROM", "booking.create(",
                      "booking.cancel("):
        assert forbidden not in source, forbidden


def test_tc130_assistant_answers_stay_within_the_register(conn):
    codes = {r["code"] for r in availability.rooms(conn)}
    answer = assistant.ask(conn, "Which rooms are free tomorrow at 10:00 for 45 students?")
    for code in answer["rooms"]:
        assert code in codes


# ------------------------------------------------------------------ analytics
def test_tc131_register_summary_matches_the_document(conn):
    summary = analytics.register_summary(conn)
    assert summary["rooms_recorded"] == 34
    assert summary["bookable"] == 30
    assert summary["full_section"] == 20
    assert summary["exam_capable"] == 2


def test_tc132_demand_supply_arithmetic(conn):
    ds = analytics.demand_supply(conn)
    assert ds["supply"] == 240
    assert ds["sections"] == 32
    assert [r["utilisation"] for r in ds["rows"]] == pytest.approx([0.8, 0.9333, 1.0667], abs=1e-3)


def test_tc133_peak_oversubscription(conn):
    ds = analytics.demand_supply(conn)
    assert ds["oversubscribed_by"] == pytest.approx(32 / 30, abs=1e-4)


def test_tc134_clash_probability_curve(conn):
    table = analytics.clash_table(conn)
    probs = [r["probability"] for r in table["rows"]]
    assert probs == sorted(probs), "the curve must rise with volume"
    assert probs[0] == pytest.approx(0.35, abs=0.02)
    assert probs[-1] > 0.99


def test_tc135_clash_probability_is_monotonic_and_bounded():
    for n in (5, 15, 30, 60):
        p = analytics.clash_probability(n, 240)
        assert 0.0 <= p <= 1.0
    assert analytics.clash_probability(60, 240) > analytics.clash_probability(30, 240)


def test_tc136_exam_placement_matches_the_document(conn):
    exam = analytics.exam_placement(conn)
    codes = [r["code"] for r in exam["qualifying"]]
    assert codes == ["IET32", "LIB"]
    assert exam["sittings"] == 16
    assert exam["days"] == 6


def test_tc137_live_day_load_is_bounded(conn, day):
    load = analytics.live_day_load(conn, day)
    assert 0 <= load["used_room_periods"] <= load["capacity_room_periods"]
    assert load["capacity_room_periods"] == 240
    assert load["idle_room_periods"] == 240 - load["used_room_periods"]


def test_tc138_health_endpoint_reports_the_register(conn):
    health = analytics.health(conn)
    assert health["register"]["bookable"] == 30
    assert health["sections"] == 32
    assert "exam_spacing_factor" in health["settings"]


# ------------------------------------------------------------------ drill
def test_tc139_twenty_parallel_requests_produce_one_reservation(conn, faculty, day, tmp_path):
    s = intervals.combine(day, "09:00")
    e = intervals.combine(day, "09:55")
    result = drill.run(conn, faculty, "IET28", s, e, section_code="CSE-1A",
                       db_path=str(tmp_path / "campus.db"))
    assert result["requests"] == 20
    assert result["successes"] == 1
    assert result["conflicts"] == 19
    assert result["live_rows_in_window"] == 1
    assert result["verified"] is True
    assert result["alternatives_min"] >= 3


def test_tc140_every_refusal_in_the_drill_carries_alternatives(conn, faculty, day, tmp_path):
    s = intervals.combine(day, "16:15")
    e = intervals.combine(day, "17:10")
    result = drill.run(conn, faculty, "IET29", s, e, db_path=str(tmp_path / "campus.db"))
    assert all(r["alternatives"] >= 3 for r in result["results"] if r["http"] == 409)
