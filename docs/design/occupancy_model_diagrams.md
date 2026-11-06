# Occupancy model — corrected design in diagrams

Mermaid sources for the room-allocation model. Paste any block into <https://mermaid.live>, GitHub, Obsidian or VS Code (Markdown Preview Mermaid Support) to render.

---

## 1 · Why a "free / occupied" toggle fails, and what replaces it

A room is not a switch. It is a **timeline of reservations**. Availability is *derived* at query time, never stored.

```mermaid
gantt
    title IET first floor + Deeksha — Wed 09:00–12:40  (derived from bookings, never stored)
    dateFormat HH:mm
    axisFormat %H:%M
    todayMarker off

    section IET20
    CSE-2A DBMS (confirmed)        :done,  a1, 09:00, 55m
    CANCELLED - freed by release   :crit,  a2, 09:55, 55m
    CSE-3A practical (confirmed)   :done,  a3, 10:50, 55m
    free                           :a4, 11:45, 55m

    section IET19
    AIML-2B Maths (confirmed)      :done,  b1, 09:00, 55m
    free                           :b2, 09:55, 165m

    section LH08
    free all morning               :c1, 09:00, 220m
```

Read the `crit` block: the class was **cancelled**, the booking row still exists with `status = CANCELLED`, and only the remainder returned to the pool. Nothing was deleted, so the audit trail survives — and the freed interval is free *because the exclusion constraint only covers `CONFIRMED` / `PENDING`*.

```mermaid
flowchart TD
    Q["Is IET20 free for<br/>tomorrow 10:00-10:55?"] --> D{"derived query"}

    D --> R1["any CONFIRMED booking<br/>overlapping the window?"]
    D --> R2["any TimetableSlot<br/>overlapping the window?"]
    D --> R3["any RoomClosure<br/>overlapping the window?"]

    R1 --> U["UNION of occupied intervals"]
    R2 --> U
    R3 --> U

    U --> A{"window INTERSECTS<br/>occupied?"}
    A -->|yes| NO["NOT AVAILABLE<br/>return 3 ranked alternatives"]
    A -->|no| YES["AVAILABLE<br/>capacity, features,<br/>walk-time all pass"]

    style Q fill:#eef2f8,stroke:#cfd6e0
    style YES fill:#e6f6ef,stroke:#7fbfa4
    style NO fill:#fdeceb,stroke:#d99a95
    style D fill:#eaeefc,stroke:#8f9fe8
```

---

## 2 · The three constraints that make the system correct

One booking can violate three different kinds of "double booking". A room-only check catches the first and silently permits the other two.

```mermaid
erDiagram
    BUILDING ||--o{ FLOOR : contains
    FLOOR ||--o{ ROOM : contains
    ROOM ||--o{ BOOKING : "reserved by"
    ROOM ||--o{ ROOM_CLOSURE : "unavailable in"
    SECTION ||--o{ BOOKING : attends
    USER ||--o{ BOOKING : requests
    COURSE ||--o{ TIMETABLE_SLOT : scheduled_as
    SECTION ||--o{ TIMETABLE_SLOT : follows
    ROOM ||--o{ TIMETABLE_SLOT : hosts
    BOOKING ||--o{ BOOKING_EVENT : history
    BOOKING ||--o{ ANNOUNCEMENT : "superseded by"
    BOOKING ||--o{ REPORT : "commented on"

    ROOM {
        text code PK "IET20, IET32, LH08"
        int  capacity "normal seating"
        int  exam_capacity "spaced seating"
        bool bookable "false for offices"
        text accessibility "step_free | stairs_only"
        text_array features
    }
    BOOKING {
        tstzrange time_range "half-open [start,end)"
        text purpose "CLASS|EXAM|PRACTICAL|EVENT"
        int  headcount
        text status "CONFIRMED|PENDING|CANCELLED"
        text reason "mandatory on cancel"
        bool is_test
    }
    SECTION {
        text code PK "CSE-3A"
        int  strength "max 75"
    }
```

