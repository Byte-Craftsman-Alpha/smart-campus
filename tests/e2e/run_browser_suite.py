"""Run the browser suite against a freshly seeded application.

Starts Streamlit on a private port, walks every scenario in a real Chromium
window, captures a screenshot per scenario and writes a JSON result file that
the report builder reads.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

import scenarios as scenario_mod  # noqa: E402
from harness import UI, UIError  # noqa: E402

from core import config, db  # noqa: E402


def start_app(port: int, fresh: bool) -> subprocess.Popen:
    if fresh:
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(config.DB_PATH) + suffix)
            if path.exists():
                path.unlink()
    db.ensure_db()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(port), "--server.address", "0.0.0.0",
         "--server.headless", "true", "--browser.gatherUsageStats", "false",
         "--server.fileWatcherType", "none"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        line = proc.stdout.readline()
        if "You can now view" in line or "Uvicorn server started" in line:
            break
    time.sleep(3)
    return proc


def run(port: int, shot_dir: Path, only: list[str] | None = None) -> dict:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        for scenario in scenario_mod.SCENARIOS:
            if only and scenario.id not in only:
                continue
            context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                          device_scale_factor=1)
            page = context.new_page()
            ui = UI(page, shot_dir, base_url=f"http://localhost:{port}")
            ui._watch()
            record = {
                "id": scenario.id, "title": scenario.title, "role": scenario.role,
                "case": scenario.case, "steps": scenario.steps,
                "expected": scenario.expected, "requirement": scenario.requirement,
                "tags": scenario.tags, "status": "passed", "observation": "",
                "screenshots": [], "console_errors": [], "error": "",
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
            began = time.time()
            try:
                # every scenario is self-contained: a fresh context, a sign-in
                if scenario.role != "none":
                    ui.goto()
                    ui.sign_in(scenario.role)
                observation = scenario.run(ui)
                record["observation"] = observation or ""
                # every scenario leaves one screenshot, whatever it captured on the way
                last = sorted(shot_dir.glob(f"{scenario.id}*.png"))
                if not last:
                    path = ui.shot(scenario.id)
                    last = [Path(path)]
                record["screenshots"] = [p.name for p in last]
            except (UIError, AssertionError, Exception) as exc:  # noqa: BLE001
                record["status"] = "failed"
                record["error"] = f"{type(exc).__name__}: {exc}"[:600]
                record["observation"] = "Scenario did not reach its expected state."
                try:
                    path = ui.shot(f"{scenario.id}_FAILED")
                    record["screenshots"] = [Path(path).name]
                except Exception:  # noqa: BLE001
                    pass
            finally:
                record["console_errors"] = ui.console_errors[:6]
                record["duration_s"] = round(time.time() - began, 1)
                context.close()
                results.append(record)
                print(f"  {record['status'].upper():6s} {scenario.id}  {scenario.title} "
                      f"({record['duration_s']}s)")
    return {
        "suite": "browser",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "passed": sum(1 for r in results if r["status"] == "passed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8511)
    parser.add_argument("--shots", default=str(ROOT / "docs" / "testing" / "screenshots"))
    parser.add_argument("--out", default=str(ROOT / "qa" / "results" / "browser_results.json"))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--reuse-app", action="store_true")
    args = parser.parse_args()

    shot_dir = Path(args.shots)
    shot_dir.mkdir(parents=True, exist_ok=True)
    proc = None
    if not args.reuse_app:
        print("starting the application…")
        proc = start_app(args.port, fresh=True)
        print("application up on", args.port)
    try:
        summary = run(args.port, shot_dir, only=args.only)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2))
    print(f"\n{summary['passed']} passed, {summary['failed']} failed "
          f"-> {args.out}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
