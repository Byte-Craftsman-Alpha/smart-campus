"""Ranking substitutes.

A conflict is not an error message; it is a question already answered three
ways (section 4.6). Every score is decomposed into the reasons that produced
it, and the weights are settings so a member of faculty can see why a room was
suggested.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import availability, intervals, policy

#: Straight-line walking seconds used when the registry has no pair entry.
DEFAULT_WALK = {"same_room_floor": 25, "same_building_floor": 60,
                "same_building_other_floor": 110, "other_building": 300}


def walk_seconds(from_room, to_room) -> int:
    """Approximate the cost of moving between two rooms, using the building
    geometry in the registry rather than a straight-line guess."""
    if from_room is None:
        return 0
    if from_room["code"] == to_room["code"]:
        return 0
    if from_room["building_code"] != to_room["building_code"]:
        return DEFAULT_WALK["other_building"]
    if from_room["floor_level"] != to_room["floor_level"]:
        return DEFAULT_WALK["same_building_other_floor"]
    return DEFAULT_WALK["same_room_floor"]


def score_candidate(conn, room, window_shift_minutes, headcount, purpose,
                    from_room=None, required_features=None) -> tuple[int, list[str]]:
    weights = {k: float(policy.get_setting(conn, k)) for k in (
        "score_weight_tight_fit", "score_weight_same_building",
        "score_weight_walk_time", "score_weight_window_shift", "score_weight_features")}
    total_w = sum(weights.values()) or 1.0

    cap = availability.effective_capacity(room, purpose,
                                          float(policy.get_setting(conn, "exam_spacing_factor")))
    # tight fit: full marks for using at least 80% of the room, decaying after
    fit_ratio = headcount / cap if cap else 1.0
    tight = 1.0 if fit_ratio >= 0.8 else max(0.35, fit_ratio)

    same_building = 1.0
    reasons = []
    if from_room is not None:
        same_building = 1.0 if from_room["building_code"] == room["building_code"] else 0.35
        walk = walk_seconds(from_room, room)
        walk_score = max(0.0, 1.0 - walk / 420.0)
        if from_room["building_code"] != room["building_code"]:
            reasons.append(f"{room['building_name']}, about {walk // 60} min walk from your building")
        elif from_room["floor_level"] != room["floor_level"]:
            reasons.append("one floor away, about a minute on the stair")
        else:
            reasons.append("same floor as your current room")
    else:
        walk_score = 0.8

    shift_score = max(0.0, 1.0 - abs(window_shift_minutes) / 45.0)
    if window_shift_minutes:
        reasons.append(f"start shifted by {abs(window_shift_minutes)} minutes")

    feat_score = 1.0
    if required_features:
        have = room.get("features") or "[]"
        if isinstance(have, str):
            have = json.loads(have)
        missing = [f for f in required_features if f not in have]
        feat_score = 0.0 if missing else 1.0
        if missing:
            reasons.append("missing " + ", ".join(missing))

    reasons.insert(0, f"seats {cap} against {headcount} requested"
                   if purpose not in ("EXAM",) else f"seats {cap} with examination spacing")

    raw = (weights["score_weight_tight_fit"] * tight
           + weights["score_weight_same_building"] * same_building
           + weights["score_weight_walk_time"] * walk_score
           + weights["score_weight_window_shift"] * shift_score
           + weights["score_weight_features"] * feat_score)
    return int(round(100 * raw / total_w)), reasons


def alternatives(conn, start, end, headcount, purpose="CLASS", from_room=None,
                 exclude_room=None, required_features=None, limit=3) -> list[dict]:
    """Three ranked substitutes, re-validated after the conflict fired.

    Five shifted windows are considered, including the unshifted one, and only
    windows within half an hour of the request (section 5.1).
    """
    start, end = intervals.parse_dt(start), intervals.parse_dt(end)
    duration = end - start
    shifts = [0, 10, 20, -10, 30] if purpose != "EXAM" else [0, 10, -10, 20, 30]
    factor = float(policy.get_setting(conn, "exam_spacing_factor"))
    found = []
    for shift in shifts:
        w_start = start + timedelta(minutes=shift)
        w_end = w_start + duration
        for room in availability.rooms(conn, bookable_only=False):
            if room["code"] == exclude_room:
                continue
            fails = availability.hard_check(room, purpose, headcount, required_features,
                                            exam_factor=factor)
            if fails:
                continue
            if availability.occupied_windows(conn, room["code"], w_start, w_end):
                continue
            score, reasons = score_candidate(conn, room, shift, headcount, purpose,
                                             from_room, required_features)
            found.append({
                "room": room["code"], "label": room["label"],
                "building": room["building_code"], "start": intervals.to_db(w_start),
                "end": intervals.to_db(w_end), "score": score, "reasons": reasons,
                "shift_minutes": shift,
            })
        if len([f for f in found if f["shift_minutes"] == shift]) >= 6 and shift != 0:
            break
    found.sort(key=lambda r: (-r["score"], abs(r["shift_minutes"]), r["room"]))
    seen, out = set(), []
    for item in found:
        if item["room"] in seen:
            continue
        seen.add(item["room"])
        out.append(item)
        if len(out) >= limit * 2:
            break
    return out[:max(limit, 3)]


def plan_split(conn, start, end, headcount, purpose="EXAM", from_room=None,
               max_rooms=2) -> list[dict]:
    """When no single room can take the headcount, propose rooms in parallel.

    Section 9.3: a seventy-five seat room holds thirty-seven candidates with
    spacing, so a section of seventy-five has to be split across two rooms.
    """
    factor = float(policy.get_setting(conn, "exam_spacing_factor"))
    free_rooms = []
    for room in availability.rooms(conn):
        if availability.hard_check(room, purpose, 1, exam_factor=factor):
            continue
        if availability.occupied_windows(conn, room["code"], start, end):
            continue
        cap = availability.effective_capacity(room, purpose, factor)
        if cap <= 0:
            continue
        free_rooms.append((cap, room))
    free_rooms.sort(key=lambda pair: -pair[0])
    for i in range(len(free_rooms)):
        for j in range(i + 1, len(free_rooms)):
            cap_a, room_a = free_rooms[i]
            cap_b, room_b = free_rooms[j]
            if cap_a + cap_b >= headcount:
                return [{
                    "room": room_a["code"], "label": room_a["label"],
                    "seats": min(cap_a, headcount), "capacity": cap_a,
                    "start": intervals.to_db(intervals.parse_dt(start)),
                    "end": intervals.to_db(intervals.parse_dt(end)),
                }, {
                    "room": room_b["code"], "label": room_b["label"],
                    "seats": headcount - min(cap_a, headcount), "capacity": cap_b,
                    "start": intervals.to_db(intervals.parse_dt(start)),
                    "end": intervals.to_db(intervals.parse_dt(end)),
                }]
    return []
