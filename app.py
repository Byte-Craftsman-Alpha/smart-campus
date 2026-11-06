"""Smart Campus Classroom Management -- Streamlit prototype.

Sign in as a student, a member of faculty or an administrator. Every screen is
a front door onto the same record: rooms are timelines, conflicts are refused
by the storage engine, and nothing is ever deleted.
"""
from __future__ import annotations

import traceback
from datetime import date

import streamlit as st

from core import analytics, booking, config, db, policy
from ui import components, page_common, page_admin, page_faculty, page_student

st.set_page_config(page_title="Smart Campus", page_icon="🏫", layout="wide",
                   initial_sidebar_state="expanded")

DEMO_ACCOUNTS = {
    "faculty": ("a.verma@iet.example.edu", "faculty123", "Dr A. Verma · Computer Science"),
    "student": ("CSE-3A-01", "student123", "Roll CSE-3A-01 · section CSE-3A"),
    "admin": ("registrar", "admin123", "Registrar · administrative account"),
}


@st.cache_resource(show_spinner="Preparing the campus register…")
def get_conn():
    return db.ensure_db()


def reset_demo():
    get_conn.clear()
    db.reset_db()
    st.session_state.pop("actor", None)
    st.session_state.pop("chat", None)


# ------------------------------------------------------------------ sign-in
def sign_in_screen(conn):
    components.band("Smart Campus Classroom Management", config.APP_TAGLINE,
                     "Room allocation across the Institute of Engineering and Technology "
                     "and Deeksha Bhawan")
    st.markdown("#### Sign in")
    components.callout(
        "Three demonstration accounts, as the definition of done asks for. "
        "Each one opens a different front door onto the same record.", "key")

    cols = st.columns(3)
    for col, (role, (login, pwd, note)) in zip(cols, DEMO_ACCOUNTS.items()):
        with col:
            st.markdown(f"**{role.title()}**")
            st.caption(note)
            st.code(f"{login}\n{pwd}", language="text")

    # Outside the form: a callback cannot be attached to a widget inside one, and
    # keying the fields by role is what makes switching role offer that role's
    # demonstration account rather than the previous one.
    role = st.selectbox("Role", ["faculty", "student", "admin"], key="signin_role")
    with st.form("signin"):
        login = st.text_input("Login", value=DEMO_ACCOUNTS[role][0],
                              key=f"signin_login_{role}")
        password = st.text_input("Password", value=DEMO_ACCOUNTS[role][1], type="password",
                                 key=f"signin_password_{role}")
        submitted = st.form_submit_button("Sign in", type="primary")

    if submitted:
        actor = authenticate(conn, role, login.strip(), password)
        if actor is None:
            st.error("That login does not match the demonstration account for this role.")
        else:
            st.session_state["actor"] = actor
            st.rerun()

    st.divider()
    st.caption("No data leaves this machine. The register is seeded from "
               "data/campus_room_registry.json and stored in smart_campus.db.")


def authenticate(conn, role, login, password):
    expected = DEMO_ACCOUNTS[role][1]
    if password != expected:
        return None
    if role == "faculty":
        row = conn.execute("SELECT * FROM faculty WHERE email=?", (login,)).fetchone()
        if row is None:
            return None
        return policy.Actor(row["email"], "faculty", row["name"],
                            faculty_id=row["id"], home_building=row["home_building"])
    if role == "student":
        row = conn.execute("SELECT * FROM student WHERE roll_number=?", (login,)).fetchone()
        if row is None:
            return None
        return policy.Actor(row["roll_number"], "student", row["name"],
                            section=row["section_code"])
    if role == "admin":
        if login not in ("registrar", "admin"):
            return None
        return policy.Actor("ADM-01", "admin", "Registrar")
    return None


# ------------------------------------------------------------------ shell
NAV = {
    "student": [
        ("My schedule", page_student.my_schedule),
        ("Room availability", page_common.availability_explorer),
        ("Notices", page_student.notices),
        ("Report a problem", page_student.report_problem),
        ("Ask the assistant", page_common.assistant_page),
    ],
    "faculty": [
        ("My reservations", page_faculty.my_reservations),
        ("Find a room", page_faculty.find_room),
        ("Weekly series", page_faculty.weekly_series),
        ("Notices", page_faculty.notices),
        ("Ask the assistant", page_common.assistant_page),
    ],
    "admin": [
        ("At a glance", page_admin.dashboard),
        ("Approval queue", page_admin.approval_queue),
        ("Room register", page_admin.room_register),
        ("Closures", page_admin.closures),
        ("Reports", page_admin.report_queue),
        ("Policy settings", page_admin.policy_settings),
        ("Audit trail", page_admin.audit_trail),
        ("Announcements", page_admin.announcements),
        ("Concurrency drill", page_admin.concurrency_drill),
        ("Ask the assistant", page_common.assistant_page),
    ],
}


def shell(conn, actor):
    with st.sidebar:
        st.markdown(
            f'<div class="sc-part"><div class="k">{actor.role.upper()}</div>'
            f'<div class="t">{actor.name}</div></div>', unsafe_allow_html=True)
        if actor.section:
            st.caption(f"Section {actor.section}")
        if actor.faculty_id:
            st.caption(f"Faculty id {actor.faculty_id}")
        pages = NAV[actor.role]
        choice = st.radio("Navigation", [name for name, _ in pages], key="nav")
        st.divider()
        if actor.role == "admin":
            if st.button("Reset demonstration data", key="reset_demo"):
                reset_demo()
                st.rerun()
        if st.button("Sign out", key="signout"):
            st.session_state.pop("actor", None)
            st.rerun()
        st.caption("Prototype · issue 1.0 · all demonstration data is flagged")

    page = dict(pages)[choice]
    try:
        page(conn, actor)
    except Exception:                     # a broken screen must say so, loudly
        st.error("This screen failed. The traceback is below so it can be fixed.")
        st.code(traceback.format_exc(), language="text")


def main():
    components.inject()
    conn = get_conn()
    booking.complete_past(conn)
    actor = st.session_state.get("actor")
    if actor is None:
        sign_in_screen(conn)
    else:
        shell(conn, actor)


main()
