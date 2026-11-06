-- Smart Campus: seventeen entities, plus the two settings tables that
-- section 12.3 asks for. SQLite stands in for PostgreSQL; the three exclusion
-- constraints of section 4.3 are reproduced as BEFORE INSERT/UPDATE triggers,
-- so the storage engine, not the application, is the arbiter.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS building (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    distance_to_iet_m   INTEGER NOT NULL DEFAULT 0,
    has_lift            INTEGER NOT NULL DEFAULT 0,
    entry_gate          TEXT
);

CREATE TABLE IF NOT EXISTS floor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    building_code   TEXT NOT NULL REFERENCES building(code),
    level           INTEGER NOT NULL,
    label           TEXT NOT NULL,
    UNIQUE (building_code, level)
);

CREATE TABLE IF NOT EXISTS room (
    code            TEXT PRIMARY KEY,
    floor_id        INTEGER NOT NULL REFERENCES floor(id),
    room_type       TEXT NOT NULL,
    label           TEXT NOT NULL,
    capacity        INTEGER NOT NULL DEFAULT 0,
    exam_capacity   INTEGER NOT NULL DEFAULT 0,
    bookable        INTEGER NOT NULL DEFAULT 0,
    accessibility   TEXT,
    zone            TEXT,
    permitted_uses  TEXT NOT NULL DEFAULT '[]',
    features        TEXT NOT NULL DEFAULT '[]',
    unconfirmed     INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS room_closure (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code   TEXT NOT NULL REFERENCES room(code),
    start_at    TEXT NOT NULL,
    end_at      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS section (
    code        TEXT PRIMARY KEY,
    branch      TEXT NOT NULL,
    year        INTEGER NOT NULL,
    strength    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS student (
    roll_number TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    section_code TEXT NOT NULL REFERENCES section(code)
);

CREATE TABLE IF NOT EXISTS faculty (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    department  TEXT NOT NULL,
    home_building TEXT NOT NULL DEFAULT 'IET'
);

CREATE TABLE IF NOT EXISTS course (
    code            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    branch          TEXT NOT NULL,
    year            INTEGER NOT NULL,
    required_features TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS timetable_slot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL REFERENCES course(code),
    section_code TEXT NOT NULL REFERENCES section(code),
    room_code   TEXT NOT NULL REFERENCES room(code),
    weekday     TEXT NOT NULL,
    period      TEXT NOT NULL,
    valid_from  TEXT NOT NULL,
    valid_to    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS booking_series (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recurrence_rule TEXT NOT NULL,
    parent_booking_id INTEGER,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS booking (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code       TEXT NOT NULL REFERENCES room(code),
    section_code    TEXT REFERENCES section(code),
    faculty_id      TEXT REFERENCES faculty(id),
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    purpose         TEXT NOT NULL,
    headcount       INTEGER NOT NULL,
    status          TEXT NOT NULL,
    reason          TEXT,
    is_test         INTEGER NOT NULL DEFAULT 0,
    version         INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT UNIQUE,
    series_id       INTEGER REFERENCES booking_series(id),
    title           TEXT,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CHECK (start_at < end_at)
);

CREATE INDEX IF NOT EXISTS booking_room_start_idx ON booking (room_code, start_at DESC);
CREATE INDEX IF NOT EXISTS booking_section_idx ON booking (section_code, start_at DESC);
CREATE INDEX IF NOT EXISTS booking_faculty_idx ON booking (faculty_id, start_at DESC);
-- partial index: only live rows matter for availability (listing 5)
CREATE INDEX IF NOT EXISTS booking_live_idx ON booking (status)
    WHERE status IN ('CONFIRMED', 'PENDING_APPROVAL');

CREATE TABLE IF NOT EXISTS booking_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER NOT NULL REFERENCES booking(id),
    event_type  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    at          TEXT NOT NULL,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS audit_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT,
    before_state TEXT,
    after_state TEXT,
    request_id  TEXT,
    at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS announcement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL,           -- CAMPUS | BUILDING | SECTION | ROOM
    scope_id    TEXT,
    severity    TEXT NOT NULL DEFAULT 'INFO',
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    publish_at  TEXT NOT NULL,
    expires_at  TEXT,
    supersedes_booking_id INTEGER,
    version     INTEGER NOT NULL DEFAULT 1,
    created_by  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER REFERENCES booking(id),
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | RESOLVED
    reporter    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    resolution  TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    report_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS report_entry (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   INTEGER NOT NULL REFERENCES report(id),
    author      TEXT NOT NULL,
    body        TEXT NOT NULL,
    at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'EMAIL',
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'QUEUED',  -- QUEUED | SENT | FAILED
    attempts    INTEGER NOT NULL DEFAULT 0,
    sent_at     TEXT,
    created_at  TEXT NOT NULL
);

-- Deliberately separate from allocation. Section 4.5: attendance may describe
-- what happened in a room, it may never determine who may use one.
CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_roll TEXT NOT NULL REFERENCES student(roll_number),
    course_code TEXT NOT NULL REFERENCES course(code),
    date        TEXT NOT NULL,
    state       TEXT NOT NULL,
    UNIQUE (student_roll, course_code, date)
);

CREATE TABLE IF NOT EXISTS setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setting_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    at          TEXT NOT NULL
);

-- ---------------------------------------------------------------- constraints
-- Constraint 1: no room carries two live reservations for the same interval.
CREATE TRIGGER IF NOT EXISTS booking_room_no_overlap_ins
BEFORE INSERT ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL')
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:ROOM_ALREADY_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.room_code = NEW.room_code
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;

-- Constraint 2: no section is expected in two rooms at the same time.
CREATE TRIGGER IF NOT EXISTS booking_section_no_overlap_ins
BEFORE INSERT ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL') AND NEW.section_code IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:SECTION_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.section_code = NEW.section_code
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;

-- Constraint 3: no member of faculty is in two rooms at the same time.
CREATE TRIGGER IF NOT EXISTS booking_faculty_no_overlap_ins
BEFORE INSERT ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL') AND NEW.faculty_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:FACULTY_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.faculty_id = NEW.faculty_id
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;

CREATE TRIGGER IF NOT EXISTS booking_room_no_overlap_upd
BEFORE UPDATE OF room_code, start_at, end_at, status ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL')
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:ROOM_ALREADY_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.id <> NEW.id
          AND b.room_code = NEW.room_code
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;

CREATE TRIGGER IF NOT EXISTS booking_section_no_overlap_upd
BEFORE UPDATE OF section_code, start_at, end_at, status ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL') AND NEW.section_code IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:SECTION_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.id <> NEW.id
          AND b.section_code = NEW.section_code
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;

CREATE TRIGGER IF NOT EXISTS booking_faculty_no_overlap_upd
BEFORE UPDATE OF faculty_id, start_at, end_at, status ON booking
WHEN NEW.status IN ('CONFIRMED', 'PENDING_APPROVAL') AND NEW.faculty_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'EXCLUSION:FACULTY_DOUBLE_BOOKED')
    WHERE EXISTS (
        SELECT 1 FROM booking b
        WHERE b.id <> NEW.id
          AND b.faculty_id = NEW.faculty_id
          AND b.status IN ('CONFIRMED', 'PENDING_APPROVAL')
          AND NEW.start_at < b.end_at
          AND b.start_at < NEW.end_at
    );
END;
