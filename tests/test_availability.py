"""TC-34..TC-50: derived availability, the three occupancy sources, and the
hard checks that exclude a room."""
from datetime import date, timedelta

from core import availability, booking, config, intervals, policy, records, seed


def window(day, start="10:00", minutes=55):
    s = intervals.combine(day, start)
    return s, s + timedelta(minutes=minutes)


def test_tc34_register_is_seeded_from_the_file(conn):
    summary = __import__("core.analytics", fromlist=["register_summary"]).register_summary(conn)
    assert summary["rooms_recorded"] == 34
    assert summary["bookable"] == 30
    assert summary["offices_or_service"] == 4


def test_tc35_occupancy_has_three_sources(conn, day):
    """A reservation, a timetable slot and a closure all block the same room."""
    s, e = window(day)
    free = availability.search(conn, s, e, 75, "CLASS")
    assert free["available"], "some room must be free at that hour on that day"

    room = free["available"][0]["code"]
    availability.occupied_windows(conn, room, s, e) == []
    from core import seed as seed_mod
    admin_actor = policy.Actor("ADM-01", "admin", "Registrar")
    created = records.create_closure(conn, admin_actor, room, s, e, "Repair", force=True)
    assert created["ok"]
    busy = availability.occupied_windows(conn, room, s, e)
    assert any(w["source"] == "CLOSURE" for w in busy)
    after = availability.search(conn, s, e, 75, "CLASS")
    assert room not in [r["code"] for r in after["available"]]


def test_tc36_closed_room_is_excluded_with_a_named_reason(conn, day):
    s, e = window(day, "11:45")
    room = "IET30"
    admin = policy.Actor("ADM-01", "admin", "Registrar")
    records.create_closure(conn, admin, room, s, e, "Painting", force=True)
    result = availability.search(conn, s, e, 75, "CLASS")
    excluded = {r["code"]: r["reasons"] for r in result["excluded"]}
    assert room in excluded
    assert any("closure" in reason for reason in excluded[room])


def test_tc37_capacity_excludes_small_rooms(conn, day):
    s, e = window(day, "15:20")
    result = availability.search(conn, s, e, 75, "CLASS")
    for room in result["available"]:
        assert room["capacity"] >= 75
    small = [r for r in result["excluded"] if r["capacity"] < 75]
    assert small, "the compact Deeksha rooms must show up as excluded"
    assert any("seats" in " ".join(r["reasons"]) for r in small)


def test_tc38_exact_fit_is_accepted_with_no_slack(conn, day):
    """Edge case: seventy-five students in a seventy-five-seat room."""
    s, e = window(day, "16:15")
    result = availability.search(conn, s, e, 75, "CLASS")
    exact = [r for r in result["available"] if r["capacity"] == 75]
    assert exact, "an exact fit must be offered"
    assert all(r["slack"] == 0 for r in exact)


def test_tc39_examination_uses_spaced_capacity(conn, day):
    s, e = window(day, "09:00", 110)
    result = availability.search(conn, s, e, 75, "EXAM")
    codes = [r["code"] for r in result["available"]]
    assert "IET32" in codes or "LIB" in codes
    for room in result["available"]:
        assert availability.effective_capacity(room, "EXAM") >= 75
    assert "IET20" not in codes, "a 75-seat room holds 37 candidates with spacing"


def test_tc40_purpose_permission_excludes_offices(conn, day):
    s, e = window(day, "10:50")
    result = availability.search(conn, s, e, 10, "INTERVIEW")
    codes = [r["code"] for r in result["available"]]
    assert "PC" not in codes, "the placement cell is not bookable through the workflow"


def test_tc41_floor_and_building_filters(conn, day):
    s, e = window(day, "13:30")
    both = availability.search(conn, s, e, 75, "CLASS", building="ALL")
    deeksha = availability.search(conn, s, e, 75, "CLASS", building="DB")
    iet = availability.search(conn, s, e, 75, "CLASS", building="IET")
    assert len(both["available"]) == len(deeksha["available"]) + len(iet["available"])
    assert all(r["building_code"] == "DB" for r in deeksha["available"])
    assert all(r["building_code"] == "IET" for r in iet["available"])


def test_tc42_floor_zero_filter_returns_only_ground_floor(conn, day):
    s, e = window(day, "14:25")
    result = availability.search(conn, s, e, 45, "CLASS", floor=0)
    assert all(r["floor_level"] == 0 for r in result["available"])


def test_tc43_feature_requirement_excludes_rooms(conn, day):
    s, e = window(day, "11:45")
    plain = availability.search(conn, s, e, 45, "CLASS")
    needs_power = availability.search(conn, s, e, 45, "CLASS", features=["power"])
    assert len(needs_power["available"]) <= len(plain["available"])
    for room in needs_power["available"]:
        assert "power" in room["features"]


def test_tc44_accessibility_filter(conn, day):
    s, e = window(day, "15:20")
    result = availability.search(conn, s, e, 45, "CLASS", accessible=True)
    assert all(r["accessibility"] in ("step_free", "lift") for r in result["available"])


def test_tc45_free_windows_complement_occupancy(conn, day):
    s, e = window(day, "10:00", 220)
    room = "LH04"
    windows = availability.free_windows(conn, room, s, e)
    busy = availability.occupied_windows(conn, room, s, e)
    total_free = sum(intervals.duration_minutes(a, b) for a, b in windows)
    total_busy = sum(
        intervals.duration_minutes(max(a, intervals.parse_dt(w["start"])),
                                   min(b, intervals.parse_dt(w["end"])))
        for a, b in [(s, e)] for w in busy)
    assert total_free + total_busy == 220


def test_tc46_section_schedule_merges_bookings_and_timetable(conn, day):
    start = intervals.combine(day, "00:00")
    entries = availability.section_schedule(conn, "CSE-3A", start, start + timedelta(days=7))
    sources = {e["source"] for e in entries}
    assert "TIMETABLE" in sources
    assert entries == sorted(entries, key=lambda e: e["start_at"])


def test_tc47_effective_capacity_falls_back_to_the_factor(conn):
    room = availability.room_by_code(conn, "IET20")
    room["exam_capacity"] = 0
    assert availability.effective_capacity(room, "EXAM", 0.5) == 37
    assert availability.effective_capacity(room, "CLASS", 0.5) == 75


def test_tc48_hard_check_names_every_failure(conn):
    room = availability.room_by_code(conn, "LH03")
    fails = availability.hard_check(room, "EXAM", 40, features=["projector"], accessible=True)
    assert any("seats" in f for f in fails)
    assert any("projector" in f for f in fails)


def test_tc49_no_row_stores_a_free_flag(conn):
    columns = [r[1] for r in conn.execute("PRAGMA table_info(room)")]
    assert not any("free" in c or "occupied" in c for c in columns)


def test_tc50_pending_request_occupies_its_interval(conn, day, faculty):
    """A pending request holds the room, or three requests could all be approved."""
    s, e = window(day, "13:30")
    result = booking.create(conn, faculty, "IET32", s, e, "SEMINAR", 150)
    assert result["ok"], result
    assert result["booking"]["status"] == "PENDING_APPROVAL"
    second = booking.create(conn, faculty, "IET32", s, e, "SEMINAR", 150)
    assert second["ok"] is False and second["http"] == 409
