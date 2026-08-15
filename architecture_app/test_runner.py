"""Runs a single Architecture namespace test case and records its result.

Shared by the MCP's `run_component_tests` (loops this over every test linked to
a component) and the REST "run this test" action (the Tests view's play
button) — both need the exact same subprocess + status-recording behavior, so
it lives in one place instead of being duplicated between the two callers.

**What changed in the port.** The monolith hardcoded its own interpreter
(`.venv/aw/bin/python`) and resolved everything against `src.BASE_DIR`. Both
were single-repo assumptions. Here:

* the fallback interpreter is `sys.executable` — whatever Python this app is
  running under, which in integrated (Tier-1) mode is the workspace's own;
* paths resolve against the workspace root, so a testcase can live in any repo
  under `repos/` or any mapped folder.

A repo with its own venv or its own pytest config still needs an explicit
`run_command` (see `set_testcase_run_command`) — the fallback is deliberately
the naive `python -m pytest <file>`, and a repo whose suite doesn't run that
way should say so rather than have this module guess.
"""

from __future__ import annotations

import os
import subprocess
import sys

from . import store as db
from .discovery import workspace_root

# Console output can be large (verbose pytest); cap what we keep/return so a
# noisy test can't blow up the response or the DB row.
_MAX_OUTPUT_CHARS = 20_000


def run_testcase(file_path: str, timeout: int = 300) -> dict:
    """Run one test case, record last_run_status/at, return the outcome plus
    captured console output for display.

    Dispatch is per-testcase, not hardcoded to pytest:
    - If the testcase has an explicit `run_command` set (see
      `set_testcase_run_command`), run that instead — any command works
      (a Python script dispatching to a Remote Agent for a Swift XCTest on
      the Xcode Simulator, a shell one-liner, whatever), as long as it
      exits 0 on pass / non-zero on fail, same convention as pytest.
    - Otherwise, only .py files are runnable via the pytest fallback. A
      non-Python test with no run_command registered can't be executed
      here, and must NOT be recorded as "fail" just because pytest
      couldn't collect it — that would silently corrupt a real (possibly
      passing) status with a false negative. Leave last_run_status
      untouched in that case.
    """
    root = workspace_root()
    testcase = db.get_testcase_by_path(file_path)
    run_command = testcase.get("run_command") if testcase else None

    if not run_command and not file_path.endswith(".py"):
        return {
            "file_path": file_path, "status": "not_runnable",
            "output": (
                f"'{file_path}' has no run_command registered and isn't a pytest file. "
                "Non-Python suites (e.g. Swift XCTest) need an explicit run_command "
                "(e.g. a Python script dispatching to a Remote Agent) — see "
                "set_testcase_run_command. Left untouched."
            ),
        }

    if run_command:
        cmd, shell = run_command, True
    else:
        full = os.path.join(root, file_path)
        if not os.path.exists(full):
            db.update_testcase_result(file_path, "unknown")
            return {"file_path": file_path, "status": "unknown",
                    "output": f"file not found: {file_path}"}
        cmd = [sys.executable, "-m", "pytest", file_path, "-v", "--no-header"]
        shell = False

    try:
        proc = subprocess.run(
            cmd, shell=shell, cwd=root, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            status = "passing"
        elif not run_command and proc.returncode in (4, 5):  # pytest usage/collection error
            status = "unknown"
        else:
            status = "fail"
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        status, output = "fail", f"timeout after {timeout}s"

    db.update_testcase_result(file_path, status)
    return {"file_path": file_path, "status": status, "output": output[-_MAX_OUTPUT_CHARS:]}
