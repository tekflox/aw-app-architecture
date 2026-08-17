"""Background test runs — a play button must not hold a request open.

`POST /testcases/run` used to block until pytest finished. Three consequences,
all observed:

* **The tunnel edge cuts at ~30s.** A suite slower than that came back to the
  browser as "502 workspace offline" while the run completed server-side, so
  the UI could not tell a slow pass from a dead workspace.
* **A threadpool worker was held for the whole run.** Starlette's pool is
  shared with every other route in the workspace; a handful of 5-minute test
  runs is a real bite out of it.
* **Nothing bounded concurrency.** `run_component_tests` loops over every test
  linked to a component, and a component with 77 of them would fork 77 pytest
  processes back to back with no ceiling. On 2026-08-16 a sweep of ~37 suites
  coincided with the workspace going unreachable for about 90 seconds; the
  cause was never proven, and it is deliberately not claimed here — but "an
  unbounded number of heavy subprocesses" is a hazard worth removing whether
  or not it was that one.

So: a run is started, a job id comes back immediately, and the caller polls.
`_SEMAPHORE` caps how many test subprocesses exist at once.

State is in-process and deliberately not persisted. A job is a few minutes of
liveness, and a workspace restart means whatever was running died with it —
recording "running" in a table would just leave rows that outlive the thing
they describe. `last_run_status` on the testcase is the durable record, and
that is written by the runner exactly as before.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

#: At most this many test subprocesses at once. Two rather than one so a slow
#: suite doesn't stall an unrelated quick check, and not more because these are
#: full pytest runs sharing the workspace's CPU with everything else it does.
MAX_CONCURRENT = 2
_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT)

#: Finished jobs are kept this long so a poller that arrives late still gets
#: the result instead of a 404 it would have to interpret.
_RETAIN_SECONDS = 30 * 60

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _reap(now: float) -> None:
    """Drop finished jobs past the retention window. Called on every create,
    so the dict cannot grow without bound in a long-lived process."""
    for job_id, job in list(_jobs.items()):
        done_at = job.get("finished_at")
        if done_at and now - done_at > _RETAIN_SECONDS:
            _jobs.pop(job_id, None)


def start(file_path: str, run: Any) -> dict[str, Any]:
    """Kick off ``run()`` in a daemon thread and return the job immediately.

    ``run`` is the callable that actually executes the test — passed in rather
    than imported so this module has no opinion about how a test is run, and
    the runner stays the one place that knows.
    """
    now = time.time()
    job_id = f"run-{uuid.uuid4().hex[:12]}"
    job = {"id": job_id, "file_path": file_path, "status": "queued",
           "started_at": now, "finished_at": None, "result": None, "error": None}
    with _lock:
        _reap(now)
        _jobs[job_id] = job

    def _work() -> None:
        # Acquired inside the thread, not before it starts: the caller must get
        # its job id back straight away even when both slots are busy, which is
        # the whole point. A queued job is honest about waiting.
        with _SEMAPHORE:
            with _lock:
                job["status"] = "running"
            try:
                job["result"] = run(file_path)
            except Exception as exc:                      # noqa: BLE001
                job["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                with _lock:
                    job["status"] = "done"
                    job["finished_at"] = time.time()

    threading.Thread(target=_work, name=f"testrun-{job_id}", daemon=True).start()
    return dict(job)


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def snapshot() -> list[dict[str, Any]]:
    """Every job this process still knows about, newest first — so a UI that
    lost its job id (a reload mid-run) can find the run again rather than
    starting a second one."""
    with _lock:
        return sorted((dict(j) for j in _jobs.values()),
                      key=lambda j: j["started_at"], reverse=True)
