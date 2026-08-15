"""Test discovery scanner for the Architecture namespace.

Walks each component's `test_base_path` (see `store.Component`) and upserts a
`Testcase` row per test file found, with `component_id` set — so the Tests view
stays populated dynamically as tests are added/removed, instead of every test
needing to be registered by hand via `create_testcase`.

`test_base_path` is a single Text column but accepts a plain path
(backward-compatible) or a comma-separated / JSON-array list of paths, so one
component can own more than one directory (see `_base_paths`) — e.g. both its
unit and integration test dirs. Callers are expected to keep each component's
path list disjoint from every other component's; discovery only warns (doesn't
refuse) if a file it's about to claim already belongs to a different component,
since Postgres `ON CONFLICT` always lets the current scan's non-null
component_id win.

Idempotent and non-destructive: `upsert_testcase` never clobbers an
already-known test's `run_command` / `is_flaky` / `last_run_status` — a rescan
only adds new files and refreshes `kind` for known ones.

Recognizes two test styles today:
  - Python:  test_*.py / *_test.py                -> pytest, runnable as-is
  - Swift:   *Tests.swift / *Test.swift            -> XCTest, needs an
             explicit run_command registered separately (set_testcase_run_command)
             since there's no generic "run a Swift test" convention.

**What changed in the port.** The monolith resolved every path against its own
`src.BASE_DIR` — one repo, one checkout. Here the root is the workspace
(`AW_WORKSPACE_CONTAINER_DIR`, default `/opt/aw-workspace`), so a
`test_base_path` is workspace-relative and can name any repo under `repos/` or
any directory a mapped folder exposes — a component in `aw-app-tasks` and one
in `aw-workspace` are both reachable from a single scan, which is the whole
point of the namespace now that the code lives in many repos instead of one.

Run standalone (used by the "Architecture Test Discovery" scheduled task):
    python -m architecture_app.discovery
though the scheduled task calls `POST /api/apps/architecture/discovery/run`
instead, so the scan runs in the process that already holds the DB session.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from . import store as db

_log = logging.getLogger(__name__)

_PY_TEST_PREFIXES = ("test_",)
_PY_TEST_SUFFIXES = ("_test.py",)
_SWIFT_TEST_SUFFIXES = ("Tests.swift", "Test.swift")

# Directories never worth descending into during a scan.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".tmp"}


def workspace_root() -> str:
    """Root every `test_base_path` is resolved against.

    Read from the environment on each call rather than captured at import: the
    CLI, the server and app containers all run from different cwds, and a
    module-level constant would freeze whichever one happened to import first.
    """
    return os.environ.get("AW_WORKSPACE_CONTAINER_DIR", "/opt/aw-workspace")


def _infer_kind(rel_path: str) -> str:
    lower = rel_path.lower()
    if "e2e" in lower or "uitest" in lower:
        return "e2e"
    if "integration" in lower:
        return "integration"
    return "unit"


def _is_python_test(filename: str) -> bool:
    return filename.endswith(".py") and (
        filename.startswith(_PY_TEST_PREFIXES) or filename.endswith(_PY_TEST_SUFFIXES)
    )


def _is_swift_test(filename: str) -> bool:
    return filename.endswith(_SWIFT_TEST_SUFFIXES)


def _scan_dir(abs_base: str) -> list[str]:
    """Return workspace-relative file paths of every recognized test file
    under `abs_base`."""
    root_dir = workspace_root()
    found = []
    for root, dirs, files in os.walk(abs_base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if _is_python_test(f) or _is_swift_test(f):
                abs_path = os.path.join(root, f)
                found.append(os.path.relpath(abs_path, root_dir))
    return sorted(found)


def _base_paths(comp: dict) -> list[str]:
    """test_base_path is a single Text column but accepts either a plain path
    (backward-compatible) or multiple paths, so one component can own more than
    one directory (e.g. its unit + integration dirs) — as a JSON array string
    or a comma-separated list."""
    raw = comp.get("test_base_path") or ""
    raw = raw.strip()
    if raw.startswith("["):
        return json.loads(raw)
    return [p.strip() for p in raw.split(",") if p.strip()]


def discover_component_tests(component_slug: str) -> dict:
    """Scan one component's test_base_path (one or more dirs) and upsert a
    Testcase row per file found. Returns a summary: {component_slug,
    scanned_path, found, skipped_no_path}."""
    comps = {c["slug"]: c for c in db.list_components_with_test_base_path()}
    comp = comps.get(component_slug)
    if comp is None or not comp.get("test_base_path"):
        return {"component_slug": component_slug, "skipped_no_path": True, "found": []}

    paths = _base_paths(comp)
    files: list[str] = []
    errors = []
    for path in paths:
        abs_base = os.path.join(workspace_root(), path)
        if not os.path.isdir(abs_base):
            errors.append(f"directory not found: {abs_base}")
            continue
        files.extend(_scan_dir(abs_base))
    files = sorted(set(files))

    for rel_path in files:
        owner = db.get_testcase_owner_slug(rel_path)
        if owner is not None and owner != component_slug:
            _log.warning(
                "test discovery for '%s' is reassigning '%s' away from '%s' — "
                "test_base_path lists that should be pairwise-disjoint across "
                "components now overlap.", component_slug, rel_path, owner,
            )
        kind = _infer_kind(rel_path)
        db.upsert_testcase(kind=kind, file_path=rel_path, component_slug=component_slug)

    result = {
        "component_slug": component_slug,
        "scanned_path": comp["test_base_path"],
        "found": files,
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def discover_all() -> list[dict]:
    """Run discovery for every component that has a test_base_path set.
    This is what the periodic "Architecture Test Discovery" task calls."""
    comps = db.list_components_with_test_base_path()
    return [discover_component_tests(c["slug"]) for c in comps]


if __name__ == "__main__":
    summary = discover_all()
    total = sum(len(r["found"]) for r in summary)
    for r in summary:
        if r.get("error"):
            print(f"  {r['component_slug']}: ERROR — {r['error']}")
        else:
            print(f"  {r['component_slug']} ({r.get('scanned_path')}): "
                  f"{len(r['found'])} test file(s)")
    print(f"Architecture test discovery: {len(summary)} component(s) scanned, "
          f"{total} test file(s) total.")
    sys.exit(0)
