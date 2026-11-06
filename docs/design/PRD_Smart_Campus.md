# PRD — Smart Campus Classroom Management System

**Event:** Build With AI: DevOps 2026 · GDG on Campus, DDUGU · **Owner:** IET · **Version:** 1.0

## 1. Problem
IET has no single system for classroom allocation. Faculty hunt for free rooms for extra lectures, minors, practicals and events; changes travel by word of mouth. Result: overlapping allocations and, last year, students missing a minor exam (NSS) due to wrong/absent information. We need one authoritative platform for room discovery, booking and academic communication across **IET and Deeksha Bhawan**.

## 2. Goals & success metrics
- **G1** Zero double-bookings — enforced at the database, not by UI checks.
- **G2** Faculty find a usable room + alternative in **< 60 s**.
- **G3** No academic change goes unpublished — every cancel/reschedule emits a scoped notice.
- **G4** Students never act on stale information.
- Metrics: 0 overlapping confirmed bookings in a 200-VU concurrency test; p95 availability query < 80 ms, booking < 150 ms; 100% of seeded changes produce a notice; student PATCH on a booking returns 403.

## 3. Users & roles
| Role | Needs | Cannot |
|---|---|---|
| Faculty | Search, book, reschedule, cancel, publish section notices | Publish campus-wide, cancel others' bookings |
| Student | View section schedule + notices, comment, report | Book, modify, publish |
| Administrator | Approve, override, edit room data, resolve reports, read audit | — |

## 4. Scope
**In:** room registry from the blueprint; availability search; booking; conflict prevention + ranked alternatives; notices; student read/report; RBAC; audit trail; AI natural-language search; timetable allocation.
**Out:** fee/attendance/exam-result systems, native apps, SSO, payments, live sensor occupancy, editing the university's real timetable.

## 5. Domain data (fixed facts)
- **IET** (3 floors, 1 central stair, no lift, 1 entry): GF — Library (150–180, dual-use exam venue), Teachers' Office, Placement Cell, Director's Office; FF — IET22/16/14/15 (labs, CSE/ME/ECE/IT) + IET20/19/18/17 (classrooms, ~75); SF — Seminar Hall IET32 (200) + IET24/25/28/29/30/23 (~75).
- **Deeksha Bhawan** (2 floors, 1 stair, 100 m from IET): LH01–LH14. Only LH01/02/08/09 seat a full 75-section.
- **34 rooms total, 30 bookable.** Branches: CSE 150 (A,B), AI-ML 150 (A,B), AI-DS 75, ECE 75, ME 75, IT 75 → 600/year, **2,400 students, 32 sections**, largest unit 75.
- **Capacity reality:** 32 sections × 7 periods/day ≈ 93% of all room-periods; peak slots 3.5× oversubscribed; a spaced 75-student exam fits only IET32 or the Library — so split-room exams must be supported.
- **Source conflicts** (resolved): labs drawn as plain rooms → modelled LAB, flag `unconfirmed`; IET23 and LH13/14 appear on the plan but not in the text → keep, flag; Deeksha capacities absent → inferred from plan area, configurable; Library bookable for exams only by approval.
- **Policy as data:** 8×55-min periods 09:00–17:10, lunch 12:40–13:30; exam seat factor 0.5; cross-building min gap 10 min; horizon 60 days; lead time 15 min.

## 6. Entity model
`Building`→`Floor`→`Room` (code, type, capacity, exam_capacity, bookable, accessibility, zone, permitted_uses[], unconfirmed) · `RoomClosure` · `Section` (code, branch, year, strength) · `User` (role, section?) · `Course` · `TimetableSlot` · `Booking` (tstzrange, purpose, headcount, status, is_test, idempotency_key, version) · `BookingSeries` · `BookingEvent` · `AuditEvent` (append-only) · `Announcement` · `Report` · `Notification` (outbox) · `Settings`.

## 7. User journeys
**J1 Faculty books:** login → search "tomorrow 10:00, 72 students, IET" → ranked free rooms → book → confirmation + calendar entry.
**J2 Clash:** second faculty requests same room → `409` + 3 scored alternatives with reasons → books one → both schedules consistent.
**J3 Cancel:** faculty cancels with reason → affected sections get a CRITICAL notice → slot returns to availability.
**J4 Student report:** student sees notice → reports "this exam is in the wrong room" → admin triage (12 similar reports merged to one) → resolved → reporter notified.
**J5 AI:** "lab with 70 seats tomorrow after lunch" → tool call → grounded result with a book button.

## 8. Functional requirements
**FR-1 Availability (G1):** filter by building, floor, room, date, start, duration, capacity, purpose, accessibility. Considers bookings + official timetable + closures. *AC:* a fully booked floor returns 0 rooms; widening building returns Deeksha rooms with distance.

