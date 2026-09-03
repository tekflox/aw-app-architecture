"""aw-workspace-cli architecture — this app's own CLI command.

Auto-discovered by aw-workspace-cli from this app's installed directory
(``<apps_root>/architecture/commands/``, since this file lives at
``commands/`` in this repo's root — see aw-workspace's ``src/cli/discovery.py``).

Everything here is a thin client over ``/api/apps/architecture/*``, using the
workspace API key ``src.cli.local_client`` already knows how to present. The
work itself has to happen in the workspace process: the store's session comes
from ``ctx.db``, which exists only there, so a CLI that tried to scan or run
tests in its own process would have no database to write to.

This is also what the seeded "Architecture Test Discovery" task runs. The
monolith's version of that task shelled straight into
``.venv/aw/bin/python -m src.libs.architecture_discovery``; ported as-is it
pointed at an interpreter and a module that don't exist in this workspace, so
the task sat disabled. Going through the CLI (which goes through the API,
which reaches the process holding the session) is what makes it actually run.

Usage:
    aw-workspace-cli architecture scan                  # derive components from manifests
    aw-workspace-cli architecture discover              # find test files per component
    aw-workspace-cli architecture components            # list, with derived health
    aw-workspace-cli architecture tests [<slug>]        # traceability rows
    aw-workspace-cli architecture run <file_path>       # run one testcase
    aw-workspace-cli architecture provision [<slug>]    # install declared test deps
    aw-workspace-cli architecture provision --check     # report, install nothing
    aw-workspace-cli architecture provision --if-stale  # only (re)install what changed
    aw-workspace-cli architecture autoprovision         # scan, then provision --if-stale
    aw-workspace-cli architecture regenerate-docs       # rewrite docs/architecture/
"""
from __future__ import annotations

import json
import sys

COMMAND = "architecture"
DESCRIPTION = "Architecture namespace — components, tests, discovery, docs"

_BASE = "/api/apps/architecture"


def _usage() -> int:
    print(__doc__.split("Usage:")[1].strip())
    return 2


