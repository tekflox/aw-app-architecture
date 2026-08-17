"""architecture_app's mode-agnostic FastAPI sub-app (ADR Decision 2/6).

``build_routes()`` returns the SAME sub-app object used in both modes:

* **integrated** — ``plugin.py`` hands it to ``ctx.routes.register(...)``,
  which mounts it at ``/api/apps/architecture`` behind the runtime's
  ``IdentityGuard``. Apps never implement their own auth in this mode.
* **standalone** — ``__main__.py`` mounts it at the same prefix itself.

Every path here is RELATIVE (no ``/api/apps/architecture`` prefix) so client
code uses one path shape in both modes.

Ported from the monolith's ``src/api/routes/architecture.py``. Reads are the
same data the MCP tools serve — the UI is a view onto the catalog, not a
second source of truth, and curation writes (renaming/describing/linking) stay
on the MCP where they're LLM-managed.

Two deliberate exceptions, both inherited from the monolith and both still
right here:

* ``testcases/run`` — an execution action with a deterministic, objective
  outcome (pytest passed or it didn't), the same category as the MCP's
  ``run_component_tests``, not a curated edit. Fine to trigger from the play
  button.
* ``discovery/run`` — reads the filesystem and upserts Testcase rows, never
  clobbering curated fields. The exact operation the scheduled task runs, just
  triggerable on demand from the Rescan button instead of waiting for a tick.

**What's new in the port.** The monolith exposed six routes because its UI was
two disconnected panels reading a slice each. The merged window needs the rest
of the namespace to be reachable too (requirements, bugs, debt, connections,
the component tree), so the read surface is widened to cover what the tabs
show. ``/mcp`` is also new: the MCP moved from a stdio subprocess to this
in-process sub-app, because the store's session comes from ``ctx.db`` and a
subprocess has no route to it (see ``mcp_tools``).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import discovery
from . import jobs
from . import md_export as md
from . import mcp_tools
from . import provision as prov
from . import scan
from . import store as db
from .test_runner import run_testcase

log = logging.getLogger("aw_apps.architecture")


class _RunTestcaseBody(BaseModel):
    file_path: str
    #: Block until the run finishes. Off by default — see run_testcase_route.
    #: The CLI sets it, because it talks over loopback with no edge timeout and
    #: a script that has to poll for its own exit code is worse than one that
    #: waits.
    wait: bool = False


def build_routes(config: dict | None = None) -> FastAPI:
    """Mode-agnostic factory — called exactly once per mode.

    ``config`` is the app's ``ctx.config`` (``config_schema`` in the manifest).
    Threaded in rather than read globally so standalone mode can pass its own,
    and so a knob that isn't wired here is obvious at the call site.
    """
    config = config or {}
    app = FastAPI(title="architecture")

    # ---- catalog reads ----------------------------------------------------

    @app.get("/components")
    async def list_components(repo: str | None = None, layer: str | None = None):
        return await run_in_threadpool(db.list_components, repo, layer)

    @app.get("/components/{slug}")
    async def get_component(slug: str):
        c = await run_in_threadpool(db.full_component, slug)
        if not c:
            raise HTTPException(status_code=404, detail=f"component '{slug}' not found")
        return c

    @app.get("/matrix")
    async def get_matrix(component_slug: str | None = None):
        return await run_in_threadpool(db.get_traceability_matrix, component_slug)

    @app.get("/component-tests")
    async def get_component_tests(component_slug: str | None = None):
        return await run_in_threadpool(db.list_component_tests, component_slug)

    @app.get("/components/{slug}/requirements")
    async def get_component_requirements(slug: str):
        return await run_in_threadpool(db.get_component_requirements, slug)

    @app.get("/components/{slug}/connections")
    async def get_component_connections(slug: str):
        return await run_in_threadpool(db.get_component_connections, slug)

    @app.get("/requirements/{req_id}/bugs")
    async def get_requirement_bugs(req_id: str):
        return await run_in_threadpool(db.get_requirement_bug_history, req_id)

    @app.get("/requirements/{req_id}/impact")
    async def get_requirement_impact(req_id: str):
        return await run_in_threadpool(db.get_requirement_impact, req_id)

    @app.get("/debt")
    async def list_debt(component_slug: str | None = None, open_only: bool = True):
        return await run_in_threadpool(db.list_debt_notes, component_slug, open_only)

    @app.get("/flaky")
    async def list_flaky():
        return await run_in_threadpool(db.list_flaky_testcases)

    # ---- execute ----------------------------------------------------------

    @app.post("/testcases/run")
    async def run_testcase_route(body: _RunTestcaseBody):
        # Runs a real pytest subprocess — must not block the shared workspace
        # event loop for everyone else while it runs.
        #
        # NOTE: the tunnel edge cuts requests at ~30s, so a slow suite will
        # look like "502 workspace offline" to a browser coming in over the
        # tunnel even though the run completes server-side and records its
        # result. The Tests view treats a failed fetch as "unknown, refresh
        # to see the recorded status" rather than as a test failure.
        timeout = int(config.get("testcase_timeout_seconds") or 300)
        if not body.wait:
            # Default. Returns a job id at once so the browser is never holding
            # a request open across the tunnel's ~30s cut, and so a loop over a
            # component's tests can't fork one pytest per file with nothing
            # bounding it (jobs.MAX_CONCURRENT does).
            return jobs.start(body.file_path,
                              lambda fp: run_testcase(fp, timeout))
        try:
            return await run_in_threadpool(run_testcase, body.file_path, timeout)
        except ValueError as exc:
            # A path with no testcase row reached update_testcase_result, which
            # raises — and that surfaced as a bare 500. "You asked me to run
            # something I don't know about" is a client error with a readable
            # message, not a server fault; a 500 sends whoever hit it looking
            # for a crash that isn't there.
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/testcases/jobs/{job_id}")
    async def get_run_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no such run job {job_id!r}")
        return job

    @app.get("/testcases/jobs")
    async def list_run_jobs():
        # So a UI that lost its job id (a reload mid-run) finds the run again
        # instead of starting a second one.
        return jobs.snapshot()

    @app.post("/discovery/run")
    async def run_discovery_route():
        # Filesystem walk across every component's test_base_path — same work
        # as the scheduled task, just off the request thread.
        return await run_in_threadpool(discovery.discover_all)

    @app.post("/scan/run")
    async def run_scan_route():
        # Reads every aw-app.json in repos/ — filesystem + JSON only, no
        # network, no LLM. Off the request thread because it walks the tree.
        return await run_in_threadpool(scan.scan_workspace)

    @app.get("/provision/check")
    async def provision_check():
        # Reads only. This is what `doctor` calls: a suite that cannot collect
        # is silent degradation, and nothing else in the workspace notices it.
        return await run_in_threadpool(prov.check)

    @app.post("/provision/run")
    async def provision_run(body: dict | None = None):
        # pip against a cold cache is minutes, so this goes through the same
        # job registry the test runs use rather than holding the request.
        body = body or {}
        slug, force = body.get("component"), bool(body.get("force"))
        if not body.get("wait"):
            return jobs.start(slug or "*", lambda _fp: prov.provision(slug, force=force))
        return await run_in_threadpool(lambda: prov.provision(slug, force=force))

    @app.post("/docs/regenerate")
    async def regenerate_docs():
        return await run_in_threadpool(md.regenerate_all)

    # ---- MCP (in-process, aggregated by aw-mcp-gateway) -------------------

    @app.post("/mcp")
    async def mcp(request: Request):
        body = await request.json()
        response = await run_in_threadpool(mcp_tools.handle_request, body)
        # A JSON-RPC notification (e.g. notifications/initialized) has no
        # response; 204 rather than a null body, which some clients reject.
        if response is None:
            from fastapi import Response
            return Response(status_code=204)
        return response

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "app": "architecture"}

    return app
