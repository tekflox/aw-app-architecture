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

**Why the registry is mirrored into Redis (2026-09-30).** This module used to
keep `_jobs` as a bare in-process dict and argue for it: "a job is a few
minutes of liveness, and a workspace restart means whatever was running died
with it — recording 'running' in a table would just leave rows that outlive
the thing they describe." That reasoning was about *durability* and it still
holds. What it missed is *visibility*: the workspace runs
`AW_WORKSPACE_WORKERS=10`, ten separate OS processes with ten separate Python
heaps and no request stickiness. `POST /provision/run` creates a job on
whichever worker answered; the very next `GET /testcases/jobs/<id>` lands on a
different one, finds nothing, and returns `404 no such run job`. Measured
2026-09-30 against the live workspace before this change: **7 of 12
consecutive polls of one healthy job came back 404.**

`aw-workspace-cli architecture autoprovision` read that 404 as a failure and
exited non-zero with every component provisioned correctly, which the hourly
"Architecture Test Provisioning" task escalated to a full system-analyst agent
— ~1.56M input tokens in one 14h window, and at least ten prior rounds since
2026-09-07, each independently re-deriving the same diagnosis. Kanban
3eb5bf3b-9510-810a-a513-ec5628c2656f.

So each job is *also* written to a TTL'd Redis key
(`aw:ws:<ws>:architecture:job:<id>`), which every worker can read — the same
STATE-mirror shape `src/apps/install_jobs.py` and `aw-app-devctl`'s tab
registry already use for this exact class of bug, and the same in-process-dict
→ Redis move that fixed the cross-worker Telegram approval buttons in
agents-platform-multitenant.

The TTL is what keeps the original objection answered: nothing here outlives
what it describes. A queued/running job's entry is short-lived and renewed by
a heartbeat from the worker that owns the run, so a worker that dies takes its
claim with it rather than leaving a row asserting "running" forever; a
finished job's entry is retained for exactly `_RETAIN_SECONDS`, the same
window the in-process copy is kept for, and then expires on its own.
`last_run_status` on the testcase is still the durable record, written by the
runner exactly as before.

The mirror is strictly additive. This worker's own `_jobs` dict stays
authoritative for its own jobs (it holds the live object the run thread
mutates), and every Redis call is wrapped: an unreachable store degrades to
exactly the pre-2026-09-30 worker-local behaviour instead of failing a
request. `AW_ARCHITECTURE_JOBS_SHARED=0` turns the mirror off outright.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

log = logging.getLogger("aw_apps.architecture.jobs")

#: At most this many test subprocesses at once. Two rather than one so a slow
#: suite doesn't stall an unrelated quick check, and not more because these are
#: full pytest runs sharing the workspace's CPU with everything else it does.
MAX_CONCURRENT = 2
_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT)

#: Finished jobs are kept this long so a poller that arrives late still gets
#: the result instead of a 404 it would have to interpret. Applies to both
#: copies: the in-process dict is reaped on create, the shared entry expires.
_RETAIN_SECONDS = 30 * 60

#: How long the shared copy of a queued/running job survives without a
#: refresh. The owning worker renews it every `_HEARTBEAT_INTERVAL_S`, with
#: several beats' slack so a slow Redis blip doesn't make a live job vanish.
#: This expiring therefore means the worker that owned the run is gone — and a
#: poller then gets an honest 404 instead of an entry stuck at "running".
_LIVE_TTL_S = 120
_HEARTBEAT_INTERVAL_S = 30

#: Set to 0/false for purely worker-local behaviour — what the tests that want
#: no store use, and the field escape hatch if the mirror ever needs turning
#: off without a redeploy.
SHARE_ENV = "AW_ARCHITECTURE_JOBS_SHARED"

#: After a failed Redis call, don't try again for this long. A store that is
#: down has to cost one attempt per cooldown, not one attempt per poll —
#: otherwise "Redis is unreachable" turns into "every job poll waits for a
#: socket timeout first", which is a worse outcome than the bug this fixes.
_BREAKER_COOLDOWN_S = 30

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

_client: Any = None
_client_lock = threading.Lock()
_breaker_until = 0.0


# ---- the shared copy --------------------------------------------------------

def _sharing_enabled() -> bool:
    return (os.environ.get(SHARE_ENV) or "1").strip().lower() not in (
        "0", "false", "no", "off")


def _redis_url() -> str:
    """Core's resolution order when core is importable, mirrored when it isn't.

    Tier-1 apps run inside the workspace process, so `src.libs.redis_coord` is
    normally right there — but this module also has to work in standalone mode
    and in this repo's own CI, where there is no aw-workspace checkout on
    `sys.path`. Falling back to the same three env vars keeps one behaviour
    instead of two.
    """
    try:
        from src.libs.redis_coord import get_workspace_redis_url
        return get_workspace_redis_url()
    except Exception:
        return (os.environ.get("AW_WORKSPACE_REDIS_URL")
                or os.environ.get("AW_REDIS_URL")
                or "redis://127.0.0.1:6379/0")


def _key_prefix() -> str:
    """`aw:ws:<workspace>:architecture:job:` — scoped under the same
    per-workspace namespace every other key in this Redis lives under, so two
    workspaces sharing one instance cannot see each other's jobs."""
    try:
        from src.libs.redis_coord import _key_prefix as _core_prefix
        base = _core_prefix()
    except Exception:
        base = f"aw:ws:{os.environ.get('AW_WORKSPACE') or 'default'}:"
    return f"{base}architecture:job:"


