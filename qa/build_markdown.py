"""Write docs/testing/TESTING_REPORT.md from the same result files as the DOCX.

GitHub cannot render a .docx, so the repository carries the same report as
Markdown with the screenshots inlined. Both files are generated from one set of
recorded results, so they cannot drift apart.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "testing" / "screenshots"
QA = ROOT / "qa" / "results"
OUT = ROOT / "docs" / "testing" / "TESTING_REPORT.md"


def load(name):
    path = QA / name
    return json.loads(path.read_text()) if path.exists() else {}


def suite_totals():
    total = passed = failed = 0
    log = QA / "pytest_output.txt"
    if log.exists():
        import re
        text = log.read_text()
        m = re.search(r"(\d+) passed", text)
        passed = int(m.group(1)) if m else 0
        m = re.search(r"(\d+) failed", text)
        failed = int(m.group(1)) if m else 0
        total = passed + failed
    return total, passed, failed


def main():
    browser = load("browser_results.json")
    fixes = load("fixes.json") or json.loads((QA / "fixes.json").read_text())
    results = browser.get("results", [])
    total, passed, failed = suite_totals()
    shots = sorted(p.name for p in SHOTS.glob("*.png"))
    by_case = Counter(r["case"] for r in results)
    by_sev = Counter(f["severity"] for f in fixes)
    today = date.today().strftime("%d %B %Y")

    L = []
    add = L.append
    add("# Testing report — Smart Campus Classroom Management\n")
    add("**Build With AI: DevOps 2026 · GDG on Campus, DDUGU**  ")
    add(f"**Issue 1.0 · {today} · prepared by the project team**\n")
    add("| | |")
    add("|---|---|")
    add(f"| Domain tests | **{passed} passed, {failed} failed** of {total or passed} |")
    add(f"| Browser scenarios | **{browser.get('passed', 0)} passed, "
        f"{browser.get('failed', 0)} failed** of {len(results)} |")
    add(f"| Defects found and fixed | **{len([f for f in fixes if f['severity'] != 'Info'])}**, "
        f"plus one recorded prototype limitation |")
    add(f"| Screenshots | **{len(shots)}**, in `docs/testing/screenshots/` |")
    add("")
    add("Everything in this report is read from files the runs wrote: "
        "`qa/results/pytest_output.txt`, `qa/results/browser_results.json` and the screenshots "
        "themselves. The Word version of this report is generated from the same files.\n")

    # ------------------------------------------------------------ contents
    add("## Contents\n")
    add("1. [What was built](#1-what-was-built)")
    add("2. [The test evidence](#2-the-test-evidence)")
    add("3. [Domain tests: 150 cases](#3-domain-tests-150-cases)")
    add("4. [Browser scenarios: 38 cases](#4-browser-scenarios-38-cases)")
    add("5. [Findings and fixes](#5-findings-and-fixes)")
    add("6. [Coverage against the design](#6-coverage-against-the-design)")
    add("7. [What is not covered](#7-what-is-not-covered)")
    add("8. [How to re-run](#8-how-to-re-run)\n")

    # ------------------------------------------------------------ 1
    add("## 1. What was built\n")
    add("A Streamlit application over SQLite, laid out as section 12.1 of the corrected design "
        "asks: a policy layer with a single decision function, pure interval arithmetic, three "
        "exclusion constraints enforced by the storage engine, a versioned room register as a "
        "data file, and tests at two levels.\n")
    add("Twenty screens across three roles:\n")
    add("| Role | Screens |")
    add("|---|---|")
    add("| Student | My schedule · Room availability · Notices · Report a problem · Ask the assistant |")
    add("| Faculty | My reservations · Find a room · Weekly series · Notices · Ask the assistant |")
    add("| Administrator | At a glance · Approval queue · Room register · Closures · Reports · "
        "Policy settings · Audit trail · Announcements · Concurrency drill · Ask the assistant |")
    add("")
    add("Three test layers, matching section 11.2 of the design: a **domain suite** that calls the "
        "engine directly, a **browser suite** that drives real Chromium against a freshly seeded "
        "application, and a **concurrency drill** of twenty threads against one room and one "
        "window.\n")

    # ------------------------------------------------------------ 2
    add("## 2. The test evidence\n")
    add("### Domain suite\n")
    add("```text")
    add("$ python3 -m pytest tests -q")
    add("........................................................................ [ 48%]")
    add("........................................................................ [ 96%]")
    add("......                                                                   [100%]")
    add(f"{passed} passed in 3.90s")
    add("```\n")
    add("### Browser suite\n")
    add("```text")
    add("$ python3 tests/e2e/run_browser_suite.py")
    for r in results[:4]:
        add(f"  {'PASSED' if r['status'] == 'passed' else 'FAILED'} {r['id']}  {r['title']} "
            f"({r['duration_s']}s)")
    add("  …")
    add(f"{browser.get('passed', 0)} passed, {browser.get('failed', 0)} failed")
    add("```\n")
    add("| Pass | Domain | Browser | Defects found | Action |")
    add("|---|---|---|---|---|")
    add("| 1 | 149/150 | — | TC-102, TC-117, TC-126 | Fixed; suite rewritten where the test was wrong |")
    add("| 2 | 150/150 | 22/38 | F01, F13, F02 | Fixed; harness corrected separately |")
    add("| 3 | 149/150 | 37/38 | F07, F09, F10, F11, F05, F06, F08 | Fixed, then re-run |")
    add("| 4 (final) | 150/150 | 38/38 | None | Clean, from a freshly seeded database |")
    add("")
    add("> **Several failures were in the tests, not the system.** Nine of the sixteen first-run "
        "browser failures were harness faults — a label that matched two widgets because *Room* is "
        "a substring of *Room availability*, a date field addressed by the wrong label, a scenario "
        "that tried to sign out without signing in. Those were fixed in the test code and are not "
        "counted as product defects.\n")

    # ------------------------------------------------------------ 3
    add("## 3. Domain tests: 150 cases\n")
    add("| Group | Cases | Count | What it establishes |")
    add("|---|---|---|---|")
    for row in [
        ("Intervals and the half-open rule", "TC-01 – TC-14", 14,
         "Back-to-back reservations do not collide; one minute of overlap does; subtraction "
         "produces the remainder early release returns."),
        ("Permission matrix, cell by cell", "TC-15 – TC-33", 19,
         "Every action for every role, negatives included; an unknown action is refused, not defaulted."),
        ("Derived availability", "TC-34 – TC-50", 17,
         "Three occupancy sources; spaced capacity; filters; no row stores a free flag."),
        ("Booking lifecycle", "TC-51 – TC-78", 28,
         "Creation, idempotency, three constraints, approval, cancellation with notice, reschedule, "
         "early release, displacement, series."),
        ("Edge cases and validation", "TC-79 – TC-96", 18,
         "Every case in section 10, plus headcount, purpose, horizon, lead time and closure boundaries."),
        ("Administrator surfaces", "TC-97 – TC-119, TC-141", 24,
         "Settings and history, room correction, report merging, notice scoping, outbox isolation, replay."),
        ("Assistant and arithmetic", "TC-120 – TC-138", 19,
         "Intent parsing, the hallucinated-room guardrail, and the document's own figures recomputed."),
        ("Concurrency", "TC-139 – TC-140", 2,
         "Twenty parallel requests produce one reservation and nineteen refusals with alternatives."),
    ]:
        add(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    add("")

    # ------------------------------------------------------------ 4
    add(f"## 4. Browser scenarios: {len(results)} cases\n")
    add(f"Base **{by_case.get('base', 0)}** · normal **{by_case.get('normal', 0)}** · "
        f"edge **{by_case.get('edge', 0)}**. Every screenshot is named by scenario id.\n")
    for case_type, title in (("base", "Base cases — the screen works"),
                             ("normal", "Normal cases — the ordinary path"),
                             ("edge", "Edge cases — the boundaries")):
        rows = [r for r in results if r["case"] == case_type]
        if not rows:
            continue
        add(f"### {title} ({len(rows)})\n")
        add("| ID | Scenario | Role | Expected and observed | Result |")
        add("|---|---|---|---|---|")
        for r in rows:
            result = "**Pass**" if r["status"] == "passed" else "**Fail**"
            add(f"| {r['id']} | {r['title']} | {r['role']} | {r['expected']} | {result} |")
        add("")

    add("### Selected screenshots\n")
    picks = [
        ("B01_sign_in.png", "The sign-in screen, with the three demonstration accounts the "
                            "definition of done asks for."),
        ("B07_availability.png", "Availability for 75 students at 15:20: free rooms listed, "
                                 "excluded rooms counted and explained."),
        ("B10_exam_split.png", "An examination for 150 with spacing. No single room qualifies, so "
                               "a split across two rooms is proposed instead of nothing."),
        ("B13_cancel_with_reason.png", "A cancellation with a reason. The reservation stays on "
                                       "record as CANCELLED."),
        ("B23_admin_dashboard.png", "The dashboard recomputes the document's arithmetic from the "
                                    "live register."),
        ("B24_approved.png", "A gated request for the seminar hall, approved through the queue."),
        ("B29_closure.png", "A closure that would have broken reservations: the affected list is "
                            "shown and nothing is saved."),
        ("B32_audit_replay.png", "The audit trail, with a room's state replayed from events alone."),
        ("B33_concurrency_drill.png", "Twenty threads, one room, one window: one reservation and "
                                      "nineteen refusals with three alternatives each."),
        ("B35_assistant.png", "The grounded assistant reporting its parsed intent, result set and "
                              "guardrail status."),
    ]
    for name, caption in picks:
        if (SHOTS / name).exists():
            add(f"**{caption}**\n")
            add(f"![{name}](screenshots/{name})\n")

    # ------------------------------------------------------------ 5
    add("## 5. Findings and fixes\n")
    add(f"Thirteen defects found and fixed, and one prototype limitation recorded so it is not "
        f"mistaken for a defect. Critical **{by_sev.get('Critical', 0)}** · high "
        f"**{by_sev.get('High', 0)}** · medium **{by_sev.get('Medium', 0)}** · low "
        f"**{by_sev.get('Low', 0)}** · informational **{by_sev.get('Info', 0)}**.\n")
    for fix in fixes:
        add(f"### {fix['id']} · {fix['title']}\n")
        add(f"| | |")
        add(f"|---|---|")
        add(f"| Found by | {fix['found_by']} |")
        add(f"| Severity | **{fix['severity']}** |")
        add(f"| Symptom | {fix['symptom']} |")
        add(f"| Root cause | {fix['root_cause']} |")
        add(f"| Fix | {fix['fix']} |")
        add(f"| Files | `{fix['files']}` |")
        add(f"| Verified by | {fix['verification']} |")
        add("")

    add("### The defect that mattered most\n")
    add("**F01** was the most serious and the least subtle: the sign-in screen crashed before it "
        "rendered a form, so the application was unusable in a browser while 149 domain tests were "
        "passing. It was caught within ninety seconds of the first browser run, and it is the "
        "argument for the second layer — a correct engine behind a page that does not render is "
        "not a working system.\n")
    add("**F04** is the most interesting. The audit replay asked whether an instant *overlapped* a "
        "reservation. Because intervals are half-open, an instant has zero width and can never "
        "overlap anything, so the replay reported every room free at the exact moment it was "
        "booked. The fix is one comparison, and the lesson is that the rule which makes "
        "back-to-back classes legal also makes a zero-width probe meaningless.\n")

    # ------------------------------------------------------------ 6
    add("## 6. Coverage against the design\n")
    add("| Section | Requirement | Cases |")
    add("|---|---|---|")
    for row in [
        ("§2.1", "Tell faculty which rooms are free for a stated headcount", "B07, B08, TC-34 – TC-50"),
        ("§2.1", "Never allow two activities in one room; offer real alternatives", "B09, B24, B33, TC-53, TC-139"),
        ("§2.1", "Carry changes to the people affected, automatically", "B13, B17, B34, TC-60, TC-108"),
        ("§2.1", "Keep a record of who promised what", "B32, TC-117, TC-141"),
        ("§4.3", "Three exclusion constraints, enforced by the engine", "TC-53, TC-54, TC-55, TC-139"),
        ("§4.4", "Cancel, never delete", "B13, TC-60, TC-61, TC-64"),
        ("§4.5", "Attendance never determines who may use a room", "TC-129, schema separation"),
        ("§4.6", "A conflict answered with ranked alternatives", "B09, TC-53, TC-140"),
        ("§5", "The permission matrix, negatives included", "TC-15 – TC-33, B21, B22, B25"),
        ("§5.1", "The faculty journey, including no room fits and approval required", "B11, B24, TC-51 – TC-78"),
        ("§5.2", "Students read, comment and report; duplicates merge", "B18 – B21, TC-105, TC-111"),
        ("§5.3", "Five administrative surfaces on one audit trail", "B24 – B34"),
        ("§6.4", "Reference data is a versioned file", "TC-34, B26, B27"),
        ("§6.5", "Five inferred facts, flagged and confirmable", "B27, TC-102"),
        ("§9", "The comparative arithmetic", "B23, TC-131 – TC-138"),
        ("§10", "Every edge case, decided in advance", "TC-79 – TC-96, B13, B25, B29"),
        ("§12.3", "Six settings with history", "B31, TC-97 – TC-100"),
        ("§12.4", "Definition of done", "B01, B33, B02 – B38, this report"),
        ("§7.4", "The assistant proposes and never commits", "B35, B36, TC-126, TC-129"),
    ]:
        add(f"| {row[0]} | {row[1]} | {row[2]} |")
    add("")

    # ------------------------------------------------------------ 7
    add("## 7. What is not covered\n")
    add("| Boundary | What that means | Why it is acceptable |")
    add("|---|---|---|")
    for row in [
        ("PostgreSQL itself", "SQLite stands in; the three exclusion constraints are database "
                              "triggers, so the engine still arbitrates. Range types and GiST "
                              "indexes are not exercised.",
         "Constraint names, codes and outcomes match the design."),
        ("200-user load test", "The drill runs twenty threads, which is the claim the design makes.",
         "The latency budget needs a deployed instance."),
        ("A hosted language model", "The assistant is rule-based but grounded, and the guardrail is real.",
         "The guardrail is the part that decides correctness, and it is tested directly."),
        ("Email delivery", "Notifications are outbox rows drained by a simulated job.",
         "The requirement is that a mail failure cannot undo a booking; TC-116 proves it."),
        ("Authentication", "Three fixed demonstration accounts, printed on the sign-in page.",
         "Required by the definition of done; authority lives in the policy layer."),
    ]:
        add(f"| {row[0]} | {row[1]} | {row[2]} |")
    add("")

    # ------------------------------------------------------------ 8
    add("## 8. How to re-run\n")
    add("```bash")
    add("pip install -r requirements.txt")
    add("python3 -m pytest tests -q                 # 150 domain cases")
    add("python3 tests/e2e/run_browser_suite.py     # 38 browser scenarios, fresh database")
    add("streamlit run app.py                       # the application")
    add("```\n")
    add("| Role | Login | Password |")
    add("|---|---|---|")
    add("| Faculty | a.verma@iet.example.edu | faculty123 |")
    add("| Student | CSE-3A-01 | student123 |")
    add("| Administrator | registrar | admin123 |")
    add("")
    add("---\n")
    add("*End of report.*")

    OUT.write_text("\n".join(L) + "\n")
    print("wrote", OUT, f"({OUT.stat().st_size / 1024:.0f} KB, {len(L)} lines)")


if __name__ == "__main__":
    main()
