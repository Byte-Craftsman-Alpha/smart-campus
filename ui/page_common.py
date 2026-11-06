"""Screens shared by more than one role: the availability explorer (with the
booking panel for anyone allowed to write) and the grounded assistant."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import assistant, availability, booking, intervals, policy, records
from ui import components


VERBS = {
    "created": ("Confirmed", "Request recorded for approval"),
    "moved": ("Moved", "Moved, still waiting for approval"),
    "cancelled": ("Cancelled", "Cancelled"),
    "released": ("Released", "Released"),
    "approved": ("Approved", "Approved"),
    "rejected": ("Rejected", "Rejected"),
    "displaced": ("Displaced", "Displaced"),
}


def render_result(result: dict, action: str = "created") -> None:
    """One place decides how a booking outcome looks, so no screen can quietly
    turn a refusal into a success."""
    if result.get("ok") and result.get("booking") is None and result.get("closure_id"):
        st.success(f"Closure #{result['closure_id']} recorded. "
                   f"{len(result.get('affected') or [])} reservation(s) were inside it.")
        return
    if result.get("ok") and result.get("booking") is None and result.get("report_id"):
        st.success(f"Report #{result['report_id']} recorded.")
        return
    if result.get("ok"):
        b = result.get("booking") or {}
        status = b.get("status", "CREATED")
        pending_verb, pending_msg = VERBS.get(action, VERBS["created"])
        if status == "PENDING_APPROVAL":
            detail = result.get("gate") or ("this reservation still waits for approval"
                                            if action != "created" else "approval required")
            st.warning(f"{pending_msg}: booking #{b.get('id')} in {b.get('room_code')} "
                       f"{components.fmt_range(b.get('start_at'), b.get('end_at'))} — {detail}.")
        else:
            st.success(f"{pending_verb}: booking #{b.get('id')} in {b.get('room_code')}, "
                       f"{components.fmt_range(b.get('start_at'), b.get('end_at'))}.")
        for warning in result.get("warnings", []):
            st.info(warning)
        return

    st.error(f"{result.get('code')} · {result.get('message')}")
    alternatives = result.get("alternatives") or []
    if alternatives:
        st.markdown("**Three usable alternatives, ranked**")
        st.dataframe(
            [{"Room": a["room"], "Building": a["building"],
              "Window": components.fmt_range(a["start"], a["end"]),
              "Score": a["score"], "Why": "; ".join(a["reasons"])} for a in alternatives],
            width="stretch", hide_index=True)
    split = result.get("split") or []
    if split:
        st.markdown("**This has to be a split sitting**")
        st.dataframe([{"Room": s["room"], "Seats needed": s["seats"],
                       "Spaced capacity": s["capacity"],
                       "Window": components.fmt_range(s["start"], s["end"])} for s in split],
                     width="stretch", hide_index=True)
    affected = result.get("affected") or []
    if affected:
        st.markdown("**Reservations inside that window**")
        st.dataframe([{"Booking": a["id"], "Room": a["room_code"], "Section": a["section_code"],
                       "Window": components.fmt_range(a["start_at"], a["end_at"]),
                       "Status": a["status"]} for a in affected],
                     width="stretch", hide_index=True)


# ------------------------------------------------------------------ explorer
def availability_explorer(conn, actor):
    components.band("Room availability", "DERIVED, NEVER STORED",
                     "Three occupancy sources united first: reservations, the timetable "
                     "and closures. No row stores a free or occupied flag.")
    can_book = policy.can(actor, "booking:create").allowed

    with st.form("availability"):
        c = st.columns([1.1, 1, 1, 1, 1.2])
        with c[0]:
            day = st.date_input("Date", value=date.today(), key="av_day")
        grid = [p["start"] for p in availability.period_grid(conn)] + ["17:10"]
        with c[1]:
            start_hhmm = st.selectbox("Start", grid, index=0, key="av_start")
        with c[2]:
            duration = st.selectbox("Duration (min)", [55, 110, 30], index=0, key="av_dur")
        with c[3]:
            headcount = st.number_input("Headcount", min_value=1, max_value=1000, value=75, step=5,
                                        key="av_head")
        with c[4]:
            purpose = st.selectbox("Purpose", ["CLASS", "PRACTICAL", "EXAM", "SEMINAR",
                                               "EVENT", "TUTORIAL", "VIVA"], key="av_purpose")
        c2 = st.columns([1, 1, 1, 1])
        with c2[0]:
            building = st.selectbox("Building", ["ALL", "IET", "DB"], key="av_building")
        with c2[1]:
            floor = st.selectbox("Floor", ["ALL", "0", "1", "2"], key="av_floor")
        with c2[2]:
            features = st.multiselect("Required features", ["projector", "desks", "power",
                                                            "reading_hall"],
                                      key="av_features")
        with c2[3]:
            accessible = st.checkbox("Step-free only", key="av_access")
        submitted = st.form_submit_button("Show availability", type="primary")

    start = intervals.combine(day, start_hhmm)
    end = start + timedelta(minutes=int(duration))

    state_key = "av_result"
    if submitted or state_key not in st.session_state:
        st.session_state[state_key] = availability.search(
            conn, start, end, int(headcount), purpose, building=building, floor=floor,
            features=features or None, accessible=accessible)

    result = st.session_state[state_key]
    start, end = result["window"]
    components.kpis([
        (len(result["available"]), "rooms free in that window", "green"),
        (len(result["excluded"]), "rooms excluded, with reasons", "amber"),
        (intervals.duration_minutes(start, end), "minutes requested", "teal"),
        (result["headcount"], f"headcount for {result['purpose'].lower()}", ""),
    ])
    st.caption(f"Window {components.fmt_range(start, end)} · "
               f"{len(result['available'])} of {len(result['available']) + len(result['excluded'])} "
               f"rooms pass the hard checks")

    if result["available"]:
        rows = []
        for r in result["available"]:
            rows.append({
                "Room": r["code"], "Name": r["label"], "Building": r["building_code"],
                "Floor": r["floor_level"],
                "Capacity": availability.effective_capacity(
                    r, result["purpose"],
                    float(policy.get_setting(conn, "exam_spacing_factor"))),
                "Slack": r["slack"],
                "Free windows": "; ".join(
                    components.fmt_range(a, b) for a, b in r["free_windows"][:2]),
            })
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        components.callout("No single room passes every check in that window. Widen the "
                           "building or shift the window.", "warn")
        from core import scoring
        split = scoring.plan_split(conn, start, end, result["headcount"], result["purpose"])
        if split:
            st.markdown("**A split across two rooms is possible right now**")
            st.dataframe(
                [{"Room": part["room"], "Seats needed": part["seats"],
                  "Spaced capacity": part["capacity"],
                  "Window": components.fmt_range(part["start"], part["end"])} for part in split],
                width="stretch", hide_index=True)
            st.caption("The system proposes the split rather than returning an empty list; "
                       "recording it names the two rooms and notifies both sections.")

    if result["excluded"]:
        with st.expander(f"Why the other {len(result['excluded'])} rooms were excluded"):
            st.dataframe(
                [{"Room": r["code"], "Building": r["building_code"],
                  "Reasons": "; ".join(r["reasons"])} for r in result["excluded"]],
                width="stretch", hide_index=True)

    components.rule()
    if not can_book:
        components.callout("A student session is read-only on the schedule. This is refused in "
                           "the policy layer, not hidden in the interface.", "key")
        _occupancy_panel(conn, result)
        return

    # ------------------------------------------------------------- booking
    options = [r["code"] for r in result["available"]]
    if not options:
        st.caption("Nothing single-room can be reserved in this window; move the filters, or "
                   "use the split above.")
        _occupancy_panel(conn, result)
        return
    st.markdown("#### Reserve one of these")
    with st.form("book_from_search"):
        b = st.columns([1, 1.2, 1, 1])
        with b[0]:
            room_code = st.selectbox("Room", options, key="book_room")
        with b[1]:
            sections = [r["code"] for r in conn.execute("SELECT code FROM section ORDER BY code")]
            section = st.selectbox("Section", ["(none)"] + sections, key="book_section")
        with b[2]:
            title = st.text_input("Title", value="", key="book_title",
                                  placeholder="e.g. DBMS extra class")
        with b[3]:
            st.caption("An idempotency key is attached, so a double click cannot create "
                       "two reservations.")
        go = st.form_submit_button("Reserve", type="primary")
    if go:
        outcome = booking.create(
            conn, actor, room_code, start, end, purpose=result["purpose"],
            headcount=result["headcount"],
            section_code=None if section == "(none)" else section,
            idempotency_key=f"{actor.id}:{room_code}:{intervals.to_db(start)}:{intervals.to_db(end)}",
            title=title or None)
        render_result(outcome)
        st.session_state.pop("av_result", None)
    _occupancy_panel(conn, result)


def _occupancy_panel(conn, result):
    st.markdown("#### What is on in these rooms")
    codes = [r["code"] for r in result["available"]] or [
        r["code"] for r in result["excluded"][:6]]
    if not codes:
        return
    room_code = st.selectbox("Inspect a room", codes, key="inspect_room")
    start, end = result["window"]
    windows = availability.occupied_windows(conn, room_code, start, end)
    if windows:
        st.dataframe([{"Source": w["source"], "Window": components.fmt_range(w["start"], w["end"]),
                       "What": w["label"], "Status": w["status"]} for w in windows],
                     width="stretch", hide_index=True)
    else:
        st.caption(f"{room_code} has nothing in {components.fmt_range(start, end)}.")


# ------------------------------------------------------------------ assistant
def assistant_page(conn, actor):
    components.band("Ask the assistant", "GROUNDED SEARCH",
                     "The model may read results and return a structured intent. It has no "
                     "path that writes.")
    components.callout(
        "Every room code in an answer is checked against the result set the query returned. "
        "If it names a room the query did not offer, the answer is replaced by the plain list.", "key")

    question = st.text_input("Your question", key="ask_input",
                             placeholder="Which rooms are free tomorrow at 10:00 for 75 students?")
    cols = st.columns(3)
    for i, example in enumerate(assistant.EXAMPLES[:3]):
        with cols[i]:
            if st.button(example, key=f"ask_example_{i}"):
                st.session_state["ask_input"] = example
                st.rerun()
    if st.button("Ask", type="primary", key="ask_go") or question:
        answer = assistant.ask(conn, question, actor)
        if answer["intent"] == "none":
            return
        st.markdown(f"**Answer.** {answer['answer']}")
        c = st.columns(3)
        with c[0]:
            st.metric("Intent detected", answer["intent"].replace("_", " "))
        with c[1]:
            st.metric("Rooms in the result set", len(answer["rooms"]))
        with c[2]:
            st.metric("Guardrail", "triggered" if answer["guardrail_triggered"] else "clean")
        if answer.get("parsed"):
            p = answer["parsed"]
            st.caption(f"Parsed: {p['day']} at {p['time']}, {p['headcount']} people, "
                       f"{p['purpose'].lower()}.")
        st.caption("No tool call is exposed that writes. The assistant cannot create, move or "
                   "cancel a reservation.")