def run(args: list[str] | None = None) -> int:
    args = list(args or [])
    if not args or args[0] in ("-h", "--help"):
        return _usage()

    from src.cli import local_client

    sub, rest = args[0], args[1:]

    if sub == "provision":
        check = "--check" in rest
        if check:
            status, body = local_client.request("GET", f"{_BASE}/provision/check")
            if status != 200:
                print(f"provision check failed: HTTP {status} {body}", file=sys.stderr)
                return 1
            for row in body.get("components", []):
                if not row["provisioned"]:
                    state = "MISSING"
                elif row.get("stale"):
                    state = "STALE"
                else:
                    state = "ok"
                bad = row.get("missing_requirement_files") or []
                print(f"{state:8} {row['component']:28} {', '.join(row['requirement_files'])}"
                      + (f"   [declared but absent: {', '.join(bad)}]" if bad else ""))
            pending = body.get("pending") or []
            if pending:
                print(f"\n{len(pending)} component(s) not provisioned: {', '.join(pending)}")
            return 0 if body.get("ok") else 1
        # NOT wait=True. A cold pip over 152 pinned packages is minutes, and
        # the edge cuts a request at ~30s — the first run of this came back as
        # "502 workspace offline" while the install carried on server-side, so
        # the CLI reported failure about something that was working. Start the
        # job, then poll; each poll is a normal short request.
        payload = {"force": "--force" in rest, "only_stale": "--if-stale" in rest}
        slug = next((a for a in rest if not a.startswith("--")), None)
        if slug:
            payload["component"] = slug
        status, job = local_client.request("POST", f"{_BASE}/provision/run", payload)
        if status != 200:
            print(f"provision failed: HTTP {status} {job}", file=sys.stderr)
            return 1
        import time
        print(f"provisioning ({job.get('id')}) — installing, this takes minutes…")
        while True:
            status, j = local_client.request("GET", f"{_BASE}/testcases/jobs/{job['id']}")
            if status != 200:
                print(f"lost track of the job: HTTP {status} {j}", file=sys.stderr)
                return 1
            if j.get("status") == "done":
                break
            time.sleep(5)
        if j.get("error"):
            print(f"provision failed: {j['error']}", file=sys.stderr)
            return 1
        body = j.get("result") or {}
        for row in body.get("provisioned", []):
            if row.get("ok"):
                print(f"ok     {row['component']:28} {', '.join(row.get('files') or [])}")
            else:
                print(f"FAILED {row['component']:28} {row.get('error','')[:200]}", file=sys.stderr)
        if not body.get("ok") and body.get("error"):
            # The unmatched-slug case: `provisioned` is empty, so without this
            # the CLI prints nothing and just exits non-zero — a failure with
            # no visible reason.
            print(f"provision failed: {body['error']}", file=sys.stderr)
        return 0 if body.get("ok") else 1

    if sub == "autoprovision":
        # scan, then provision what's stale — one command, one process, so a
        # scheduled task doesn't depend on the runner supporting a shell "&&".
        status, body = local_client.request("POST", f"{_BASE}/scan/run", {})
        if status != 200:
            print(f"scan failed: HTTP {status} {body}", file=sys.stderr)
            return 1
        print(f"scan: components {body.get('components')}  "
              f"connections {body.get('connections')}  "
              f"mcp tools {body.get('mcp_tools')}")

        status, job = local_client.request(
            "POST", f"{_BASE}/provision/run", {"only_stale": True})
        if status != 200:
            print(f"provision failed: HTTP {status} {job}", file=sys.stderr)
            return 1
        import time
        print(f"provisioning ({job.get('id')}) — installing what's stale…")
        while True:
            status, j = local_client.request("GET", f"{_BASE}/testcases/jobs/{job['id']}")
            if status != 200:
                print(f"lost track of the job: HTTP {status} {j}", file=sys.stderr)
                return 1
            if j.get("status") == "done":
                break
            time.sleep(5)
        if j.get("error"):
            print(f"provision failed: {j['error']}", file=sys.stderr)
            return 1
        body = j.get("result") or {}
        for row in body.get("provisioned", []):
            if row.get("ok"):
                print(f"ok     {row['component']:28} {', '.join(row.get('files') or [])}")
            else:
                print(f"FAILED {row['component']:28} {row.get('error','')[:200]}", file=sys.stderr)
        if not body.get("provisioned"):
            print("autoprovision: nothing stale, no-op")
        return 0 if body.get("ok") else 1

    if sub == "scan":
        status, body = local_client.request("POST", f"{_BASE}/scan/run", {})
        if status != 200:
            print(f"scan failed: HTTP {status} {body}", file=sys.stderr)
            return 1
        print(f"components {body.get('components')}  "
              f"connections {body.get('connections')}  "
              f"mcp tools {body.get('mcp_tools')}")
        skipped = body.get("skipped_curated") or 0
        if skipped:
            # Not a warning — this is the provenance rule working. Reported
            # because a scan that silently declines to write half the catalog
            # would otherwise look like a scan that found nothing.
            print(f"{skipped} component(s) left alone (curated — scan does not overwrite)")
        return 0

    if sub == "discover":
        status, body = local_client.request("POST", f"{_BASE}/discovery/run", {})
        if status != 200:
            print(f"discovery failed: HTTP {status} {body}", file=sys.stderr)
            return 1
        total = sum(len(r.get("found", [])) for r in body)
        errored = 0
        for r in body:
            if r.get("error"):
                errored += 1
                print(f"  {r['component_slug']}: ERROR — {r['error']}")
            elif not r.get("skipped_no_path"):
                print(f"  {r['component_slug']} ({r.get('scanned_path')}): "
                      f"{len(r.get('found', []))} test file(s)")
        print(f"Architecture test discovery: {len(body)} component(s) scanned, "
              f"{total} test file(s) total.")
        # Non-zero when a component's test_base_path points somewhere that no
        # longer exists — that's the condition the seeded task's
        # notify_exit_codes watches for. A scan that finds nothing because
        # nothing is registered yet is NOT an error.
        return 1 if errored else 0

    if sub == "components":
        status, body = local_client.request("GET", f"{_BASE}/components")
        if status != 200:
            print(f"HTTP {status} {body}", file=sys.stderr)
            return 1
        for c in body:
            print(f"{c.get('health', 'unknown'):<16} {c['slug']:<32} "
                  f"{c.get('repo') or '—'}")
        return 0

    if sub == "tests":
        path = f"{_BASE}/component-tests"
        if rest:
            path += f"?component_slug={rest[0]}"
        status, body = local_client.request("GET", path)
        if status != 200:
            print(f"HTTP {status} {body}", file=sys.stderr)
            return 1
        print(json.dumps(body, indent=2, default=str))
        return 0

    if sub == "run":
        if not rest:
            print("run needs a file_path", file=sys.stderr)
            return 2
        status, body = local_client.request(
            "POST", f"{_BASE}/testcases/run", {"file_path": rest[0], "wait": True})
        if status != 200:
            print(f"HTTP {status} {body}", file=sys.stderr)
            return 1
        print(f"{body.get('status')}  {body.get('file_path')}")
        if body.get("output"):
            print(body["output"])
        return 0 if body.get("status") == "passing" else 1

    if sub == "regenerate-docs":
        status, body = local_client.request("POST", f"{_BASE}/docs/regenerate", {})
        if status != 200:
            print(f"HTTP {status} {body}", file=sys.stderr)
            return 1
        print(f"changed={body.get('changed')} pruned={body.get('pruned')}")
        return 0

    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return _usage()
