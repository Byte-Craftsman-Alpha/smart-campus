"""The faculty front door: four screens, and the part that has to feel fast."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import availability, booking, intervals, policy, records
from ui import components, page_common


def my_reservations(conn, actor):
    components.band("My reservations", "FACULTY",
                     "Every state change is a status change with a reason attached. Nothing is "
                     "deleted, ever.")
    rows = [dict(r) for r in conn.execute(
        """SELECT b.*, r.label AS room_label, f.building_code
           FROM booking b JOIN room r ON r.code=b.room_code JOIN floor f ON f.id=r.floor_id
           WHERE b.faculty_id=? ORDER BY b.start_at DESC""", (actor.faculty_id,))]
    live = [r for r in rows if r["status"] in ("CONFIRMED", "PENDING_APPROVAL")]
    pending = [r for r in rows if r["status"] == "PENDING_APPROVAL"]
    cancelled = [r for r in rows if r["status"] == "CANCELLED"]
    components.kpis([
        (len(live), "live reservations", "green"),
        (len(pending), "waiting for approval", "amber"),
        (len(cancelled), "cancelled, kept on record", "rose"),
        (len(rows), "rows in your history", ""),
    ])

    if not rows:
        st.caption("Nothing booked yet. Use Find a room to place your first reservation.")
        return

    for row in rows:
        status_chip = components.chip(row["status"])
        with st.container():
            st.markdown(
                f"**{row['room_code']}** · {row['room_label']} · {row['building_code']}<br>"
                f"{components.fmt_range(row['start_at'], row['end_at'])} · "
                f"{row['purpose'].title()} · {row['headcount']} people · "
                f"{row['section_code'] or 'no section'} &nbsp; {status_chip}",
                unsafe_allow_html=True)
            if row["status"] in ("CONFIRMED", "PENDING_APPROVAL"):
                with st.expander("Work on this reservation"):
                    tabs = st.tabs(["Cancel", "Reschedule", "Finish early"])

                    with tabs[0]:
                        reason = st.text_input("Reason for cancelling", key=f"cancel_reason_{row['id']}",
                                               placeholder="Faculty on duty leave")
                        if st.button("Cancel this reservation", key=f"cancel_btn_{row['id']}"):
                            outcome = booking.cancel(conn, actor, row["id"], reason)
                            page_common.render_result(outcome, action="cancelled")

                    with tabs[1]:
                        new_day = st.date_input("New date", value=intervals.parse_dt(row["start_at"]).date(),
                                                key=f"res_day_{row['id']}")
                        grid = [p["start"] for p in availability.period_grid(conn)]
                        cur_start = intervals.parse_dt(row["start_at"]).strftime("%H:%M")
                        new_start = st.selectbox("New start", grid,
                                                 index=grid.index(cur_start) if cur_start in grid else 0,
                                                 key=f"res_start_{row['id']}")
                        new_dur = st.selectbox("Duration (minutes)", [55, 110], key=f"res_dur_{row['id']}")
                        if st.button("Move it", key=f"res_btn_{row['id']}"):
                            s = intervals.combine(new_day, new_start)
                            outcome = booking.reschedule(conn, actor, row["id"], s,
                                                         s + timedelta(minutes=int(new_dur)),
                                                         reason="Rescheduled by the owner")
                            page_common.render_result(outcome, action="moved")

                    with tabs[2]:
                        st.caption("The remainder of the interval returns to the pool. Attendance "
                                   "is a separate record and is never touched.")
                        options = intervals.hhmm_between(row["start_at"], row["end_at"])
                        new_end = st.selectbox("Class actually ends at", options,
                                               index=max(0, len(options) - 2),
                                               key=f"release_{row['id']}")
                        if st.button("Release the rest of the period", key=f"release_btn_{row['id']}"):
                            outcome = booking.early_release(
                                conn, actor, row["id"], intervals.combine(
                                    intervals.parse_dt(row["start_at"]).date(), new_end))
                            page_common.render_result(outcome, action="released")
            components.rule()


def find_room(conn, actor):
    page_common.availability_explorer(conn, actor)


def weekly_series(conn, actor):
    components.band("Weekly series", "RECURRING CLASSES",
                     "A series is created and cancelled as one action, never as eight unrelated "
                     "bookings.")
    sections = [r["code"] for r in conn.execute("SELECT code FROM section ORDER BY code")]
    rooms = [r["code"] for r in availability.rooms(conn)]
    with st.form("series"):
        c = st.columns(4)
        with c[0]:
            day = st.date_input("First date", value=date.today() + timedelta(days=1), key="ser_day")
        with c[1]:
            grid = [p["start"] for p in availability.period_grid(conn)]
            start_hhmm = st.selectbox("Start", grid, index=5, key="ser_start")
        with c[2]:
            duration = st.selectbox("Duration (min)", [55, 110], index=0, key="ser_dur")
        with c[3]:
            weeks = st.number_input("Weeks", min_value=1, max_value=18, value=4, key="ser_weeks")
        c2 = st.columns(3)
        with c2[0]:
            room_code = st.selectbox("Room", rooms, key="ser_room")
        with c2[1]:
            section = st.selectbox("Section", sections, key="ser_section")
        with c2[2]:
            purpose = st.selectbox("Purpose", ["CLASS", "PRACTICAL", "TUTORIAL"], key="ser_purpose")
        go = st.form_submit_button("Create the series", type="primary")
    if go:
        start = intervals.combine(day, start_hhmm)
        outcome = booking.create_series(
            conn, actor, room_code, start, start + timedelta(minutes=int(duration)),
            weekday=intervals.parse_dt(start).strftime("%a").upper()[:3], weeks=int(weeks),
            purpose=purpose, headcount=75, section_code=section)
        if outcome.get("ok"):
            st.success(f"Series {outcome['series_id']} created: {len(outcome['created'])} bookings.")
        else:
            st.error(f"{outcome.get('code')} · {outcome.get('message')}")
        for failure in outcome.get("failed", []):
            st.warning(f"week {failure['week']}: {failure['code']} — {failure['message']}")

    series_rows = [dict(r) for r in conn.execute(
        """SELECT s.id, s.recurrence_rule, s.created_by, COUNT(b.id) AS live
           FROM booking_series s LEFT JOIN booking b ON b.series_id = s.id
             AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
           GROUP BY s.id ORDER BY s.id DESC""")]
    if series_rows:
        st.markdown("#### Series on record")
        st.dataframe([{"Series": r["id"], "Rule": r["recurrence_rule"],
                       "Live bookings": r["live"], "Created by": r["created_by"]}
                      for r in series_rows], width="stretch", hide_index=True)
        with st.form("cancel_series"):
            c = st.columns([1, 2])
            with c[0]:
                series_id = st.selectbox("Series to cancel", [r["id"] for r in series_rows],
                                         key="cancel_series_id")
            with c[1]:
                reason = st.text_input("Reason", key="cancel_series_reason")
            if st.form_submit_button("Cancel the whole series"):
                outcome = booking.cancel_series(conn, actor, series_id, reason)
                st.success(f"Cancelled {len(outcome.get('cancelled', []))} bookings; "
                           f"{len(outcome.get('refused', []))} refused.")


def notices(conn, actor):
    components.band("Notices", "COMMUNICATION",
                     "A notice is how a change reaches the people affected by it.")
    sections = [r["code"] for r in conn.execute("SELECT code FROM section ORDER BY code")]
    with st.form("faculty_notice"):
        c = st.columns([1, 1])
        with c[0]:
            section = st.selectbox("Section", sections, key="notice_section")
        with c[1]:
            severity = st.selectbox("Severity", ["INFO", "IMPORTANT", "URGENT"], key="notice_sev")
        title = st.text_input("Title", key="notice_title")
        body = st.text_area("Body", key="notice_body")
        if st.form_submit_button("Publish to this section", type="primary"):
            outcome = records.publish(conn, actor, title, body, scope="SECTION",
                                      scope_id=section, severity=severity)
            if outcome["ok"]:
                st.success(f"Published; {outcome['notified']} outbox rows written.")
            else:
                st.error(f"{outcome['code']} · {outcome['message']}")

    st.markdown("#### Recent notices")
    for a in records.list_announcements(conn, limit=25):
        components.card(a["title"],
                        f"{a['scope']} {a['scope_id'] or ''} · {a['severity']} · "
                        f"{a['publish_at']} · v{a['version']}",
                        f"<div style='font-size:.85rem'>{a['body']}</div>")