def _store() -> Any:
    """The shared registry client, or ``None`` when sharing is off or the
    store is in its failure cooldown.

    Sync rather than async: every caller in this module is sync (the run
    happens in a plain thread), same choice agents-platform-runners' warm pool
    made for the same reason. The routes that read it go through
    ``run_in_threadpool``.
    """
    global _client, _breaker_until
    if not _sharing_enabled():
        return None
    with _client_lock:
        if _client is not None:
            return _client
        if time.time() < _breaker_until:
            return None
        try:
            import redis  # sync client
            _client = redis.Redis.from_url(
                _redis_url(), decode_responses=True,
                socket_connect_timeout=1, socket_timeout=1)
            return _client
        except Exception as exc:                          # noqa: BLE001
            _breaker_until = time.time() + _BREAKER_COOLDOWN_S
            log.debug("architecture: no shared job registry (%s) — job ids will "
                      "only be visible on the worker that created them", exc)
            return None


def _trip(exc: Exception, what: str) -> None:
    """Drop the client and stop trying for `_BREAKER_COOLDOWN_S`."""
    global _client, _breaker_until
    with _client_lock:
        _client = None
        _breaker_until = time.time() + _BREAKER_COOLDOWN_S
    log.debug("architecture: shared job registry %s failed — falling back to "
              "this worker's own jobs for %ss: %s", what, _BREAKER_COOLDOWN_S, exc)


def _mirror(job: dict[str, Any], ttl: int) -> None:
    """Publish `job` for every other worker to read. Best-effort by design."""
    client = _store()
    if client is None:
        return
    try:
        client.set(_key_prefix() + job["id"], json.dumps(job, default=str), ex=ttl)
    except Exception as exc:                              # noqa: BLE001
        _trip(exc, "write")


def _read_shared(job_id: str) -> dict[str, Any] | None:
    client = _store()
    if client is None:
        return None
    try:
        raw = client.get(_key_prefix() + job_id)
    except Exception as exc:                              # noqa: BLE001
        _trip(exc, "read")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        log.debug("architecture: malformed shared job entry for %s", job_id)
        return None


def _scan_shared() -> list[dict[str, Any]]:
    client = _store()
    if client is None:
        return []
    prefix = _key_prefix()
    found: list[dict[str, Any]] = []
    try:
        for key in client.scan_iter(match=f"{prefix}*"):
            raw = client.get(key)
            if not raw:
                continue          # expired between the scan and the read
            try:
                found.append(json.loads(raw))
            except ValueError:
                continue
    except Exception as exc:                              # noqa: BLE001
        _trip(exc, "scan")
    return found


def _heartbeat(job: dict[str, Any], stop: threading.Event) -> None:
    """Renew the shared copy of a running job until it finishes.

    Without this the entry would expire mid-run and a poll landing on another
    worker would 404 on a perfectly healthy job — the bug, reintroduced with
    extra steps. With it, an expired entry carries real information: the
    worker that owned the run is gone.
    """
    while not stop.wait(_HEARTBEAT_INTERVAL_S):
        with _lock:
            if job.get("finished_at"):
                return
            snap = dict(job)
        _mirror(snap, _LIVE_TTL_S)


# ---- the registry ----------------------------------------------------------

def _reap(now: float) -> None:
    """Drop finished jobs past the retention window. Called on every create,
    so the dict cannot grow without bound in a long-lived process. The shared
    copies need no equivalent — they carry the same window as a TTL."""
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
        snap = dict(job)
    # Before the thread starts, and before the id is handed back: the caller's
    # first poll can land on any of the ten workers, including one that has
    # never heard of this job.
    _mirror(snap, _LIVE_TTL_S)

    def _work() -> None:
        # Acquired inside the thread, not before it starts: the caller must get
        # its job id back straight away even when both slots are busy, which is
        # the whole point. A queued job is honest about waiting.
        with _SEMAPHORE:
            with _lock:
                job["status"] = "running"
                snap = dict(job)
            _mirror(snap, _LIVE_TTL_S)
            stop = threading.Event()
            threading.Thread(target=_heartbeat, args=(job, stop),
                             name=f"testrun-hb-{job_id}", daemon=True).start()
            try:
                job["result"] = run(file_path)
            except Exception as exc:                      # noqa: BLE001
                job["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                stop.set()
                with _lock:
                    job["status"] = "done"
                    job["finished_at"] = time.time()
                    snap = dict(job)
                # Retained for the same window as the in-process copy, so a
                # late poller gets the result off whichever worker answers.
                _mirror(snap, _RETAIN_SECONDS)

    threading.Thread(target=_work, name=f"testrun-{job_id}", daemon=True).start()
    return dict(job)


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            return dict(job)
    # Not this worker's job. Under AW_WORKSPACE_WORKERS=10 that is the normal
    # case, not the exceptional one: the POST that created it landed on one of
    # ten processes and this GET landed on another.
    return _read_shared(job_id)


def snapshot() -> list[dict[str, Any]]:
    """Every job still known about anywhere — this worker's own (authoritative,
    they hold the live objects) plus whatever the other workers have mirrored,
    deduplicated by id. So a UI that lost its job id (a reload mid-run) can
    find the run again rather than starting a second one, even when the reload
    lands on a different worker than the run did."""
    with _lock:
        jobs = {job_id: dict(j) for job_id, j in _jobs.items()}
    for shared in _scan_shared():
        job_id = shared.get("id")
        if job_id and job_id not in jobs:
            jobs[job_id] = shared
    return sorted(jobs.values(),
                  key=lambda j: j.get("started_at") or 0, reverse=True)
