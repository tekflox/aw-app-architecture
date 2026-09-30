"""Cross-worker job-registry regression test (Kanban 3eb5bf3b-9510-810a-a513-ec5628c2656f).

`jobs._jobs` was a bare in-process dict. The workspace runs
`AW_WORKSPACE_WORKERS=10` — ten OS processes, ten Python heaps, no request
stickiness — so `POST /provision/run` created a job on whichever worker
answered and the next `GET /testcases/jobs/<id>` landed on a different one and
returned `404 no such run job`. Measured live before the fix: 7 of 12
consecutive polls of one healthy job came back 404. The CLI read that as a
provisioning failure and exited non-zero, which the hourly "Architecture Test
Provisioning" task escalated to a full system-analyst agent — ~1.56M input
tokens in one 14h window, repeated for three weeks.

**"Two workers" here is two independently-loaded copies of `jobs.py`.** Each
gets its own module object and therefore its own `_jobs` dict, which is exactly
what a second uvicorn worker is from this module's point of view — the same
thing aw-app-devctl's `test_relay_multiworker.py` achieves with two relay
instances, except loading the module twice also covers the module-level state
that an instance-based test cannot reach.

Both copies share one store, and the suite runs twice over:

* **fake** — an in-memory stand-in for the sync redis client, injected by
  monkeypatching `_store`. No service needed, so this arm runs everywhere,
  including this repo's own CI (which has neither a Redis nor an aw-workspace
  checkout). It exercises the real code path: both module copies go through
  `_mirror`/`_read_shared`/`_scan_shared`.
* **real** — an actual Redis, skipped when one isn't reachable. Same
  assertions against the genuine client, so a fake that has drifted from
  redis-py's behaviour cannot hide a break.

Mutation-tested: with `start()`'s `_mirror(...)` call removed (the fix),
test_job_started_on_one_worker_is_visible_from_another and
test_snapshot_spans_workers fail on both arms.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_JOBS_PY = _REPO_ROOT / "architecture_app" / "jobs.py"

# Isolate this run's keys from any real workspace sharing the same Redis. Set
# before anything reads it, since _key_prefix() resolves it per call.
os.environ["AW_WORKSPACE"] = f"architecture-jobs-test-{uuid.uuid4().hex[:8]}"
os.environ.pop("AW_ARCHITECTURE_JOBS_SHARED", None)


def _load_worker(name: str):
    """Load `jobs.py` under its own module name — a fresh `_jobs` dict, a fresh
    client cache, no shared Python state with any other copy."""
    spec = importlib.util.spec_from_file_location(name, _JOBS_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---- the two store backends -------------------------------------------------

class _FakeSyncRedis:
    """Enough of redis-py's sync surface for jobs.py: set(ex=), get, scan_iter.

    TTLs are honoured against a monotonic clock so the expiry behaviour the
    module relies on is actually exercised, not just accepted.
    """

    def __init__(self) -> None:
        self.data: dict[str, tuple[str, float | None]] = {}

    def set(self, key, value, ex=None):
        self.data[key] = (value, (time.time() + ex) if ex else None)
        return True

    def get(self, key):
        entry = self.data.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and time.time() >= expires:
            self.data.pop(key, None)
            return None
        return value

    def scan_iter(self, match=None):
        prefix = (match or "*").rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix) and self.get(key) is not None:
                yield key


class _DeadRedis:
    """A store that is reachable-looking but fails every call — the
    "Redis is down" arm, which must degrade, not raise."""

    def set(self, *a, **k):
        raise ConnectionError("store is down")

    def get(self, *a, **k):
        raise ConnectionError("store is down")

    def scan_iter(self, *a, **k):
        raise ConnectionError("store is down")


def _real_redis_url() -> str:
    for var in ("AW_TEST_REDIS_URL", "AW_WORKSPACE_REDIS_URL", "AW_REDIS_URL"):
        url = os.environ.get(var)
        if url:
            return url
    return "redis://127.0.0.1:6379/0"


def _real_redis():
    """A live sync client, or None — same resolution order jobs.py uses."""
    try:
        import redis

        client = redis.Redis.from_url(
            _real_redis_url(), decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return client
    except Exception:
        return None


@pytest.fixture(params=["fake", "real"])
def workers(request, monkeypatch):
    """Two independent copies of `jobs.py` sharing one store — worker A and
    worker B. Yields `(a, b, client)`."""
    if request.param == "real":
        client = _real_redis()
        if client is None:
            pytest.skip("no reachable Redis for the real-store arm")
    else:
        client = _FakeSyncRedis()

    a = _load_worker(f"jobs_worker_a_{request.param}")
    b = _load_worker(f"jobs_worker_b_{request.param}")
    for worker in (a, b):
        monkeypatch.setattr(worker, "_store", lambda _c=client: _c)

    yield a, b, client

    if request.param == "real":
        prefix = a._key_prefix()
        for key in client.scan_iter(match=f"{prefix}*"):
            client.delete(key)


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# ---- the regression --------------------------------------------------------

def test_job_started_on_one_worker_is_visible_from_another(workers):
    """THE bug. Worker A starts a job; worker B — which has never heard of it —
    must answer for it rather than 404."""
    a, b, _ = workers
    job = a.start("/some/test_file.py", lambda fp: {"ok": True, "ran": fp})

    assert b._jobs == {}, "worker B must not share worker A's in-process dict"
    seen = b.get(job["id"])
    assert seen is not None, (
        "worker B returned None for a job worker A had just created — this is "
        "the 404 'no such run job' the CLI reads as a provisioning failure")
    assert seen["id"] == job["id"]
    assert seen["file_path"] == "/some/test_file.py"


def test_a_still_queued_job_is_visible_from_another_worker(workers):
    """The `start()` mirror has to happen before the run thread does anything.

    `MAX_CONCURRENT` is 2, so a third job sits at `queued` — sometimes for
    minutes, since the slots ahead of it are cold pip installs. Mirroring only
    on the queued→running transition would leave exactly that window 404ing,
    which is the window a scheduled `autoprovision` poll is most likely to land
    in. Found by mutation-testing: removing `start()`'s own mirror left every
    other test in this file green.
    """
    a, b, _ = workers
    blocked = [threading.Event() for _ in range(a.MAX_CONCURRENT)]
    for gate in blocked:
        a.start("/hog/test_slot.py", lambda _fp, _g=gate: _g.wait(10) or {"ok": True})
    try:
        _wait_for(lambda: sum(1 for j in a.snapshot()
                              if j["status"] == "running") == a.MAX_CONCURRENT)
        queued = a.start("/some/test_waiting.py", lambda fp: {"ok": True})
        assert a.get(queued["id"])["status"] == "queued", (
            "setup failed — the job was expected to be waiting on the semaphore")

        seen = b.get(queued["id"])
        assert seen is not None, (
            "a queued job is invisible to other workers — a poll landing on one "
            "of them 404s on a job that has not even started yet")
        assert seen["status"] == "queued"
    finally:
        for gate in blocked:
            gate.set()


def test_result_of_a_finished_job_crosses_workers(workers):
    """Not just the id: the result the poller is actually waiting for."""
    a, b, _ = workers
    job = a.start("/some/test_file.py", lambda fp: {"ok": True, "provisioned": []})

    done = _wait_for(lambda: (b.get(job["id"]) or {}).get("status") == "done"
                     and b.get(job["id"]))
    assert done, "worker B never saw the job reach 'done'"
    assert done["result"] == {"ok": True, "provisioned": []}
    assert done["error"] is None
    assert done["finished_at"]


def test_a_failing_run_reports_its_error_across_workers(workers):
    a, b, _ = workers

    def _boom(_fp):
        raise RuntimeError("pip exploded")

    job = a.start("/some/test_file.py", _boom)
    done = _wait_for(lambda: (b.get(job["id"]) or {}).get("status") == "done"
                     and b.get(job["id"]))
    assert done, "worker B never saw the failing job finish"
    assert done["error"] == "RuntimeError: pip exploded"


def test_snapshot_spans_workers(workers):
    """A UI that reloaded onto another worker must still find the run."""
    a, b, _ = workers
    job_a = a.start("/a/test_one.py", lambda fp: {"ok": True})
    job_b = b.start("/b/test_two.py", lambda fp: {"ok": True})

    ids_from_b = {j["id"] for j in b.snapshot()}
    assert job_a["id"] in ids_from_b, "worker A's job is missing from B's snapshot"
    assert job_b["id"] in ids_from_b
    assert {j["id"] for j in a.snapshot()} == ids_from_b


def test_the_heartbeat_keeps_a_long_run_visible_past_the_live_ttl(workers, monkeypatch):
    """A running job's shared entry is short-lived on purpose — that is what
    makes a dead worker's claim expire instead of asserting "running" forever.
    The owning worker therefore has to renew it, or a provision that outlives
    one TTL window (they all do: cold pip is minutes, the TTL is 120s) goes
    invisible mid-run and the poll 404s on a healthy job.

    The real constants are too slow to observe, so they're shrunk here: a 1s
    TTL renewed every 0.2s, checked after more than two windows have passed.
    """
    a, b, _ = workers
    monkeypatch.setattr(a, "_LIVE_TTL_S", 1)
    monkeypatch.setattr(a, "_HEARTBEAT_INTERVAL_S", 0.2)

    release = threading.Event()
    job = a.start("/slow/test_thing.py", lambda _fp: release.wait(10) or {"ok": True})
    try:
        time.sleep(2.3)          # > 2 × the shrunk TTL
        seen = b.get(job["id"])
        assert seen is not None, (
            "the running job's shared entry expired mid-run — the owning "
            "worker is not renewing it")
        assert seen["status"] == "running"
    finally:
        release.set()


def test_own_job_is_served_from_the_local_dict(workers):
    """The worker that owns the run stays authoritative — it holds the live
    object, so it must not be reading its own state back out of the store."""
    a, _b, client = workers
    job = a.start("/some/test_file.py", lambda fp: {"ok": True})
    _wait_for(lambda: (a.get(job["id"]) or {}).get("status") == "done")

    # Corrupt the shared copy; the owner must be unaffected.
    client.set(a._key_prefix() + job["id"], json.dumps({"id": job["id"],
                                                        "status": "bogus"}), ex=60)
    assert a.get(job["id"])["status"] == "done"


def test_finished_jobs_are_shared_with_the_retention_window_as_a_ttl(workers):
    """The original objection to persisting this state was rows outliving what
    they describe. The shared copy answers it with a TTL, not with a reaper."""
    a, _b, client = workers
    job = a.start("/some/test_file.py", lambda fp: {"ok": True})
    _wait_for(lambda: (a.get(job["id"]) or {}).get("status") == "done")

    ttl = client.ttl(a._key_prefix() + job["id"]) if hasattr(client, "ttl") else None
    if ttl is None:  # fake client — assert against its own expiry bookkeeping
        _value, expires = client.data[a._key_prefix() + job["id"]]
        ttl = expires - time.time()
    assert 0 < ttl <= a._RETAIN_SECONDS
    assert ttl > a._LIVE_TTL_S, (
        "a finished job must be retained for the full window, not the short "
        "live TTL — a late poller would otherwise get a 404 for the result")


# ---- degradation -----------------------------------------------------------

def test_an_unreachable_store_degrades_to_worker_local(monkeypatch):
    """Redis down must cost cross-worker visibility and nothing else: the job
    still runs, the owning worker still answers for it, no exception escapes."""
    dead = _DeadRedis()
    a = _load_worker("jobs_worker_a_dead")
    b = _load_worker("jobs_worker_b_dead")
    for worker in (a, b):
        monkeypatch.setattr(worker, "_store", lambda _c=dead: _c)

    job = a.start("/some/test_file.py", lambda fp: {"ok": True})
    done = _wait_for(lambda: (a.get(job["id"]) or {}).get("status") == "done"
                     and a.get(job["id"]))
    assert done and done["result"] == {"ok": True}
    assert b.get(job["id"]) is None          # degraded, as before the fix
    assert b.snapshot() == []                # and not an exception


def test_sharing_can_be_turned_off(monkeypatch):
    """`AW_ARCHITECTURE_JOBS_SHARED=0` is the field escape hatch."""
    a = _load_worker("jobs_worker_a_off")
    monkeypatch.setenv(a.SHARE_ENV, "0")
    assert a._store() is None
    monkeypatch.setenv(a.SHARE_ENV, "1")
    assert a._sharing_enabled() is True


def test_key_prefix_is_scoped_to_the_workspace(monkeypatch):
    """Two workspaces on one Redis must not see each other's jobs."""
    a = _load_worker("jobs_worker_a_prefix")
    monkeypatch.delenv("AW_WORKSPACE_REDIS_URL", raising=False)
    prefix = a._key_prefix()
    assert prefix.endswith("architecture:job:")
    assert os.environ["AW_WORKSPACE"] in prefix
