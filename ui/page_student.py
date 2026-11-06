"""The student front door. Students read; what they can do is speak -- a comment
attached to a reservation, and a structured report when something is wrong."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import availability, config, intervals, records
from ui import components, page_common


def my_schedule(conn, actor):
    components.band("My section's schedule", f"SECTION {actor.section}",
                     "Where to be, when, and what changed. Reading is the whole of a student's "
                     "access to the schedule.")
    day = st.date_input("Week starting", value=date.today(), key="sched_day")
    start = intervals.combine(day, "00:00")
    end = start + timedelta(days=7)
    entries = availability.section_schedule(conn, actor.section, start, end)

    live = [e for e in entries
            if e.get("status") in ("CONFIRMED", "PENDING_APPROVAL", "TIMETABLE")]
    cancelled = [e for e in entries if e.get("status") == "CANCELLED"]
    rooms = sorted({e["room_code"] for e in live})
    components.kpis([
        (len(live), "classes in the next seven days", "green"),
        (len(rooms), "different rooms", "teal"),
        (len(cancelled), "cancellations on record", "rose"),
        (len([e for e in entries if e["source"] == "TIMETABLE"]), "timetabled repeats", ""),
    ])

    if not entries:
        st.caption("Nothing scheduled in that window.")
        return

    rows = []
    for e in entries:
        when = intervals.parse_dt(e["start_at"])
        rows.append({
            "Day": f"{when:%a %d %b}", "Start": f"{when:%H:%M}",
            "End": intervals.parse_dt(e["end_at"]).strftime("%H:%M"),
            "Room": e["room_code"], "Where": e.get("room_label", ""),
            "Building": {"IET": "IET", "DB": "Deeksha Bhawan"}.get(e.get("building_code"), ""),
            "What": e.get("title") or e.get("purpose", "").title(),
            "Status": e.get("status", ""),
        })
    st.dataframe(rows, width="stretch", hide_index=True)

    upcoming = [e for e in live if intervals.parse_dt(e["start_at"]) >= datetime.now()]
    if upcoming:
        nxt = upcoming[0]
        components.callout(
            f"Next: <b>{nxt.get('title') or nxt['purpose']}</b> in {nxt['room_code']} "
            f"({nxt.get('room_label')}) — {components.fmt_range(nxt['start_at'], nxt['end_at'])}.", "key")

    recent_notices = [a for a in records.list_announcements(conn, actor.section, limit=5)]
    if recent_notices:
        st.markdown("#### Notices that affect you")
        for a in recent_notices:
            components.card(a["title"], f"{a['severity']} · {a['publish_at']}", a["body"])


def notices(conn, actor):
    components.band("Notices for your section", "COMMUNICATION",
                     "A change is carried to the people affected by it, at the moment it is made.")
    items = records.list_announcements(conn, actor.section, limit=50)
    if not items:
        st.caption("No notices yet.")
        return
    for a in items:
        components.card(a["title"],
                        f"{a['scope']} {a['scope_id'] or ''} · {a['severity']} · {a['publish_at']}",
                        f"<div style='font-size:.86rem'>{a['body']}</div>")


def report_problem(conn, actor):
    components.band("Report a problem", "STRUCTURED, NOT FREE TEXT",
                     "Structure is what makes a report triageable. Duplicates merge into one item "
                     "with a count, which is the signal an administrator needs.")
    start = intervals.combine(date.today() - timedelta(days=7), "00:00")
    end = start + timedelta(days=21)
    entries = [e for e in availability.section_schedule(conn, actor.section, start, end)
               if e["source"] == "BOOKING"]

    if not entries:
        st.caption("No reservations on your section's record to report on.")
    else:
        labels = {
            e["id"]: f"#{e['id']} · {e['room_code']} · {components.fmt_range(e['start_at'], e['end_at'])}"
            for e in entries}
        with st.form("report"):
            booking_id = st.selectbox("Which reservation?", list(labels), key="rep_booking",
                                      format_func=lambda k: labels[k])
            kind = st.selectbox("What is wrong?", config.REPORT_KINDS, key="rep_kind",
                                format_func=lambda k: config.REPORT_KIND_LABELS[k])
            body = st.text_area("Tell us what you saw", key="rep_body",
                                placeholder="The class was moved to IET18 but the schedule still shows LH01.")
            if st.form_submit_button("Send the report", type="primary"):
                outcome = records.create_report(conn, actor, booking_id, kind, body)
                if outcome["ok"] and outcome.get("merged"):
                    st.info(f"Merged into report #{outcome['report_id']}; this reservation now has "
                            f"{outcome['count']} reports.")
                elif outcome["ok"]:
                    st.success(f"Report #{outcome['report_id']} created. You will be told the outcome.")
                else:
                    st.error(f"{outcome['code']} · {outcome['message']}")

    st.divider()
    st.markdown("#### Comment on a reservation")
    st.caption("A comment is visible to the owner of the reservation and to an administrator.")
    if entries:
        with st.form("comment"):
            booking_id = st.selectbox("Reservation", [e["id"] for e in entries], key="cm_booking",
                                      format_func=lambda k: labels[k])
            body = st.text_area("Comment", key="cm_body")
            if st.form_submit_button("Add the comment"):
                outcome = records.comment(conn, actor, booking_id, body)
                if outcome["ok"]:
                    st.success("Comment recorded on the thread.")
                else:
                    st.error(f"{outcome['code']} · {outcome['message']}")

    st.divider()
    st.markdown("#### Reports you can see on your section")
    mine = [r for r in records.open_reports(conn) if r["section_code"] == actor.section]
    if not mine:
        st.caption("No open reports for your section.")
    for r in mine:
        components.card(
            f"{config.REPORT_KIND_LABELS.get(r['kind'], r['kind'])}",
            f"Report #{r['id']} · reservation #{r['booking_id']} · {r['report_count']} reports",
            f"<div style='font-size:.85rem'>Room {r['room_code']}, "
            f"{components.fmt_range(r['start_at'], r['end_at'])}</div>")
