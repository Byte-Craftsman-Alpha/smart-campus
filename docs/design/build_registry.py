import json
from collections import Counter

rooms = []
def R(**kw): rooms.append(kw)

# ---------- IET GROUND FLOOR ----------
R(code="LIB", building="IET", floor="GF", label="Library", rtype="LIBRARY", capacity=180,
  exam_capacity=90, bookable=True, permitted_uses=["EXAM", "ORIENTATION", "EVENT", "SEMINAR"],
  features=["desks", "reading_hall", "power"], zone="IET-GF-WEST", near_stairs="IET-STAIR-C",
  accessibility="step_free", unconfirmed=False,
  notes="Dual-use: reading hall + examination venue. Bookable only outside library hours or by Director approval.")
R(code="TO", building="IET", floor="GF", label="Teachers' Office / Faculty Cabins", rtype="OFFICE", capacity=0,
  exam_capacity=0, bookable=False, permitted_uses=[], features=[], zone="IET-GF-WEST",
  near_stairs="IET-STAIR-C", accessibility="step_free", unconfirmed=False,
  notes="Not bookable. Anchor location for faculty identity and approval routing.")
R(code="DO", building="IET", floor="GF", label="Director's Office", rtype="OFFICE", capacity=0, exam_capacity=0,
  bookable=False, permitted_uses=[], features=[], zone="IET-GF-EAST", near_stairs="IET-STAIR-C",
  accessibility="step_free", unconfirmed=False, notes="Administrator role anchor; not bookable.")
R(code="PC", building="IET", floor="GF", label="Placement Cell", rtype="OFFICE", capacity=0, exam_capacity=0,
  bookable=False, permitted_uses=["INTERVIEW"], features=[], zone="IET-GF-EAST", near_stairs="IET-STAIR-C",
  accessibility="step_free", unconfirmed=False,
  notes="Hosts interviews; modelled as office, bookable by admin only (extension, not required by the statement).")

# ---------- IET FIRST FLOOR ----------
for code, br in [("IET22", "CSE"), ("IET16", "ME"), ("IET14", "ECE"), ("IET15", "IT")]:
    R(code=code, building="IET", floor="FF", label="Room " + code, rtype="LAB", capacity=75, exam_capacity=37,
      bookable=True, permitted_uses=["PRACTICAL", "CLASS", "EXAM", "EVENT"],
      features=["lab_benches", "power", "projector"], zone="IET-FF-NORTH", near_stairs="IET-STAIR-C",
      accessibility="stairs_only", lab_branch=br, unconfirmed=True,
      notes="Blueprint draws a plain room; the statement calls the four first-floor north rooms the CSE/ME/ECE/IT laboratories. Modelled as LAB (switch room_type to CLASS in one config row if organisers clarify).")
for code in ["IET20", "IET19", "IET18", "IET17"]:
    R(code=code, building="IET", floor="FF", label="Room " + code, rtype="CLASS", capacity=75, exam_capacity=37,
      bookable=True, permitted_uses=["CLASS", "TUTORIAL", "EXAM", "EVENT"],
      features=["projector", "whiteboard"], zone="IET-FF-SOUTH", near_stairs="IET-STAIR-C",
      accessibility="stairs_only", unconfirmed=False,
      notes="Standard classroom, ~75 capacity (stated).")

# ---------- IET SECOND FLOOR ----------
R(code="IET32", building="IET", floor="SF", label="Seminar Hall (IET32)", rtype="SEMINAR", capacity=200,
  exam_capacity=100, bookable=True,
  permitted_uses=["SEMINAR", "EVENT", "EXAM", "WORKSHOP", "ORIENTATION"],
  features=["pa_system", "projector", "stage", "podium"], zone="IET-SF-WEST", near_stairs="IET-STAIR-C",
  accessibility="stairs_only", unconfirmed=False,
  notes="Largest IET venue; primary overflow and examination hall. On the 2nd floor with no lift.")
for code in ["IET24", "IET25"]:
    R(code=code, building="IET", floor="SF", label="Room " + code, rtype="CLASS", capacity=75, exam_capacity=37,
      bookable=True, permitted_uses=["CLASS", "TUTORIAL", "EXAM", "EVENT"],
      features=["projector", "whiteboard"], zone="IET-SF-NORTH", near_stairs="IET-STAIR-C",
      accessibility="stairs_only", unconfirmed=False, notes="Standard classroom, ~75 capacity.")
for code in ["IET30", "IET29", "IET28", "IET23"]:
    R(code=code, building="IET", floor="SF", label="Room " + code, rtype="CLASS", capacity=75, exam_capacity=37,
      bookable=True, permitted_uses=["CLASS", "TUTORIAL", "EXAM", "EVENT"],
      features=["projector", "whiteboard"], zone="IET-SF-SOUTH", near_stairs="IET-STAIR-C",
      accessibility="stairs_only", unconfirmed=(code == "IET23"),
      notes=("Drawn on the blueprint; the statement lists only IET24/25/28/29/30. Kept bookable and flagged unconfirmed."
             if code == "IET23" else "Standard classroom, ~75 capacity."))
R(code="IET-SF-STORE", building="IET", floor="SF", label="Unlabelled room beside stairwell", rtype="SERVICE",
  capacity=0, exam_capacity=0, bookable=False, permitted_uses=[], features=[], zone="IET-SF-NORTH",
  near_stairs="IET-STAIR-C", accessibility="stairs_only", unconfirmed=True,
  notes="Narrow unlabelled space between the stairs and IET24. Non-bookable service room.")

