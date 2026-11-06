import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, policy, seed  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    """A fresh campus per test: seeded from the registry, thrown away after."""
    path = tmp_path / "campus.db"
    c = db.ensure_db(path)
    yield c
    c.close()


@pytest.fixture()
def admin():
    return policy.Actor("ADM-01", "admin", "Registrar")


@pytest.fixture()
def faculty():
    return policy.Actor("a.verma@iet.example.edu", "faculty", "Dr A. Verma",
                        faculty_id="FAC-01")


@pytest.fixture()
def other_faculty():
    return policy.Actor("s.mishra@iet.example.edu", "faculty", "Dr S. Mishra",
                        faculty_id="FAC-02")


@pytest.fixture()
def student():
    return policy.Actor("CSE-3A-01", "student", "Student CSE-3A", section="CSE-3A")


@pytest.fixture()
def day():
    """A teaching day a week out, so lead time and horizon never interfere."""
    return seed.next_teaching_day(date.today(), 5)