```mermaid
stateDiagram-v2
    [*] --> CONFIRMED : faculty reserves<br/>(room free, capacity OK)
    [*] --> PENDING : Seminar Hall / Library /<br/>event above 100

    PENDING --> CONFIRMED : admin approves
    PENDING --> REJECTED : admin rejects
    PENDING --> CANCELLED : requester withdraws

    CONFIRMED --> COMPLETED : end time passes
    CONFIRMED --> CANCELLED : cancel + reason<br/>+ auto-notice
    CONFIRMED --> CONFIRMED : reschedule (move)<br/>new interval checked again

    CANCELLED --> [*]
    REJECTED --> [*]
    COMPLETED --> [*]

    note right of CANCELLED
        Row is never deleted.
        Interval returns to the pool
        because the exclusion
        constraint ignores CANCELLED.
    end note

    note right of PENDING
        PENDING occupies the slot
        so nobody else can take it
        while approval is pending.
    end note
```

The DB-level rules:

```sql
-- 1. no room is double-booked
EXCLUDE USING gist (room_id WITH =, time_range WITH &&)
  WHERE (status IN ('CONFIRMED','PENDING'));

-- 2. no SECTION is in two rooms at once   <-- the one teams forget
EXCLUDE USING gist (section_id WITH =, time_range WITH &&)
  WHERE (status IN ('CONFIRMED','PENDING'));

-- 3. no FACULTY is in two rooms at once
EXCLUDE USING gist (requested_by WITH =, time_range WITH &&)
  WHERE (status IN ('CONFIRMED','PENDING'));
```

---

## 3 · The three operations, and nothing else

Suggestion is a **read**. Only reservation is a **write**. That separation is why a stale suggestion can never corrupt the schedule.

```mermaid
flowchart TD
    A["Faculty enters<br/>headcount, subject, year,<br/>branch, section, time"] --> B

    B["SUGGEST (read-only)<br/>filter: bookable, capacity >= headcount,<br/>purpose permitted, features,<br/>accessibility, no overlap"] --> C

    C{"candidates<br/>found?"}
    C -->|no| C1["show nearest free windows<br/>(+-30 min) or split into 2 rooms"]
    C -->|yes| D["ranked list<br/>capacityFit, sameBuilding, sameFloor,<br/>features, disruption, fairness"]

    D --> E["RESERVE (single transaction)<br/>INSERT booking<br/>+ BookingEvent + AuditEvent + notice outbox"]

    E --> F{"SQLSTATE 23P01<br/>(constraint hit)"}
    F -->|yes| F1["409 + 3 alternatives,<br/>re-validated against the DB"]
    F1 --> D
    F -->|no| G["CONFIRMED<br/>appears on section schedule"]

    G --> H["RELEASE / CANCEL<br/>status = CANCELLED + reason<br/>+ auto-notice to affected sections"]
    H --> I["interval instantly reusable<br/>history preserved"]

    style B fill:#eaeefc,stroke:#8f9fe8
    style E fill:#2f4bd6,stroke:#243a9e,color:#fff
    style G fill:#e6f6ef,stroke:#7fbfa4
    style F1 fill:#fdeceb,stroke:#d99a95
    style H fill:#fdf4e3,stroke:#d8b273
```

---

## 4 · Why the race condition is not a code problem

Two faculty, same room, same slot, same second. Application-level checks let both through. The database does not.

```mermaid
sequenceDiagram
    autonumber
    participant FA as Faculty A
    participant FB as Faculty B
    participant API as API (Next.js)
    participant DB as PostgreSQL

    FA->>API: POST /bookings IET19 10:00-10:55
    FB->>API: POST /bookings IET19 10:00-10:55

    par concurrent
        API->>DB: SELECT overlapping bookings
        and
        API->>DB: SELECT overlapping bookings
    end

    DB-->>API: none found (both requests)
    Note over API: ❌ a check-then-write race:<br/>both "checks" pass

    API->>DB: INSERT booking (A)
    DB-->>API: OK, committed

    API->>DB: INSERT booking (B)
    DB-->>API: SQLSTATE 23P01<br/>EXCLUDE constraint violated

    API-->>FB: 409 + 3 ranked alternatives
    Note over FA,DB: Exactly one booking exists.<br/>This is enforced by storage,<br/>not by our code.
```