# ---------- DEEKSHA BHAWAN ----------
for code, cap in [("LH01", 80), ("LH02", 80), ("LH03", 45), ("LH04", 45), ("LH05", 45),
                  ("LH06", 55), ("LH07", 55)]:
    R(code=code, building="DB", floor="GF", label=code + " (Deeksha Bhawan)", rtype="CLASS", capacity=cap,
      exam_capacity=cap // 2, bookable=True,
      permitted_uses=["CLASS", "TUTORIAL", "EXAM", "EVENT", "VIVA"],
      features=["whiteboard", "power"], zone="DB-GF", near_stairs="DB-STAIR-GF", accessibility="step_free",
      unconfirmed=False,
      notes="Capacity is absent from the source data. Value inferred from plan geometry (long open-plan room vs compact room) and is CONFIGURABLE.")
for code, cap in [("LH08", 80), ("LH09", 80), ("LH10", 45), ("LH11", 45), ("LH12", 45),
                  ("LH13", 55), ("LH14", 55)]:
    R(code=code, building="DB", floor="FF", label=code + " (Deeksha Bhawan)", rtype="CLASS", capacity=cap,
      exam_capacity=cap // 2, bookable=True,
      permitted_uses=["CLASS", "TUTORIAL", "EXAM", "EVENT", "VIVA"],
      features=["whiteboard", "power"], zone="DB-FF", near_stairs="DB-STAIR-FF", accessibility="stairs_only",
      unconfirmed=(code in ("LH13", "LH14")),
      notes=("Blueprint shows LH13/LH14; the statement says LH01-LH12. Blueprint wins, flagged unconfirmed."
             if code in ("LH13", "LH14")
             else "Capacity absent from source data; inferred from plan geometry and CONFIGURABLE."))

data = {
    "meta": {
        "name": "DDUGU IET + Deeksha Bhawan room registry (seed data 1.0)",
        "source_of_truth": "Building blueprint on page 2 of BUILD_WITH_AI_DevOps_Problem_Statement.pdf",
        "reconciliation_rule": "Blueprint = source of truth for room IDENTITY and geometry. Statement = source of truth for stated capacities. Anything absent from both is CONFIGURABLE with a documented default.",
        "buildings": {
            "IET": {"name": "Institute of Engineering and Technology", "floors": ["GF", "FF", "SF"],
                    "stairs": ["IET-STAIR-C"], "lift": False, "entry": "IET-ENTRY-GF-CENTRE"},
            "DB": {"name": "Deeksha Bhawan", "floors": ["GF", "FF"],
                   "stairs": ["DB-STAIR-GF", "DB-STAIR-FF"], "lift": False, "entry": "DB-ENTRY-GF-SOUTH"}
        },
        "inter_building": {
            "IET<->DB": {"distance_m": 100, "walk_seconds_straight": 83,
                         "effort_seconds": {"GF-GF": 240, "GF-FF": 290, "FF-GF": 290, "FF-FF": 340,
                                            "SF-GF": 360, "SF-FF": 410},
                         "min_turnaround_minutes": 10,
                         "rule": "The auto-scheduler may never place two consecutive academic activities for the same section in different buildings with a gap shorter than 10 minutes."}
        }
    },
    "rooms": rooms,
    "period_grid": {
        "timezone": "Asia/Kolkata",
        "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
        "periods": [
            {"id": "P1", "start": "09:00", "end": "09:55"}, {"id": "P2", "start": "09:55", "end": "10:50"},
            {"id": "P3", "start": "10:50", "end": "11:45"}, {"id": "P4", "start": "11:45", "end": "12:40"},
            {"id": "P5", "start": "13:30", "end": "14:25"}, {"id": "P6", "start": "14:25", "end": "15:20"},
            {"id": "P7", "start": "15:20", "end": "16:15"}, {"id": "P8", "start": "16:15", "end": "17:10"}
        ],
        "lunch": {"start": "12:40", "end": "13:30"},
        "granularity_minutes": 5,
        "note": "Bookings are arbitrary half-open intervals [start,end) snapped to 5 minutes. The period grid exists only for the official timetable and for reporting."
    }
}
json.dump(data, open("campus_room_registry.json", "w"), indent=2)

# ---------- ANALYTICS ----------
bookable = [r for r in rooms if r["bookable"]]
print("rooms total:", len(rooms), "| bookable:", len(bookable))
print(Counter((r["building"], r["floor"]) for r in bookable))
print("IET bookable:", len([r for r in bookable if r["building"] == "IET"]),
      "| DB bookable:", len([r for r in bookable if r["building"] == "DB"]))
print("rooms cap>=75:", [r["code"] for r in bookable if r["capacity"] >= 75])
print("rooms exam_cap>=75:", [r["code"] for r in bookable if r["exam_capacity"] >= 75])

br = {"CSE": 150, "AIML": 150, "AIDS": 75, "ECE": 75, "ME": 75, "IT": 75}
sec = {"CSE": 2, "AIML": 2, "AIDS": 1, "ECE": 1, "ME": 1, "IT": 1}
per_year = sum(br.values()); sections = sum(sec.values())
print("students/year:", per_year, "| 4 years:", per_year * 4, "| sections/year:", sections, "| sections 4yr:", sections * 4)
print("largest section size:", max(br[b] / sec[b] for b in br))
S = len(bookable); P = 8
for k in (5, 6, 7):
    dem = sections * 4 * k
    print("demand %d periods/section/day = %d room-periods (%.1f%% of %d supply)" % (k, dem, dem / (S * P) * 100, S * P))

# peak slot pressure: assume 65% of a section's periods land in P1,P2,P5 (morning + post-lunch peaks)
peak = (sections * 4 * 6) * 0.55
print("peak-slot concentrated demand on 1 slot:", round(peak, 1), "vs room supply", S, "-> oversubscribed" if peak > S else "")