**FR-2 Booking (G2):** create for CLASS/EXAM/PRACTICAL/EVENT/SEMINAR/VIVA with headcount, section, purpose. State machine DRAFT→PENDING_APPROVAL→CONFIRMED→COMPLETED/CANCELLED/REJECTED; no hard delete. *AC:* four purposes persist correctly; approval-gated purposes land PENDING.

**FR-3 Conflict prevention (G1):** PostgreSQL `EXCLUDE USING gist (room_id, tstzrange)` on CONFIRMED/PENDING. *AC:* 20 parallel identical requests → exactly 1 success, 19× `409`.

**FR-4 Alternatives:** every conflict returns ≥3 scored, DB-validated options (±30 min window shift allowed) with 2 reasons each. Scoring: capacityFit .22, sameBuilding .20, sameFloor .12, purposeFit .12, featureMatch .10, disruption .08, timeShift .08, accessibility .05, fairness .03. *AC:* property test over 500 random booking sets yields no occupied room.

**FR-5 Notices:** scoped CAMPUS/BUILDING/SECTION/ROOM/BOOKING, severity INFO/IMPORTANT/CRITICAL, publish+expiry, versioned edits, optional `supersedes_booking`. Cancel/reschedule auto-drafts a notice. Delivery: in-app feed → daily email digest → email/webhook on CRITICAL. *AC:* cancel → affected section schedule + feed update; CRITICAL pins to top.

**FR-6 Student access:** read-only schedules; comment thread (rate-limited); structured reports (wrong room / cancelled-but-listed / clash / outdated / other) with status lifecycle, duplicate aggregation and resolution notification. *AC:* student token PATCH booking → 403.

**FR-7 RBAC:** one server-side `can(actor, action, resource)`; full role×action matrix test. *AC:* every negative cell asserted.

**FR-8 Accountability:** `BookingEvent` (human biography) + append-only `AuditEvent` (before/after, actor, request-id). Mandatory reason on cancel/reschedule. *AC:* replay reconstructs any room's past state; no API mutates audit rows.

**FR-9 AI:** LLM with read-only tools only; translates utterance → zod-validated `search_rooms` intent; explains engine output. Never computes availability, never writes, never displays unverified facts. 8 s timeout; form fallback if provider/key absent. *AC:* AI output contains no room code absent from the query result set.

**FR-10 Allocation:** greedy (most-constrained-first) + local-search repair; report moves and before/after cost. *AC:* one command re-allocates a day and lists every move with reason.

**FR-11 Test data:** `is_test` + `seed_source`; visible TEST chip; one command resets seeded records.

**FR-12 Admin:** confirm room data, approvals queue, reports triage, settings, audit search.

## 9. Non-functional
Mobile-first student views; WCAG-AA contrast + keyboard nav; Asia/Kolkata time everywhere (`timestamptz`); app boots with only `DATABASE_URL`; CI gates lint, typecheck, unit, integration, E2E, build; preview deploy per PR; `/api/health`; structured logs with request-id; idempotent booking POST.

## 10. Dependencies & assumptions
PostgreSQL 16 with `btree_gist`; supplied student/branch datasets (columns unverified); blueprint as the room source of truth; venue internet; one maintainer with DB access. Assumes no lift in either building and no cross-building covered link.

## 11. Milestones
D1 schema + EXCLUDE constraint + registry seed · D2 student ingest + auth/RBAC · D3 availability + search UI · D4 booking + alternatives · D5 notices + student surfaces · D6 AI layer · D7 allocation + admin · D8 hardening/load test · D9 CI + docs · D10 rehearsal + backup video.

## 12. Risks
Dataset columns unknown → 6-stage ingest with alias maps + dry-run, synthetic-student fallback. Blueprint ambiguity challenged → reconciliation ledger + `unconfirmed` flags. ORM vs constraint → hand-written SQL migration, serialisable-transaction fallback. LLM outage → adapter + deterministic fallback. Integration collapse → API contract frozen D1, features frozen D8, continuous deploy. Data loss → `pg_dump` before demo.

## 13. Open questions
Exact Deeksha capacities; whether FF north rooms are labs or classrooms; whether LH13/14 are in use; the real period grid; who owns Seminar Hall approval.

## 14. Primary screens
Student: today/week schedule · notices feed · report + comment. Faculty: availability search (filters + results with capacity & walk time) · booking confirm · booking detail with history. Shared: room timeline / floor-plan picker. Admin: approvals queue · reports triage · room-data confirmation · audit search · settings. Plus an AI chat panel available to faculty and admin.

## 15. Definition of done
Deployed URL live; CI green on `main` (lint, typecheck, unit, integration, E2E, build); double-booking impossibility proven by the concurrency test, not asserted; every one of the 8 statement requirements demoable in a 7-minute rehearsed walkthrough; all seeded records visibly flagged TEST with a one-command reset; README reaches a running app from a fresh clone in under 5 minutes; the five source ambiguities documented and visible in the UI.
