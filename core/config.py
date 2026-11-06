"""Paths, vocabulary and default policy for the Smart Campus prototype.

Everything here mirrors the corrected design document:
  - section 6.2  seventeen entities
  - section 10   edge-case behaviour
  - section 12.3 six configuration values that must not be hard-coded
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REGISTRY_PATH = DATA_DIR / "campus_room_registry.json"
DB_PATH = ROOT / "smart_campus.db"

APP_NAME = "Smart Campus Classroom Management"
APP_TAGLINE = "GDG on Campus, DDUGU  ·  Build With AI: DevOps 2026"

# ------------------------------------------------------------------ vocabulary
ROLES = ["student", "faculty", "admin"]

STATUSES = [
    "PENDING_APPROVAL",
    "CONFIRMED",
    "CANCELLED",
    "REJECTED",
    "COMPLETED",
    "DISPLACED",
]

#: A row only occupies its interval while it is live. Section 4.3.
LIVE_STATUSES = ("CONFIRMED", "PENDING_APPROVAL")

PURPOSES = [
    "CLASS",
    "PRACTICAL",
    "TUTORIAL",
    "EXAM",
    "SEMINAR",
    "WORKSHOP",
    "EVENT",
    "ORIENTATION",
    "VIVA",
    "INTERVIEW",
]

#: Purposes that are placed against spaced (examination) capacity. Section 9.3.
EXAM_PURPOSES = ("EXAM",)

REPORT_KINDS = [
    "WRONG_ROOM",
    "CANCELLED_STILL_SHOWING",
    "CLASH_WITH_ANOTHER_CLASS",
    "OUTDATED_INFORMATION",
    "OTHER",
]

REPORT_KIND_LABELS = {
    "WRONG_ROOM": "The room shown is wrong",
    "CANCELLED_STILL_SHOWING": "A cancelled class is still showing",
    "CLASH_WITH_ANOTHER_CLASS": "Two classes are shown in the same room",
    "OUTDATED_INFORMATION": "The information is out of date",
    "OTHER": "Something else",
}

ANNOUNCEMENT_SEVERITIES = ["INFO", "IMPORTANT", "URGENT"]

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

#: Defaults for the six settings of section 12.3. All six are editable at run
#: time and every change writes a row into setting_history.
DEFAULT_SETTINGS = {
    "period_length_minutes": 55,
    "periods_per_day": 8,
    "lunch_start": "12:40",
    "lunch_end": "13:30",
    "exam_spacing_factor": 0.5,
    "min_cross_building_gap_minutes": 10,
    "booking_horizon_days": 60,
    "min_lead_time_minutes": 15,
    "approval_headcount_threshold": 100,
    "snap_minutes": 5,
    "score_weight_tight_fit": 0.35,
    "score_weight_same_building": 0.20,
    "score_weight_walk_time": 0.20,
    "score_weight_window_shift": 0.15,
    "score_weight_features": 0.10,
    "demo_mode": 1,
}

#: Ranked scoring weights are visible in the administrator settings (section 5.1).
SCORE_WEIGHTS = {
    "tight fit": "score_weight_tight_fit",
    "same building": "score_weight_same_building",
    "walk time": "score_weight_walk_time",
    "window shift": "score_weight_window_shift",
    "required features": "score_weight_features",
}

#: Rooms whose booking always needs an administrator. Section 5, permission matrix.
GATED_ROOM_TYPES = ("SEMINAR", "LIBRARY")

#: Buildings and the walking costs between them (registry meta.inter_building).
BUILDING_LABELS = {
    "IET": "Institute of Engineering and Technology",
    "DB": "Deeksha Bhawan",
}

MAX_PLAUSIBLE_WALK_SECONDS = 900

#: Palette shared with the design document, so the prototype and the report look
#: like the same project.
PALETTE = {
    "navy_deep": "#16264D",
    "navy": "#1B2F5E",
    "teal": "#0C6E6E",
    "amber": "#A56A11",
    "rose": "#9E2F32",
    "green": "#1E6F45",
    "ink": "#1B1F27",
    "ink2": "#46505F",
    "ink3": "#6D7887",
    "rule": "#D8DEE8",
    "band": "#F5F7FC",
    "tint_navy": "#EDF1FA",
    "tint_teal": "#E3F2F1",
    "tint_amber": "#FBF2E1",
    "tint_rose": "#FBEBEA",
    "tint_green": "#E6F3EC",
}