---

## 5 · Attendance is NOT an allocation signal

The single most important separation in the model.

```mermaid
flowchart LR
    subgraph ALLOC["ALLOCATION (reservations)"]
        B["Booking<br/>room + interval + status"]
    end

    subgraph ACAD["ACADEMIC RECORD (facts)"]
        AT["Attendance<br/>present / absent / cancelled"]
    end

    B -.->|"never derived from"| AT
    AT -.->|"never mutates"| B

    AT --> R1["reports, eligibility,<br/>analytics, disputes"]
    B --> R2["availability,<br/>conflicts, alternatives"]

    B --> X["❌ NOT ALLOWED:<br/>'mark 0 present' makes a room free"]
    AT --> X

    style X fill:#fdeceb,stroke:#d99a95
    style B fill:#e6f6ef,stroke:#7fbfa4
    style AT fill:#eaeefc,stroke:#8f9fe8
```

Why the red path is banned:

- **A class that started at 10:00 is still running at 10:20.** Releasing it mid-period hands a room to another class while 60 students and their bags are still in it. Zero practical value.
- **"0 present" and "cancelled" are different facts.** Conflating them destroys the distinction that caused the original NSS incident.
- **It creates a perverse incentive:** mark students absent → get a better room slot.
- **Real reuse is planned, not accidental.** "Tomorrow's P3 is cancelled" → notice → slot re-bookable. That is where the benefit actually lives.

---

## 6 · What a good cancellation payload looks like

```mermaid
flowchart TD
    A["Faculty clicks Cancel"] --> B{"owner of this booking?<br/>starts in >= 30 min?"}
    B -->|no| B1["403 / 422<br/>policy refusal"]
    B -->|yes| C["require reason (free text)"]

    C --> D["BEGIN"]
    D --> E["UPDATE booking<br/>status = CANCELLED, reason"]
    E --> F["INSERT BookingEvent<br/>(actor, reason, before/after)"]
    F --> G["INSERT AuditEvent<br/>(append-only, request-id)"]
    G --> H["INSERT Announcement (draft)<br/>scope = affected sections"]
    H --> I["INSERT Notification (outbox row)"]
    I --> J["COMMIT"]

    J --> K["Cron: deliver in-app feed +<br/>email / webhook for CRITICAL"]
    J --> L["Interval immediately reusable<br/>no other transaction needed"]

    style B1 fill:#fdeceb,stroke:#d99a95
    style E fill:#fdf4e3,stroke:#d8b273
    style J fill:#2f4bd6,stroke:#243a9e,color:#fff
    style L fill:#e6f6ef,stroke:#7fbfa4
```

Everything that matters happens in **one transaction**: the status change, the history, the audit, and the notice. A cancellation therefore cannot be silent — which is the failure the original problem statement was written about.

---

## Summary

| Concept | Wrong | Right |
|---|---|---|
| Room state | `status: FREE / OCCUPIED` | intervals in `Booking`, availability derived |
| Freeing a room | delete / clear the record | `status = CANCELLED` + reason, row kept |
| Trigger for freeing | "0 present" attendance | explicit release or cancellation |
| Conflict check | `if (room.isFree)` in app code | `EXCLUDE USING gist` in PostgreSQL |
| What is checked | room only | room **+ section + faculty** |
| Capacity | one number | `capacity` + `exam_capacity` (spaced seating) |
| Suggestion | the answer | a read-only hint; the DB decides at insert |
| Attendance | allocation signal | separate academic record, never mutates allocation |
