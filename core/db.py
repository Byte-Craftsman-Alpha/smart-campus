"""Connection handling. One writer at a time, which is what makes the
exclusion constraints behave the way PostgreSQL's do under load."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(path=None) -> sqlite3.Connection:
    path = str(path or config.DB_PATH)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = True):
    """BEGIN IMMEDIATE serialises writers, so two concurrent inserts cannot both
    pass the application-level checks and then both write."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def ensure_db(path=None, seed: bool = True):
    """Create the schema and, if the register is empty, seed the campus."""
    conn = connect(path)
    init_schema(conn)
    if seed:
        from . import seed as seed_mod
        if conn.execute("SELECT COUNT(*) c FROM room").fetchone()["c"] == 0:
            seed_mod.seed_all(conn)
    return conn


def reset_db(path=None):
    """Drop the file and rebuild. Used by tests and by the demo reset button."""
    p = Path(path or config.DB_PATH)
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            f.unlink()
    return ensure_db(path)
