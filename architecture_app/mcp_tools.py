"""MCP surface for the Architecture namespace — read + write + execute over the
structured architecture catalog (components, requirements/BDD, test
traceability, bug history, typed connections, MCP tools).

The whole architecture ecosystem is LLM-managed through these tools; the UI
(`ui/`) is a view onto the same data, not a second source of truth. Backing
store: this app's own `app__architecture__*` tables. Every write also
regenerates the deterministic Markdown under the workspace's `docs/architecture/`
(push-on-write, `md_export`), which the KB indexes.

Health is DERIVED, never stored — see `store`'s two VIEWs.

**What changed in the port.** The monolith ran this as a stdio MCP server
(`src/mcp/architecture.py`) that imported the DB module directly and owned its
own process. That shape can't work here: the store gets its session from
`ctx.db`, which only exists inside the workspace process, so a subprocess would
have no way to reach the tables. The JSON-RPC handling is unchanged; what's
gone is `main()`/the stdio loop, replaced by `POST /api/apps/architecture/mcp`
in `routes.py` (the same in-process HTTP-MCP shape the `kb` app uses, which is
what `aw-mcp-gateway` aggregates as `aw__architecture__*`).
"""

import json
import logging

from . import discovery
from . import scan
from . import md_export as md
from . import store as db
from .test_runner import run_testcase

_log = logging.getLogger(__name__)


def _tool_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _ok(obj):
    return _tool_result(json.dumps(obj, default=str, indent=2))


def _regen():
    """Push-on-write: regenerate all component MD files (deterministic, only
    changed files rewrite) + prune."""
    try:
        md.regenerate_all()
    except Exception as e:  # a write shouldn't fail because MD gen hiccuped
        _log.warning("architecture MD regen failed: %s", e)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_STR = {"type": "string"}
_STR_ARR = {"type": "array", "items": {"type": "string"}}

