# Architecture

## The one idea

A room is a **timeline**, not a switch. Availability is derived from three occupancy sources
united first — live reservations, the official timetable, and closures — and correctness is
enforced by the storage engine with three exclusion constraints, not by application code that
could be bypassed.

```
    UI (Streamlit)                 domain (core/)                 storage (SQLite)
    ─────────────────              ────────────────               ─────────────────
    screens per role  ──────►  policy.can(actor, action, row)  ──►  booking
    shared components          availability.search()               room_closure
    result renderer     ◄────  booking.create/approve/cancel  ◄──  timetable_slot
                               scoring.alternatives()              triggers:
                               audit.replay_room()                    room_no_overlap
                               records.*                              section_no_overlap
                               assistant.ask()  (read only)           faculty_no_overlap
```

## Why each module exists

| Module | Responsibility | The defect it prevents |
|---|---|---|
| `core/intervals.py` | Half-open interval algebra, snapping, subtraction | Back-to-back classes colliding; a "free" flag that drifts |
| `core/policy.py` | One `can()` function; the permission matrix; settings with history | A new route quietly widening a role |
| `core/availability.py` | Union of the three occupancy sources; hard checks; free windows | A room offered while the timetable holds it |
| `core/booking.py` | Create, approve, reject, reschedule, release, displace; outbox in the same transaction | Two activities in one room; a mail failure losing a booking |
| `core/scoring.py` | Ranked alternatives and split sittings | A refusal that leaves the person with nowhere to go |
| `core/records.py` | Closures, notices, reports, room correction | A closure silently breaking three bookings |
| `core/audit.py` | Trail, field diff, replay from events | A disagreement settled from memory |
| `core/assistant.py` | Intent parsing, grounded search, the guardrail | A confidently wrong room code |
| `core/analytics.py` | The scarcity arithmetic, computed live | A number in a document nobody can re-check |

## Data model

Seventeen entities, as section 6.2 of the design enumerates them: `building`, `floor`, `room`,
`room_closure`, `section`, `student`, `faculty`, `course`, `timetable_slot`, `booking_series`,
`booking`, `booking_event`, `audit_event`, `announcement`, `report`, `report_entry`,
`notification`, plus `attendance` held deliberately apart from allocation, and `setting` /
`setting_history` for the six policy values.

## The three constraints

```sql
-- Constraint 1: no room carries two live reservations for the same interval.
CREATE TRIGGER booking_room_no_overlap_ins BEFORE INSERT ON booking
WHEN NEW.status IN ('CONFIRMED','PENDING_APPROVAL') BEGIN
  SELECT RAISE(ABORT,'EXCLUSION:ROOM_ALREADY_BOOKED')
  WHERE EXISTS (SELECT 1 FROM booking b
                WHERE b.room_code = NEW.room_code
                  AND b.status IN ('CONFIRMED','PENDING_APPROVAL')
                  AND NEW.start_at < b.end_at AND b.start_at < NEW.end_at);
END;
```

The section and faculty constraints are the same shape on `section_code` and `faculty_id`. The
application checks first so that a refusal can carry alternatives and a readable reason; the
trigger is the arbiter when the checks race. The concurrency drill proves the second statement.

## A request, end to end

1. The screen calls `booking.create(...)` with an idempotency key.
2. `policy.can(actor, "booking:create")` decides authority — a refusal names the reason.
3. Headcount, purpose, window, section and room are validated; each failure has its own code.
4. Gates are applied: seminar hall, library, large events and unconfirmed rooms become
   `PENDING_APPROVAL` for faculty.
5. Occupancy is checked in the order that produces the most useful refusal: room, timetable,
   section, faculty. Each conflict returns three ranked alternatives.
6. The insert runs. If a trigger still fires — because another transaction got there first — the
   caller receives `409` with alternatives, not a stack trace.
7. Booking event, audit row and notification rows are written in the same transaction.
8. Notifications are drained later by a job; a failure there changes nothing about the booking.
