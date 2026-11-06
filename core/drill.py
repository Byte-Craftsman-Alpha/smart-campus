"""The concurrency drill: twenty identical requests, one success.

Section 11.2 says double booking is shown to be impossible by a test rather
than asserted in prose. This runs the real insert path from twenty threads with
their own connections.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

from . import config, db, intervals, policy


def run(conn, actor, room_code, start, end, purpose="CLASS", headcount=75,
        section_code=None, requests=20, db_path=None):
    from . import booking

    barrier = threading.Barrier(requests)
    results = []
    lock = threading.Lock()

    def worker(index):
        worker_conn = db.connect(db_path or config.DB_PATH)
        try:
            barrier.wait(timeout=20)
            began = time.perf_counter()
            # The drill isolates one constraint: the room. Section and faculty
            # are given to the first request only, so every later refusal is
            # necessarily about the room.
            outcome = booking.create(
                worker_conn, actor, room_code, start, end, purpose=purpose,
                headcount=headcount,
                section_code=section_code if index == 0 else None,
                faculty_id=actor.faculty_id if index == 0 else None,
                auto_faculty=(index == 0),
                request_id=f"drill-{index}")
            elapsed = (time.perf_counter() - began) * 1000
            with lock:
                results.append({"index": index, "http": outcome["http"], "code": outcome["code"],
                                "alternatives": len(outcome.get("alternatives", [])),
                                "ms": round(elapsed, 1)})
        except Exception as exc:                     # a lock timeout is a result too
            with lock:
                results.append({"index": index, "http": 0, "code": type(exc).__name__,
                                "alternatives": 0, "ms": 0.0})
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(requests)]
    began = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=40)
    elapsed = (time.perf_counter() - began) * 1000

    successes = [r for r in results if r["http"] in (200, 201)]
    conflicts = [r for r in results if r["http"] == 409]
    other = [r for r in results if r not in successes and r not in conflicts]
    live = conn.execute(
        """SELECT COUNT(*) c FROM booking WHERE room_code=? AND status IN ('CONFIRMED','PENDING_APPROVAL')
           AND ? < end_at AND start_at < ?""",
        (room_code, intervals.to_db(intervals.parse_dt(start)),
         intervals.to_db(intervals.parse_dt(end)))).fetchone()["c"]
    from collections import Counter
    return {
        "requests": requests,
        "codes": dict(Counter(r["code"] for r in results)),
        "successes": len(successes),
        "conflicts": len(conflicts),
        "other": other,
        "alternatives_min": min([r["alternatives"] for r in conflicts], default=0),
        "live_rows_in_window": live,
        "elapsed_ms": round(elapsed, 1),
        "results": sorted(results, key=lambda r: r["index"]),
        "verified": len(successes) == 1 and live == 1,
    }
