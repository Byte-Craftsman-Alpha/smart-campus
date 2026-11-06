# Setup

## Requirements

- Python 3.11 or newer (the work was done on 3.13)
- No database server: SQLite ships with Python

## Install and run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The application opens on `http://localhost:8501`. On first run it creates `smart_campus.db` and
seeds it from `data/campus_room_registry.json`: 34 rooms, 32 sections, 96 student records, 8
faculty, 24 courses, a weekly timetable, a handful of demonstration bookings and one closure.

## Demonstration accounts

Printed on the sign-in page, as the definition of done asks.

| Role | Login | Password |
|---|---|---|
| Faculty | `a.verma@iet.example.edu` | `faculty123` |
| Student | `CSE-3A-01` | `student123` |
| Administrator | `registrar` | `admin123` |

Any of the eight faculty emails works with the faculty password; any student roll number of the
form `CSE-3A-01` works with the student password.

## Reset

**Reset demonstration data** in the administrator's sidebar drops the database and re-seeds it.
The browser suite does the same thing before every run.

## Tests

```bash
python3 -m pytest tests -q                 # 150 domain cases, about four seconds
python3 tests/e2e/run_browser_suite.py     # 38 browser scenarios, about eleven minutes
```

The browser suite needs Chromium once:

```bash
python3 -m playwright install --with-deps chromium
```

It starts its own Streamlit instance on port 8511 with a fresh database, so it can be run while
your own instance is still open. Screenshots land in `docs/testing/screenshots/`.

## Rebuilding the testing report

```bash
python3 -m pytest tests -q --tb=no > qa/results/pytest_output.txt
python3 tests/e2e/run_browser_suite.py
python3 qa/build_report.py        # docs/testing/TESTING_REPORT.docx
python3 qa/build_markdown.py      # docs/testing/TESTING_REPORT.md
```

Both report files are generated from the recorded results, so they cannot drift away from the
evidence.