TOOLS = [
    # ---- read ----
    {"name": "list_components",
     "description": "List architecture components (optionally filtered by repo/layer). Returns slug, name, repo, layer, technologies, parent_slug, and DERIVED health.",
     "inputSchema": {"type": "object", "properties": {"repo": _STR, "layer": _STR}}},
    {"name": "get_component",
     "description": "Full detail for one component: fields, derived health, connections, MCP tools, and its requirements (each with derived health, linked tests, bug history).",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "get_component_requirements",
     "description": "The BDD requirements of a component, each with intended_status and DERIVED health.",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "get_requirement_tests",
     "description": "Test cases linked (N:N) to a requirement, with last_run_status/at.",
     "inputSchema": {"type": "object", "properties": {"req_id": _STR}, "required": ["req_id"]}},
    {"name": "get_requirement_bug_history",
     "description": "Chronological bug events for a requirement (open and resolved).",
     "inputSchema": {"type": "object", "properties": {"req_id": _STR}, "required": ["req_id"]}},
    {"name": "get_component_connections",
     "description": "Typed connections touching a component (as source or target).",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "get_component_tools",
     "description": "MCP tools a component exposes.",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "get_traceability_matrix",
     "description": "One row per requirement: what was asked (Given/When/Then), what implemented it (Kanban card / implemented_ref), how it's tested (linked test files + last result), how it's logged (logger_name), and derived health. Each row also carries root_component_slug/root_component_name (topmost ancestor via parent_slug) for UI grouping by the actual repo-level component. Omit component_slug for the whole catalog.",
     "inputSchema": {"type": "object", "properties": {"component_slug": _STR}}},
    {"name": "list_component_tests",
     "description": "Every test case directly owned by a component (set by run_test_discovery or create_testcase's component_slug), including ones not yet linked to any BDD requirement (`linked: false`). Omit component_slug for all components.",
     "inputSchema": {"type": "object", "properties": {"component_slug": _STR}}},
    {"name": "get_requirement_impact",
     "description": "Derived, not stored: what else might be affected if this requirement's component changes. Walks the connection graph one hop out and lists each neighbor component's own requirements. Check before marking a change 'implemented'.",
     "inputSchema": {"type": "object", "properties": {"req_id": _STR}, "required": ["req_id"]}},

    # ---- write: component lifecycle ----
    {"name": "create_component",
     "description": "Create or update a component (idempotent on slug — re-creating updates it). slug is the stable id driving the MD file path.",
     "inputSchema": {"type": "object", "properties": {
         "slug": _STR, "name": _STR, "parent_slug": _STR, "repo": _STR, "layer": _STR,
         "description": {**_STR, "description": "Prose summary of what this component is — improves KB semantic search."},
         "technologies": _STR_ARR, "docs_dir": _STR, "run_cmd": _STR, "test_cmd": _STR,
         "test_base_path": {**_STR, "description": "Repo-relative directory (or comma-separated / JSON-array list of directories) to scan for this component's tests — drives run_test_discovery."}},
         "required": ["slug", "name"]}},
    {"name": "update_component",
     "description": "Partial update of a component. Any subset of: name, parent_slug, repo, layer, description, technologies, docs_dir, run_cmd, test_cmd, test_base_path.",
     "inputSchema": {"type": "object", "properties": {
         "slug": _STR, "name": _STR, "parent_slug": _STR, "repo": _STR, "layer": _STR,
         "description": _STR, "technologies": _STR_ARR, "docs_dir": _STR, "run_cmd": _STR, "test_cmd": _STR,
         "test_base_path": {**_STR, "description": "Repo-relative directory to scan for this component's tests (e.g. 'repos/aw-meta-display/WatchUITests'), or a comma-separated / JSON-array list of directories so one component can own multiple dirs. Drives run_test_discovery."}},
         "required": ["slug"]}},
    {"name": "delete_component",
     "description": "Delete a component and (FK cascade) its requirements/connections/tools. Refuses if it still has sub-components unless cascade=true, which recursively deletes the subtree.",
     "inputSchema": {"type": "object", "properties": {"slug": _STR, "cascade": {"type": "boolean", "default": True}}, "required": ["slug"]}},

    # ---- write: requirements ----
    {"name": "create_requirement",
     "description": "Add a BDD requirement (Given/When/Then) to a component. intended_status is authored intent only (not_implemented|implemented) — health is derived.",
     "inputSchema": {"type": "object", "properties": {
         "component_slug": _STR, "title": _STR, "given": _STR, "when": _STR, "then": _STR,
         "intended_status": {"type": "string", "enum": ["not_implemented", "implemented"]}},
         "required": ["component_slug", "title", "given", "when", "then"]}},
    {"name": "update_requirement",
     "description": "Partial update of a requirement. Any subset of: title, given, when, then, intended_status, implemented_ref, logger_name.",
     "inputSchema": {"type": "object", "properties": {
         "id": _STR, "title": _STR, "given": _STR, "when": _STR, "then": _STR,
         "intended_status": {"type": "string", "enum": ["not_implemented", "implemented"]}, "implemented_ref": _STR,
         "logger_name": {**_STR, "description": "Python logger name (e.g. 'src.api.routes.notion_kanban') this rule's success/failure path logs through — feeds the traceability matrix's 'how is this logged' column."}},
         "required": ["id"]}},
    {"name": "set_requirement_status",
     "description": "Convenience: mark a requirement implemented/not_implemented, optionally recording the commit/PR ref.",
     "inputSchema": {"type": "object", "properties": {
         "id": _STR, "intended_status": {"type": "string", "enum": ["not_implemented", "implemented"]}, "implemented_ref": _STR},
         "required": ["id", "intended_status"]}},
    {"name": "delete_requirement",
     "description": "Delete a requirement (cascades its test links and bug events).",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},
    {"name": "link_requirement_kanban",
     "description": "Link a requirement to the Notion Kanban card that will implement it. Every requirement must have a card linked before set_requirement_status can mark it 'implemented'.",
     "inputSchema": {"type": "object", "properties": {
         "id": _STR, "kanban_page_id": _STR, "kanban_url": _STR},
         "required": ["id", "kanban_page_id"]}},
    {"name": "unlink_requirement_kanban",
     "description": "Remove a requirement's Kanban card link (e.g. the card was deleted/replaced).",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},

    # ---- write: test traceability ----
    {"name": "create_testcase",
     "description": "Register a test case (idempotent on file_path). kind: unit|integration|e2e. component_slug sets direct component ownership (shows up in Workspace > Tests even unlinked). Link it to requirements with link_requirement_test.",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["unit", "integration", "e2e"]}, "file_path": _STR,
         "test_plan_notes": _STR, "component_slug": _STR},
         "required": ["kind", "file_path"]}},
    {"name": "update_testcase_result",
     "description": "Record a test case's last run outcome (passing|fail|unknown). What a test-runner automation calls; flips derived health.",
     "inputSchema": {"type": "object", "properties": {
         "file_path": _STR, "last_run_status": {"type": "string", "enum": ["passing", "fail", "unknown"]}, "last_run_at": _STR},
         "required": ["file_path", "last_run_status"]}},
    {"name": "link_requirement_test",
     "description": "Add one N:N link between a requirement and a test case (one test can cover several requirements).",
     "inputSchema": {"type": "object", "properties": {"requirement_id": _STR, "testcase_id": _STR}, "required": ["requirement_id", "testcase_id"]}},
    {"name": "unlink_requirement_test",
     "description": "Remove a requirement↔test link.",
     "inputSchema": {"type": "object", "properties": {"requirement_id": _STR, "testcase_id": _STR}, "required": ["requirement_id", "testcase_id"]}},
    {"name": "delete_testcase",
     "description": "Delete a test case (cascades its requirement links).",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},
    {"name": "set_testcase_run_command",
     "description": "Register (or clear, passing null) how to actually RUN this test case when it isn't a plain `pytest <file_path>` — e.g. a Swift XCTest that needs a Python wrapper dispatching to a Remote Agent (Xcode Simulator on macbook-fred). The command runs from the repo root; exit 0 = passing, non-zero = fail, same convention pytest already uses, so the Workspace > Tests play button and run_component_tests both just work once this is set.",
     "inputSchema": {"type": "object", "properties": {
         "file_path": _STR, "run_command": _STR},
         "required": ["file_path"]}},
    {"name": "mark_testcase_flaky",
     "description": "Flaky-test policy: flag a test as intermittently failing instead of just re-running it until green. Set is_flaky=false to clear it (also clears flaky_note unless a new one is given).",
     "inputSchema": {"type": "object", "properties": {
         "file_path": _STR, "is_flaky": {"type": "boolean"}, "flaky_note": _STR},
         "required": ["file_path", "is_flaky"]}},
    {"name": "list_flaky_testcases",
     "description": "List every test case currently flagged flaky, with its note and last run result.",
     "inputSchema": {"type": "object", "properties": {}}},

    # ---- write: bug history ----
    {"name": "report_bug",
     "description": "Open a bug event against a requirement (a human-observed breakage). While open, the requirement's derived health is 'broken'. Don't use for test failures — those already derive 'broken' from update_testcase_result.",
     "inputSchema": {"type": "object", "properties": {"requirement_id": _STR, "description": _STR, "detected_at": _STR}, "required": ["requirement_id", "description"]}},
    {"name": "resolve_bug",
     "description": "Close an open bug event; health flips back automatically. Optionally record the fixing commit/PR ref.",
     "inputSchema": {"type": "object", "properties": {"bug_id": _STR, "resolved_ref": _STR, "resolved_at": _STR}, "required": ["bug_id"]}},

    # ---- write: technical debt ----
    {"name": "create_debt_note",
     "description": "Log a known piece of technical debt against a component (e.g. found during a periodic review) — not a user-observed bug, doesn't affect derived health. Optionally scope it to one requirement.",
     "inputSchema": {"type": "object", "properties": {
         "component_slug": _STR, "description": _STR, "requirement_id": _STR},
         "required": ["component_slug", "description"]}},
    {"name": "resolve_debt_note",
     "description": "Mark a technical debt note resolved, optionally recording the fixing commit/PR ref.",
     "inputSchema": {"type": "object", "properties": {
         "debt_id": _STR, "resolved_ref": _STR, "resolved_at": _STR},
         "required": ["debt_id"]}},
    {"name": "list_debt_notes",
     "description": "List technical debt notes, optionally scoped to one component. open_only defaults true.",
     "inputSchema": {"type": "object", "properties": {
         "component_slug": _STR, "open_only": {"type": "boolean", "default": True}}}},

    # ---- write: connections & tools ----
    {"name": "create_connection",
     "description": "Create/update a typed edge between two components (idempotent on from+to+kind). kind: http|db|stdio-mcp|queue|other.",
     "inputSchema": {"type": "object", "properties": {
         "from_slug": _STR, "to_slug": _STR, "kind": {"type": "string", "enum": ["http", "db", "stdio-mcp", "queue", "other"]}, "description": _STR},
         "required": ["from_slug", "to_slug", "kind"]}},
    {"name": "delete_connection",
     "description": "Delete a connection by id.",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},
    {"name": "create_mcp_tool",
     "description": "Register an MCP tool a component exposes (idempotent on component+name).",
     "inputSchema": {"type": "object", "properties": {"component_slug": _STR, "name": _STR, "description": _STR}, "required": ["component_slug", "name"]}},
    {"name": "delete_mcp_tool",
     "description": "Delete an MCP tool by id.",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},

    # ---- execute ----
    {"name": "run_component_tests",
     "description": "Run every test case linked to a component (subprocess pytest per file_path), record each result via update_testcase_result, then return the component's newly-derived health. Closes the loop into the health view.",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "scan_workspace",
     "description": "Derive the component catalog from the workspace's own aw-app.json manifests: one component per installed app, its connections (db / routes / gateway / declared app dependencies), its MCP tool rows, and its tests/ dir as test_base_path — plus aw-workspace and its src/ subpackages. Deterministic, no inference. Rows are written with edited_by='scan' and a component anyone has since edited is skipped, so this is safe to re-run on a schedule.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "run_test_discovery",
     "description": "Scan component test_base_path(s) for test files and upsert Testcase rows (component-owned, never clobbers run_command/is_flaky/last_run_status on already-known tests). Omit slug to scan every component with a test_base_path set. This is what the periodic 'Architecture Test Discovery' scheduled task calls.",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}}},

    # ---- sync / maintenance ----
    {"name": "sync_component",
     "description": "Force-regenerate one component's Markdown file now (writes already do this automatically; the KB reindexes the folder on its own cadence).",
     "inputSchema": {"type": "object", "properties": {"slug": _STR}, "required": ["slug"]}},
    {"name": "regenerate_architecture_docs",
     "description": "Regenerate all component Markdown files, prune orphans. Maintenance / drift-repair.",
     "inputSchema": {"type": "object", "properties": {}}},
]


