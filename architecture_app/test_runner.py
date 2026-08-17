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


def _component_command(testcase: dict, file_path: str) -> str | None:
    """Render the component's ``test_cmd`` template for one file.

    ``{file}`` -> workspace-relative path (what the runner's cwd is anchored
    to). ``{rel}`` -> path relative to the component's own repo, which is what
    a command that `cd`s into that repo needs. Neither present -> append the
    path, so the simplest useful template is just `pytest`.
    """
    template = (testcase.get("component_test_cmd") or "").strip()
    if not template:
        return None
    rel = file_path
    repo = testcase.get("component_repo")
    prefix = f"repos/{repo}/"
    if repo and file_path.startswith(prefix):
        rel = file_path[len(prefix):]
    if "{file}" in template or "{rel}" in template:
        return template.replace("{file}", file_path).replace("{rel}", rel)
    return f"{template} {file_path}"
#: Re-exported from the store, which owns it: setting a SKIP: command is a
#: WRITE (it also retires the stale verdict), so the marker has to be known
#: where that write happens.
SKIP_PREFIX = db.SKIP_PREFIX


#: pytest exit codes that mean NO VERDICT WAS PRODUCED, as opposed to 1, which
#: means tests ran and failed — the only one that is real signal about the code.
#:
#:   2  collection error (measured: an ImportError in a test module exits 2)
#:   4  usage error
#:   5  nothing collected
#:
#: 2 is also what pytest returns on a user interrupt, so it is not exclusively
#: "could not collect" — but every meaning of 2 is still "no result", which is
#: what `unknown` records. aw-app-mini-browser fails to collect here purely
#: because this container lacks its `mcp` dependency; calling that a broken
#: test would be a false negative on a suite that is probably green in CI.
_PYTEST_NOT_A_RESULT = {2, 4, 5}


def _classify(returncode: int, command: str) -> str:
    """Turn an exit code into passing / fail / unknown.

    The pytest exit-code nuance used to apply ONLY to the built-in fallback:
    any non-zero from an explicit run_command was recorded as "fail". So a
    component whose per-repo test_cmd hit a collection error got a red mark on
    a test that never ran — observed on aw-app-mini-browser ("ERROR collecting
    test session") and aw-app-crispal ("1 skipped"). Both read as broken code.

    Whether the command came from the testcase, its component, or the fallback
    has nothing to do with how pytest reports itself, so the interpretation
    follows the RUNNER, not the source of the string.
    """
    if returncode == 0:
        return "passing"
    if "pytest" in command and returncode in _PYTEST_NOT_A_RESULT:
        return "unknown"
    return "fail"


def run_testcase(file_path: str, timeout: int = 300) -> dict:
    """Run one test case, record last_run_status/at, return the outcome plus
    captured console output for display.

    Three levels, most specific first — all exiting 0 on pass / non-zero on
    fail, the pytest convention, so the play button works the same regardless
    of what actually runs:

    1. the testcase's own ``run_command`` (``set_testcase_run_command``) — the
       escape hatch for one awkward file;
    2. its component's ``test_cmd`` — **the one that scales**. Discovery finds
       hundreds of files; registering a command on each is not a thing anyone
       will do, while "this is how you run one test in this repo" is a single
       fact per repo. `{file}` in the template is replaced with the
       workspace-relative path and `{rel}` with the path relative to the
       component's repo; with no placeholder the path is appended.
    3. the naive ``python -m pytest <file>`` fallback, which only applies to
       ``.py``.

    A non-Python test with none of the above can't be executed here and must
    NOT be recorded as "fail" just because pytest couldn't collect it — that
    would overwrite a real (possibly passing) status with a false negative.
    Left untouched in that case.
    """
    root = workspace_root()
    testcase = db.get_testcase_by_path(file_path) or {}
    explicit = (testcase.get("run_command") or "").strip()
    if explicit.startswith(SKIP_PREFIX):
        # Deliberately not run here. NOT recorded as a result: last_run_status
        # is left exactly as it was, because "we chose not to run it" says
        # nothing about whether it passes.
        return {
            "file_path": file_path, "status": "not_runnable",
            "output": explicit[len(SKIP_PREFIX):].strip() or
                      "marked not runnable in this environment",
        }
    run_command = explicit or _component_command(testcase, file_path)

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
            # Only record against a testcase that exists. A path nobody
            # registered has nothing to update, and trying threw a ValueError
            # that the route turned into a 500.
            if testcase:
                db.update_testcase_result(file_path, "unknown")
            return {"file_path": file_path, "status": "unknown",
                    "output": f"file not found: {file_path}"}
        cmd = [sys.executable, "-m", "pytest", file_path, "-v", "--no-header"]
        shell = False

    try:
        proc = subprocess.run(
            cmd, shell=shell, cwd=root, capture_output=True, text=True, timeout=timeout,
        )
        status = _classify(proc.returncode, cmd if isinstance(cmd, str) else " ".join(cmd))
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        status, output = "fail", f"timeout after {timeout}s"

    db.update_testcase_result(file_path, status)
    return {"file_path": file_path, "status": status, "output": output[-_MAX_OUTPUT_CHARS:]}
