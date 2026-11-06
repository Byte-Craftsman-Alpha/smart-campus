"""The administrator's surfaces: room data, the approval queue, reports, policy
and the audit trail. All of them write to the same record."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import (analytics, audit, availability, booking, config, drill, intervals,
                  policy, records)
from ui import components, page_common


def dashboard(conn, actor):
    components.band("At a glance", "ADMINISTRATOR",
                     "The arithmetic of scarcity, computed from the live register rather than "
                     "quoted from the document.")
    health = analytics.health(conn)
    reg = health["register"]
    components.kpis([
        (reg["bookable"], "bookable rooms of " + str(reg["rooms_recorded"]), "teal"),
        (health["sections"], "sections across four years", ""),
        (health["live_bookings"], "live reservations", "green"),
        (health["pending_approvals"], "waiting for approval", "amber"),
        (health["open_reports"], "open reports", "rose"),
    ])

    st.markdown("#### Supply against demand")
    ds = analytics.demand_supply(conn)
    st.dataframe([
        {"Periods used per section": r["periods_per_section"],
         "Demand (room-periods)": r["demand"],
         "Supply": ds["supply"],
         "Utilisation": f"{r['utilisation'] * 100:.1f}%",
         "Room-periods left": r["free"]} for r in ds["rows"]],
        width="stretch", hide_index=True)
    st.caption(f"{ds['rooms']} bookable rooms × {ds['periods']} periods = {ds['supply']} "
               f"room-periods a day. A single period can host at most {ds['rooms']} sections, "
               f"so {ds['sections']} sections are {ds['oversubscribed_by']:.2f}× the concurrency "
               f"ceiling at {ds['peak_periods']} periods.")

    c = st.columns(2)
    with c[0]:
        st.markdown("#### Clash risk without the constraint")
        clash = analytics.clash_table(conn)
        st.dataframe([{"Simultaneous bookings": r["n"],
                       "P(at least one clash)": f"{r['probability'] * 100:.1f}%",
                       "Expected clashes a semester": f"{r['expected_clashes']:.0f}"}
                      for r in clash["rows"]], width="stretch", hide_index=True)
        st.caption(f"Over {clash['room_terms']} room-terms.")
    with c[1]:
        st.markdown("#### Examination placement")
        exam = analytics.exam_placement(conn)
        if exam["qualifying"]:
            st.dataframe([{"Room": r["code"], "Spaced capacity": r["exam_capacity"]}
                          for r in exam["qualifying"]], width="stretch", hide_index=True)
            st.caption(f"{exam['sections']} sections need {exam['sittings']} sittings, which is "
                       f"{exam['days']} days at {exam['per_day']} sittings a day.")
        else:
            st.caption("No room on the register seats a full section with examination spacing.")

    st.markdown("#### Today against the register")
    load = analytics.live_day_load(conn, date.today())
    components.kpis([
        (load["used_room_periods"], "room-periods in use today", "teal"),
        (load["idle_room_periods"], "idle room-periods today", ""),
        (f"{load['utilisation'] * 100:.0f}%", "utilisation today", "green"),
        (load["peak_concurrent"], f"peak concurrent rooms ({load['peak_period']})", "amber"),
    ])

    staff = analytics.staff_time(conn)
    st.markdown("#### What the register changes")
    st.dataframe([{
        "Bookings on record": staff["bookings"],
        "Manual minutes per booking": 15,
        "Minutes in this system": 0.75,
        "Hours saved so far": f"{staff['hours_saved']:.1f}",
        "Projected per semester": f"{staff['semester_projection_hours']:.0f} h",
    }], width="stretch", hide_index=True)

    with st.expander("System health (the endpoint a maintainer reads)"):
        st.json(health["settings"])
        st.write({"register": reg, "notifications": health["notifications"],
                  "generated_at": health["generated_at"]})


def approval_queue(conn, actor):
    components.band("Approval queue", "ADMINISTRATOR",
                     "The seminar hall, the library and large events are decided by a person, "
                     "not by the form.")
    pending = [dict(r) for r in conn.execute(
        """SELECT b.*, r.label AS room_label, f.building_code, fa.name AS faculty_name
           FROM booking b JOIN room r ON r.code=b.room_code JOIN floor f ON f.id=r.floor_id
           LEFT JOIN faculty fa ON fa.id=b.faculty_id
           WHERE b.status='PENDING_APPROVAL' ORDER BY b.start_at""")]
    components.kpis([(len(pending), "requests waiting", "amber" if pending else "green")])
    if not pending:
        st.caption("Nothing waiting. A queue that is usually empty is a queue that works.")
        return
    for row in pending:
        components.card(
            f"{row['room_code']} · {row['room_label']}",
            f"{components.fmt_range(row['start_at'], row['end_at'])} · "
            f"{row['purpose'].title()} · {row['headcount']} people · "
            f"{row['faculty_name'] or row['created_by']}",
            f"<div style='font-size:.84rem'>Requested because: {row['reason'] or 'policy gate'}</div>")
        c = st.columns([2, 2, 1])
        with c[0]:
            note = st.text_input("Note", key=f"appr_note_{row['id']}", placeholder="optional")
            if st.button("Approve", key=f"appr_{row['id']}", type="primary"):
                page_common.render_result(booking.approve(conn, actor, row["id"], note or None))
        with c[1]:
            reason = st.text_input("Rejection reason", key=f"rej_reason_{row['id']}")
            if st.button("Reject", key=f"rej_{row['id']}"):
                page_common.render_result(booking.reject(conn, actor, row["id"], reason))
        components.rule()


def room_register(conn, actor):
    components.band("Room register", "REFERENCE DATA",
                     "Stored once as a versioned file. Floors, capacities and flags are corrected "
                     "here, not in a component.")
    rooms = availability.rooms(conn, bookable_only=False)
    unconfirmed = [r for r in rooms if r["unconfirmed"]]
    components.kpis([
        (len(rooms), "rooms recorded", ""),
        (len([r for r in rooms if r["bookable"]]), "bookable", "teal"),
        (len(unconfirmed), "facts still unconfirmed", "amber"),
        (len([r for r in rooms if r["exam_capacity"] >= 75]), "rooms that seat a full section "
                                                             "for an exam", "green"),
    ])
    st.dataframe([{
        "Room": r["code"], "Name": r["label"], "Building": r["building_code"],
        "Floor": r["floor_level"], "Type": r["room_type"], "Capacity": r["capacity"],
        "Exam capacity": r["exam_capacity"], "Bookable": bool(r["bookable"]),
        "Unconfirmed": bool(r["unconfirmed"]),
    } for r in rooms], width="stretch", hide_index=True)

    st.divider()
    st.markdown("#### Five facts were inferred, not stated")
    st.caption("Each is presented with its source and cleared in one click.")
    if unconfirmed:
        for room in unconfirmed:
            c = st.columns([2, 1, 1, 1])
            with c[0]:
                st.markdown(f"**{room['code']}** · {room['label']} · "
                            f"{room['building_code']} floor {room['floor_level']}")
                st.caption(room["notes"] or "Inferred from the plan.")
            with c[1]:
                cap = st.number_input("Capacity", min_value=0, value=int(room["capacity"]),
                                      key=f"cap_{room['code']}")
            with c[2]:
                exam_cap = st.number_input("Exam capacity", min_value=0,
                                           value=int(room["exam_capacity"]),
                                           key=f"excap_{room['code']}")
            with c[3]:
                if st.button("Confirm", key=f"confirm_{room['code']}"):
                    outcome = records.confirm_room(conn, actor, room["code"], cap, exam_cap)
                    st.success("Confirmed and audited." if outcome["ok"] else outcome["message"])
    else:
        st.success("Every room fact has been confirmed.")

    st.divider()
    st.markdown("#### Correct a room record")
    code = st.selectbox("Room", [r["code"] for r in rooms], key="edit_room_code")
    current = availability.room_by_code(conn, code)
    with st.form("edit_room_form"):
        c = st.columns(3)
        with c[0]:
            capacity = st.number_input("Nominal capacity", min_value=0,
                                       value=int(current["capacity"]), key="edit_cap")
        with c[1]:
            exam_capacity = st.number_input("Exam capacity", min_value=0,
                                            value=int(current["exam_capacity"]), key="edit_exam")
        with c[2]:
            room_type = st.selectbox("Type", ["CLASS", "LAB", "SEMINAR", "LIBRARY", "OFFICE",
                                              "SERVICE"],
                                     index=["CLASS", "LAB", "SEMINAR", "LIBRARY", "OFFICE",
                                            "SERVICE"].index(current["room_type"]),
                                     key="edit_type")
        notes = st.text_input("Notes", value=current["notes"] or "", key="edit_notes")
        if st.form_submit_button("Save and audit"):
            outcome = records.update_room(conn, actor, code, capacity=capacity,
                                          exam_capacity=exam_capacity, room_type=room_type,
                                          notes=notes)
            st.success("Saved." if outcome["ok"] else outcome["message"])


def closures(conn, actor):
    components.band("Closures", "ADMINISTRATOR",
                     "A closure cannot be saved until each affected reservation is cancelled or "
                     "moved; the affected list is shown first.")
    rooms = [r["code"] for r in availability.rooms(conn)]
    with st.form("closure"):
        c = st.columns([1, 1, 1, 2])
        with c[0]:
            room = st.selectbox("Room", rooms, key="cl_room")
        with c[1]:
            day = st.date_input("Date", value=date.today() + timedelta(days=1), key="cl_day")
        with c[2]:
            grid = [p["start"] for p in availability.period_grid(conn)]
            start_hhmm = st.selectbox("From", grid, index=0, key="cl_from")
            end_hhmm = st.selectbox("To", [p["end"] for p in availability.period_grid(conn)],
                                    index=2, key="cl_to")
        with c[3]:
            reason = st.text_input("Reason", key="cl_reason",
                                   placeholder="Electrical repair in the corridor")
        go = st.form_submit_button("Close the room", type="primary")
    if go:
        start = intervals.combine(day, start_hhmm)
        end = intervals.combine(day, end_hhmm)
        outcome = records.create_closure(conn, actor, room, start, end, reason)
        page_common.render_result(outcome)
        if not outcome["ok"] and outcome.get("affected"):
            st.info("Nothing was saved. Cancel or move those reservations, then close the room.")

    st.markdown("#### Closures on record")
    rows = records.list_closures(conn, live_only=False)
    if rows:
        st.dataframe([{"Room": r["room_code"], "From": r["start_at"], "To": r["end_at"],
                       "Reason": r["reason"], "By": r["created_by"]} for r in rows],
                     width="stretch", hide_index=True)
    else:
        st.caption("No closures recorded.")


def report_queue(conn, actor):
    components.band("Reports", "ADMINISTRATOR",
                     "Twelve students reporting the same wrong room produce one item with a count "
                     "of twelve.")
    reports = records.open_reports(conn)
    components.kpis([(len(reports), "open reports", "rose" if reports else "green")])
    if not reports:
        st.caption("Nothing open.")
        return
    for r in reports:
        components.card(
            config.REPORT_KIND_LABELS.get(r["kind"], r["kind"]),
            f"Report #{r['id']} · reservation #{r['booking_id']} · "
            f"{r['report_count']} report(s) · {r['room_code']} "
            f"{components.fmt_range(r['start_at'], r['end_at'])} · reported by {r['reporter']}")
        thread = records.report_thread(conn, r["id"])
        st.dataframe([{"Who": t["author"], "When": t["at"], "What": t["body"]} for t in thread],
                     width="stretch", hide_index=True)
        c = st.columns([3, 1])
        with c[0]:
            resolution = st.text_input("Resolution", key=f"res_text_{r['id']}",
                                       placeholder="Moved the class to IET18 and republished the notice")
        with c[1]:
            if st.button("Resolve", key=f"res_{r['id']}", type="primary"):
                outcome = records.resolve(conn, actor, r["id"], resolution)
                st.success(f"Resolved; {outcome.get('notified', 0)} reporters notified."
                           if outcome["ok"] else outcome["message"])
        components.rule()


def policy_settings(conn, actor):
    components.band("Policy settings", "SIX VALUES THAT DECIDE BEHAVIOUR",
                     "Each is stored with its current value and its previous values, and changing "
                     "one writes an audit record.")
    settings = policy.all_settings(conn)
    with st.form("settings"):
        c = st.columns(3)
        with c[0]:
            period = st.number_input("Period length (minutes)", 30, 120,
                                     int(settings["period_length_minutes"]), key="set_period")
            periods = st.number_input("Periods per day", 4, 12, int(settings["periods_per_day"]),
                                      key="set_periods")
            factor = st.number_input("Examination spacing factor", 0.2, 1.0,
                                     float(settings["exam_spacing_factor"]), step=0.05,
                                     key="set_factor")
        with c[1]:
            gap = st.number_input("Cross-building gap (minutes)", 0, 60,
                                  int(settings["min_cross_building_gap_minutes"]), key="set_gap")
            horizon = st.number_input("Booking horizon (days)", 1, 365,
                                      int(settings["booking_horizon_days"]), key="set_horizon")
            lead = st.number_input("Minimum lead time (minutes)", 0, 1440,
                                   int(settings["min_lead_time_minutes"]), key="set_lead")
        with c[2]:
            threshold = st.number_input("Approval threshold (headcount)", 0, 1000,
                                        int(settings["approval_headcount_threshold"]), key="set_thresh")
            snap = st.number_input("Grid (minutes)", 5, 30, int(settings["snap_minutes"]), step=5,
                                   key="set_snap")
            demo = st.checkbox("Mark demonstration data", value=bool(int(settings["demo_mode"])),
                               key="set_demo")
        if st.form_submit_button("Save settings", type="primary"):
            updates = {
                "period_length_minutes": period, "periods_per_day": periods,
                "exam_spacing_factor": factor, "min_cross_building_gap_minutes": gap,
                "booking_horizon_days": horizon, "min_lead_time_minutes": lead,
                "approval_headcount_threshold": threshold, "snap_minutes": snap,
                "demo_mode": 1 if demo else 0,
            }
            for key, value in updates.items():
                if str(settings[key]) != str(value):
                    policy.set_setting(conn, key, value, actor.id)
            st.success("Saved. Every change wrote an audit row and a history row.")

    st.markdown("#### Scoring weights for the alternatives")
    with st.form("weights"):
        c = st.columns(len(config.SCORE_WEIGHTS))
        values = {}
        for col, (label, key) in zip(c, config.SCORE_WEIGHTS.items()):
            with col:
                values[key] = st.number_input(label.title(), 0.0, 1.0,
                                              float(settings[key]), step=0.05, key=f"w_{key}")
        if st.form_submit_button("Save weights"):
            for key, value in values.items():
                policy.set_setting(conn, key, value, actor.id)
            st.success("Weights saved. The reasons shown to faculty follow these weights.")

    st.markdown("#### Change history")
    history = policy.settings_history(conn)
    st.dataframe([{"Setting": h["key"], "From": h["old_value"], "To": h["new_value"],
                   "By": h["actor"], "At": h["at"]} for h in history],
                 width="stretch", hide_index=True)


def audit_trail(conn, actor):
    components.band("Audit trail", "TAMPER-EVIDENT",
                     "Replaying the log reconstructs any room's state at any past time.")
    c = st.columns([1, 1, 1])
    with c[0]:
        entity = st.selectbox("Entity", ["(all)", "booking", "room", "report", "announcement"],
                              key="aud_entity")
    with c[1]:
        action = st.text_input("Action prefix", key="aud_action", placeholder="booking:")
    with c[2]:
        limit = st.number_input("Rows", 10, 500, 100, step=10, key="aud_limit")
    rows = audit.trail(conn, limit=int(limit),
                       entity=None if entity == "(all)" else entity,
                       action=action or None)
    st.dataframe([{"When": r["at"], "Actor": r["actor"], "Action": r["action"],
                   "Entity": f"{r['entity']}#{r['entity_id']}", "Request": r["request_id"]}
                  for r in rows], width="stretch", hide_index=True)

    with st.expander("Before and after", expanded=False):
        for r in rows[:20]:
            changes = audit.diff(r["before_state"], r["after_state"])
            if changes:
                st.markdown(f"**{r['action']}** · {r['entity']} #{r['entity_id']} · {r['at']}")
                st.dataframe([{"Field": f, "Before": b, "After": a} for f, b, a in changes],
                             width="stretch", hide_index=True)

    st.divider()
    st.markdown("#### Replay a room's state")
    c = st.columns([1, 1, 1])
    with c[0]:
        room = st.selectbox("Room", [r["code"] for r in availability.rooms(conn)], key="rep_room")
    with c[1]:
        day = st.date_input("At date", value=date.today(), key="replay_day")
    with c[2]:
        grid = [p["start"] for p in availability.period_grid(conn)]
        at = st.selectbox("At time", grid, index=0, key="replay_at")
    if st.button("Replay", key="replay_go", type="primary"):
        state = audit.replay_room(conn, room, intervals.combine(day, at))
        st.write({"room": state["room"], "at": state["at"], "free": state["free"],
                  "events_replayed": state["replayed_events"],
                  "bookings_seen": state["all_bookings_seen"]})
        if state["occupying"]:
            st.dataframe([{"Booking": b["booking_id"], "Status": b["status"],
                           "From": b["start"], "To": b["end"], "Section": b["section"]}
                          for b in state["occupying"]], width="stretch", hide_index=True)
        else:
            st.caption("The room was free at that instant, according to the events alone.")

    st.divider()
    st.markdown("#### Notification outbox")
    stats = records.notification_stats(conn)
    st.write(stats or {"QUEUED": 0})
    c = st.columns([1, 1])
    with c[0]:
        if st.button("Deliver queued notifications", key="outbox_go"):
            outcome = records.deliver_notifications(conn)
            st.success(f"{outcome['sent']} sent, {outcome['failed']} failed.")
    with c[1]:
        fail_first = st.number_input("Simulate failures", 0, 50, 0, key="outbox_fail")
    if fail_first:
        if st.button("Deliver with simulated failures", key="outbox_fail_go"):
            outcome = records.deliver_notifications(conn, fail_first=int(fail_first))
            st.warning(f"{outcome['sent']} sent, {outcome['failed']} failed. The booking is "
                       f"unaffected: the outbox is a separate table.")


def announcements(conn, actor):
    components.band("Announcements", "ADMINISTRATOR",
                     "Campus and building notices are an administrative act; section notices "
                     "belong to whoever teaches the section.")
    with st.form("announce"):
        c = st.columns([1, 1, 1])
        with c[0]:
            scope = st.selectbox("Scope", ["CAMPUS", "BUILDING", "SECTION"], key="an_scope")
        with c[1]:
            scope_id = st.text_input("Scope id (building or section)", key="an_scope_id",
                                     placeholder="IET or CSE-3A")
        with c[2]:
            severity = st.selectbox("Severity", config.ANNOUNCEMENT_SEVERITIES, key="an_sev")
        title = st.text_input("Title", key="an_title")
        body = st.text_area("Body", key="an_body")
        if st.form_submit_button("Publish", type="primary"):
            outcome = records.publish(conn, actor, title, body, scope=scope,
                                      scope_id=scope_id or None, severity=severity)
            if outcome["ok"]:
                st.success(f"Published; {outcome['notified']} outbox rows written.")
            else:
                st.error(f"{outcome['code']} · {outcome['message']}")

    st.markdown("#### Recent notices")
    for a in records.list_announcements(conn, limit=25):
        components.card(a["title"], f"{a['scope']} {a['scope_id'] or ''} · {a['severity']} · "
                                    f"{a['publish_at']}", a["body"])


def concurrency_drill(conn, actor):
    components.band("Concurrency drill", "TWENTY REQUESTS, ONE ROOM, ONE WINNER",
                     "Double booking shown to be impossible by the test rather than asserted in "
                     "prose.")
    components.callout(
        "Twenty threads, twenty connections, one room and one window. The expected outcome is "
        "one success and nineteen refusals, each carrying three usable alternatives.", "key")
    c = st.columns([1, 1, 1])
    with c[0]:
        room = st.selectbox("Room", [r["code"] for r in availability.rooms(conn)], key="dr_room",
                            index=5)
    with c[1]:
        day = st.date_input("Date", value=date.today() + timedelta(days=2), key="dr_day")
    with c[2]:
        grid = [p["start"] for p in availability.period_grid(conn)]
        at = st.selectbox("Start", grid, index=7, key="dr_at")
    if st.button("Run the drill", key="dr_go", type="primary"):
        start = intervals.combine(day, at)
        end = start + timedelta(minutes=int(policy.get_setting(conn, "period_length_minutes")))
        result = drill.run(conn, actor, room, start, end, db_path=str(config.DB_PATH))
        components.kpis([
            (result["successes"], "reservations created", "green"),
            (result["conflicts"], "refused with alternatives", "amber"),
            (result["alternatives_min"], "alternatives on the smallest refusal", "teal"),
            (result["live_rows_in_window"], "live rows in the window afterwards", ""),
        ])
        st.write({"requests": result["requests"], "outcomes": result["codes"],
                  "elapsed_ms": result["elapsed_ms"], "verified": result["verified"]})
        st.dataframe([{"Thread": r["index"], "HTTP": r["http"], "Code": r["code"],
                       "Alternatives": r["alternatives"], "ms": r["ms"]}
                      for r in result["results"]], width="stretch", hide_index=True)
        if result["verified"]:
            st.success("Exactly one reservation exists for that room and window.")
        else:
            st.error("The drill did not converge on one row. This is a defect.")