# ---------------------------------------------------------------------------
# Execute tool
# ---------------------------------------------------------------------------

def _run_component_tests(slug: str) -> dict:
    tests = db.component_testcases(slug)
    if not tests:
        return _tool_result(
            f"No test cases linked to component '{slug}'. "
            f"Register tests (create_testcase) and link them (link_requirement_test) first."
        )
    results = []
    for t in tests:
        r = run_testcase(t["file_path"])
        results.append({
            "file_path": r["file_path"], "status": r["status"],
            "note": r["output"].strip()[-300:],
        })
    _regen()
    health = [c["health"] for c in db.list_components() if c["slug"] == slug]
    return _ok({
        "component": slug,
        "ran": len(results),
        "results": results,
        "component_health": health[0] if health else None,
    })


# Write tools that mutate the catalog → trigger MD regen after success.
_WRITE_TOOLS = {
    "create_component", "update_component", "delete_component",
    "create_requirement", "update_requirement", "set_requirement_status", "delete_requirement",
    "link_requirement_kanban", "unlink_requirement_kanban",
    "create_testcase", "update_testcase_result", "link_requirement_test",
    "unlink_requirement_test", "delete_testcase", "mark_testcase_flaky",
    "set_testcase_run_command", "run_test_discovery", "scan_workspace",
    "report_bug", "resolve_bug",
    "create_debt_note", "resolve_debt_note",
    "create_connection", "delete_connection", "create_mcp_tool", "delete_mcp_tool",
}


