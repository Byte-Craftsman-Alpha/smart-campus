"""Shared Streamlit chrome: the palette, the bands and the small components that
give the prototype the same visual language as the design document."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import config, intervals

P = config.PALETTE

CSS = f"""
<style>
:root {{
  --navy-deep: {P['navy_deep']};
  --navy: {P['navy']};
  --teal: {P['teal']};
  --amber: {P['amber']};
  --rose: {P['rose']};
  --green: {P['green']};
  --ink: {P['ink']};
  --ink2: {P['ink2']};
  --ink3: {P['ink3']};
  --rule: {P['rule']};
  --band: {P['band']};
}}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
html, body, [class*="css"] {{ font-family: "DejaVu Sans", "Segoe UI", system-ui, sans-serif; }}
h1, h2, h3 {{ color: var(--navy-deep); letter-spacing: -0.01em; }}

.sc-band {{
  background: var(--navy-deep); color: #fff; padding: 16px 20px 14px 20px;
  border-radius: 2px; margin: 0 0 14px 0;
}}
.sc-band .eyebrow {{ font-size: .62rem; letter-spacing: .18em; color: #9FB4E8; text-transform: uppercase; }}
.sc-band h1 {{ color: #fff !important; font-size: 1.55rem; margin: .25rem 0 0 0; font-weight: 700; }}
.sc-band p {{ color: #C7D3EC; margin: .3rem 0 0 0; font-size: .86rem; }}
.sc-band .tick {{ display:inline-block; width:44px; height:3px; background: var(--teal); margin-top:12px; }}

.sc-part {{
  background: var(--navy); color: #fff; padding: 10px 16px; border-radius: 2px;
  border-left: 6px solid var(--teal); margin: 4px 0 14px 0;
}}
.sc-part .k {{ font-size:.6rem; letter-spacing:.16em; color:#9FB4E8; }}
.sc-part .t {{ font-size: 1.02rem; font-weight: 600; }}

.sc-kpis {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 6px 0 14px 0; }}
.sc-kpi {{
  flex: 1 1 130px; border-radius: 3px; padding: 12px 14px; background: var(--band);
  border: 1px solid var(--rule);
}}
.sc-kpi .v {{ font-size: 1.5rem; font-weight: 700; color: var(--navy-deep); line-height: 1.1; }}
.sc-kpi .l {{ font-size: .72rem; color: var(--ink3); margin-top: 2px; }}
.sc-kpi.teal {{ background: {P['tint_teal']}; border-color: #BFDCDA; }}
.sc-kpi.teal .v {{ color: var(--teal); }}
.sc-kpi.amber {{ background: {P['tint_amber']}; border-color: #EBD9B6; }}
.sc-kpi.amber .v {{ color: var(--amber); }}
.sc-kpi.rose {{ background: {P['tint_rose']}; border-color: #EBC8C7; }}
.sc-kpi.rose .v {{ color: var(--rose); }}
.sc-kpi.green {{ background: {P['tint_green']}; border-color: #C4DFD0; }}
.sc-kpi.green .v {{ color: var(--green); }}

.sc-chip {{
  display: inline-block; font-size: .68rem; letter-spacing: .06em; padding: 2px 8px;
  border-radius: 10px; font-weight: 600; text-transform: uppercase;
}}
.chip-confirmed {{ background: {P['tint_green']}; color: {P['green']}; }}
.chip-pending {{ background: {P['tint_amber']}; color: {P['amber']}; }}
.chip-cancelled {{ background: {P['tint_rose']}; color: {P['rose']}; }}
.chip-other {{ background: {P['tint_navy']}; color: {P['navy']}; }}
.chip-test {{ background: #EEF0F4; color: var(--ink3); }}

.sc-card {{
  border: 1px solid var(--rule); border-radius: 3px; padding: 12px 14px;
  background: #fff; margin-bottom: 8px;
}}
.sc-card h4 {{ margin: 0 0 2px 0; color: var(--navy-deep); font-size: .95rem; }}
.sc-card .meta {{ color: var(--ink3); font-size: .78rem; }}
.sc-callout {{
  background: {P['tint_navy']}; border-left: 4px solid var(--navy);
  padding: 10px 14px; border-radius: 2px; color: var(--ink); font-size: .86rem;
}}
.sc-key {{
  background: {P['tint_teal']}; border-left: 4px solid var(--teal);
  padding: 10px 14px; border-radius: 2px; color: var(--ink); font-size: .86rem;
}}
.sc-warn {{
  background: {P['tint_amber']}; border-left: 4px solid var(--amber);
  padding: 10px 14px; border-radius: 2px; color: var(--ink); font-size: .86rem;
}}
.sc-rule {{ height:1px; background: var(--rule); margin: 12px 0 14px 0; }}
.sc-mono {{ font-family: "DejaVu Sans Mono", monospace; font-size: .8rem; }}
div[data-testid="stSidebarNav"] {{ display: none; }}
.stButton > button {{ border-radius: 2px; }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def band(title: str, eyebrow: str = "", subtitle: str = "") -> None:
    st.markdown(
        f"""<div class="sc-band"><div class="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>{f'<p>{subtitle}</p>' if subtitle else ''}
        <div class="tick"></div></div>""",
        unsafe_allow_html=True)


def part(label: str, title: str) -> None:
    st.markdown(
        f'<div class="sc-part"><div class="k">{label}</div><div class="t">{title}</div></div>',
        unsafe_allow_html=True)


def kpis(items) -> None:
    """items: list of (value, label, tone) with tone in '', teal, amber, rose, green."""
    html = "".join(
        f'<div class="sc-kpi {tone}"><div class="v">{value}</div><div class="l">{label}</div></div>'
        for value, label, tone in items)
    st.markdown(f'<div class="sc-kpis">{html}</div>', unsafe_allow_html=True)


def chip(status: str) -> str:
    cls = {
        "CONFIRMED": "chip-confirmed",
        "PENDING_APPROVAL": "chip-pending",
        "CANCELLED": "chip-cancelled",
        "REJECTED": "chip-cancelled",
        "DISPLACED": "chip-pending",
        "COMPLETED": "chip-other",
        "TIMETABLE": "chip-other",
    }.get(status, "chip-other")
    return f'<span class="sc-chip {cls}">{status.replace("_", " ")}</span>'


def callout(text: str, kind: str = "callout") -> None:
    st.markdown(f'<div class="sc-{kind}">{text}</div>', unsafe_allow_html=True)


def rule() -> None:
    st.markdown('<div class="sc-rule"></div>', unsafe_allow_html=True)


def card(title: str, meta: str, body_html: str = "", test_flag: bool = False) -> None:
    flag = ' <span class="sc-chip chip-test">test data</span>' if test_flag else ""
    st.markdown(
        f'<div class="sc-card"><h4>{title}{flag}</h4>'
        f'<div class="meta">{meta}</div>{body_html}</div>',
        unsafe_allow_html=True)


# ------------------------------------------------------------------ time input
def time_options(conn):
    """The registry grid, padded either side, so a custom window stays easy."""
    grid = []
    from core import availability
    for p in availability.period_grid(conn):
        grid.append(p["start"])
    grid.append("17:10")
    return grid


def date_time_picker(conn, prefix: str, default_day: date | None = None,
                     default_time: str = "10:00", duration_options=(55, 110)):
    cols = st.columns([1, 1, 1])
    with cols[0]:
        day = st.date_input("Date", value=default_day or date.today(), key=f"{prefix}_day")
    options = time_options(conn)
    idx = options.index(default_time) if default_time in options else 0
    with cols[1]:
        start_hhmm = st.selectbox("Start", options, index=idx, key=f"{prefix}_start")
    with cols[2]:
        duration = st.selectbox("Duration (minutes)", list(duration_options),
                                index=0, key=f"{prefix}_dur")
    start = intervals.combine(day, start_hhmm)
    end = start + timedelta(minutes=int(duration))
    return start, end


def fmt_range(start, end) -> str:
    s, e = intervals.parse_dt(start), intervals.parse_dt(end)
    return f"{s:%a %d %b, %H:%M}–{e:%H:%M}"


def pretty(value: str) -> str:
    return value.replace("_", " ").title()