def _dispatch(tool: str, a: dict) -> dict:
    # ---- read ----
    if tool == "list_components":
        return _ok(db.list_components(a.get("repo"), a.get("layer")))
    if tool == "get_component":
        c = db.full_component(a["slug"])
        return _ok(c) if c else _tool_result(f"component '{a['slug']}' not found", is_error=True)
    if tool == "get_component_requirements":
        return _ok(db.get_component_requirements(a["slug"]))
    if tool == "get_requirement_tests":
        return _ok(db.get_requirement_tests(a["req_id"]))
    if tool == "get_requirement_bug_history":
        return _ok(db.get_requirement_bug_history(a["req_id"]))
    if tool == "get_component_connections":
        return _ok(db.get_component_connections(a["slug"]))
    if tool == "get_component_tools":
        return _ok(db.get_component_tools(a["slug"]))
    if tool == "get_traceability_matrix":
        return _ok(db.get_traceability_matrix(a.get("component_slug")))
    if tool == "get_requirement_impact":
        return _ok(db.get_requirement_impact(a["req_id"]))
    if tool == "list_flaky_testcases":
        return _ok(db.list_flaky_testcases())
    if tool == "list_debt_notes":
        return _ok(db.list_debt_notes(a.get("component_slug"), a.get("open_only", True)))
    if tool == "list_component_tests":
        return _ok(db.list_component_tests(a.get("component_slug")))

    # ---- write: component ----
    if tool == "create_component":
        # Only forward keys the caller actually sent. Passing a.get(...) for
        # every field turned "I didn't mention layer" into "set layer to NULL",
        # which made create_component on an existing slug a destructive
        # operation — see upsert_component's _UNSET sentinel.
        optional = ("parent_slug", "repo", "layer", "description", "technologies",
                    "docs_dir", "run_cmd", "test_cmd", "test_base_path")
        return _ok(db.upsert_component(
            a["slug"], a["name"],
            edited_by=a.get("edited_by", "generated"),
            **{k: a[k] for k in optional if k in a}))
    if tool == "update_component":
        fields = {k: v for k, v in a.items() if k != "slug"}
        return _ok(db.update_component(a["slug"], **fields))
    if tool == "delete_component":
        return _ok(db.delete_component(a["slug"], a.get("cascade", True)))

    # ---- write: requirement ----
    if tool == "create_requirement":
        return _ok(db.create_requirement(
            a["component_slug"], a["title"], a["given"], a["when"], a["then"],
            a.get("intended_status", "not_implemented")))
    if tool == "update_requirement":
        fields = {k: v for k, v in a.items() if k != "id"}
        return _ok(db.update_requirement(a["id"], **fields))
    if tool == "set_requirement_status":
        return _ok(db.set_requirement_status(a["id"], a["intended_status"], a.get("implemented_ref")))
    if tool == "delete_requirement":
        return _ok(db.delete_requirement(a["id"]))
    if tool == "link_requirement_kanban":
        return _ok(db.link_requirement_kanban(a["id"], a["kanban_page_id"], a.get("kanban_url")))
    if tool == "unlink_requirement_kanban":
        return _ok(db.unlink_requirement_kanban(a["id"]))

    # ---- write: test ----
    if tool == "create_testcase":
        return _ok(db.upsert_testcase(a["kind"], a["file_path"], a.get("test_plan_notes"), a.get("component_slug")))
    if tool == "update_testcase_result":
        return _ok(db.update_testcase_result(a["file_path"], a["last_run_status"], a.get("last_run_at")))
    if tool == "link_requirement_test":
        return _ok(db.link_requirement_test(a["requirement_id"], a["testcase_id"]))
    if tool == "unlink_requirement_test":
        return _ok(db.unlink_requirement_test(a["requirement_id"], a["testcase_id"]))
    if tool == "delete_testcase":
        return _ok(db.delete_testcase(a["id"]))
    if tool == "set_testcase_run_command":
        return _ok(db.set_testcase_run_command(a["file_path"], a.get("run_command")))
    if tool == "mark_testcase_flaky":
        return _ok(db.mark_testcase_flaky(a["file_path"], a["is_flaky"], a.get("flaky_note")))

    # ---- write: bug ----
    if tool == "report_bug":
        return _ok(db.report_bug(a["requirement_id"], a["description"], a.get("detected_at")))
    if tool == "resolve_bug":
        return _ok(db.resolve_bug(a["bug_id"], a.get("resolved_ref"), a.get("resolved_at")))

    # ---- write: technical debt ----
    if tool == "create_debt_note":
        return _ok(db.create_debt_note(a["component_slug"], a["description"], a.get("requirement_id")))
    if tool == "resolve_debt_note":
        return _ok(db.resolve_debt_note(a["debt_id"], a.get("resolved_ref"), a.get("resolved_at")))

    # ---- write: connections & tools ----
    if tool == "create_connection":
        return _ok(db.create_connection(a["from_slug"], a["to_slug"], a["kind"], a.get("description")))
    if tool == "delete_connection":
        return _ok(db.delete_connection(a["id"]))
    if tool == "create_mcp_tool":
        return _ok(db.upsert_mcp_tool(a["component_slug"], a["name"], a.get("description")))
    if tool == "delete_mcp_tool":
        return _ok(db.delete_mcp_tool(a["id"]))

    # ---- execute ----
    if tool == "run_component_tests":
        return _run_component_tests(a["slug"])
    if tool == "scan_workspace":
        return _ok(scan.scan_workspace())
    if tool == "run_test_discovery":
        slug = a.get("slug")
        result = [discovery.discover_component_tests(slug)] if slug else discovery.discover_all()
        return _ok(result)

    # ---- sync ----
    if tool == "sync_component":
        changed = md.sync_component(a["slug"])
        return _ok({"slug": a["slug"], "changed": changed})
    if tool == "regenerate_architecture_docs":
        return _ok(md.regenerate_all())

    return _tool_result(f"Unknown tool: {tool}", is_error=True)


def handle_request(request: dict):
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "aw-architecture", "version": "1.0.0"},
        }}

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = request.get("params", {})
        tool = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            result = _dispatch(tool, args)
            # Push-on-write MD regen for any successful catalog mutation.
            if tool in _WRITE_TOOLS and not result.get("isError"):
                _regen()
        except ValueError as e:
            result = _tool_result(str(e), is_error=True)
        except KeyError as e:
            result = _tool_result(f"Missing required argument: {e}", is_error=True)
        except Exception as e:
            result = _tool_result(f"Error: {e}", is_error=True)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


