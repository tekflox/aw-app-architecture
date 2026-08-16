"""Workspace scanner — derives the component catalog from what the workspace
already declares about itself.

The monolith had no equivalent. Its 59 components, 41 connections and 90 MCP
tool rows were typed in one `create_component` call at a time, because nothing
in that codebase declared its own shape — the structure existed only in
someone's head and in the code. The decoupled architecture inverted that:
every app ships an `aw-app.json` stating its id, description, tier, category,
permissions, routes, MCP surface and app dependencies. That file is a
machine-readable architecture document, and this module reads it.

**What is derived here is only what a manifest states outright.** No
inference, no heuristics, no LLM. If a fact needs judgement, it is not in this
file — it belongs to an agent or a person, and the provenance rule below keeps
this scan from trampling their work.

Derived per app:
  component      one per aw-app.json (id, name, description, layer from tier)
  connections    db:own-tables      -> postgres      (kind=db)
                 contributes.routes -> aw-workspace  (kind=http)
                 contributes.mcp    -> mcp-gateway   (kind=stdio-mcp)
                 dependencies.apps  -> that app      (kind=other)
  mcp tools      one row per contributes.mcp.provides entry
  test_base_path the app's tests/ dir, when it has one

Plus the workspace itself: `aw-workspace` as a root component with its `src/`
subpackages as children, and two infrastructure components (`postgres`,
`mcp-gateway`) that exist so the connections above have somewhere to point.

Provenance
----------
Every row this module writes carries ``edited_by="scan"``. ``upsert_component``
only overwrites a component that is *still* marked that way, so the moment an
agent or a person edits one, this scan stops touching it — permanently. That
rule is the reason this can run on a schedule at all: without it, a scan every
30 minutes would erase every description anyone writes, once per tick.

Connections and MCP tool rows have no such flag and are plain upserts. They're
statements of fact taken from the manifest rather than prose, so re-asserting
them is harmless; the ``uq_connection_edge`` unique index makes it a no-op.
"""

from __future__ import annotations

import glob
import json
import logging
import os

from . import store as db
from .discovery import workspace_root

_log = logging.getLogger(__name__)

#: Components that exist to be the far end of a derived connection. They are
#: infrastructure this workspace runs on rather than anything in a repo, so
#: nothing else would ever create them.
_INFRA = [
    dict(slug="postgres", name="Postgres", layer="infrastructure",
         technologies=["postgresql"],
         description="Shared Postgres. Each workspace owns one schema; an app's "
                     "own tables live there under its app__<slug>__ prefix."),
    dict(slug="mcp-gateway", name="MCP Gateway", layer="infrastructure",
         technologies=["python"],
         description="Aggregates every installed app's MCP surface behind one "
                     "endpoint and prefixes tool names (aw__<app>__…)."),
]

#: `src/` subpackages worth being components in their own right. Deliberately a
#: list rather than "every directory": `tests` is not a component, and a scan
#: that invents components from directory names produces a catalog nobody
#: trusts.
_CORE_SUBPACKAGES = [
    ("workspace-api", "Workspace API", "api", "backend",
     "REST/WS surface the SPA and the local CLI talk to."),
    ("apps-runtime", "Apps runtime", "apps", "backend",
     "Loads apps, enforces the capability catalog, owns the ctx.* facades."),
    ("workspace-cli", "Workspace CLI", "cli", "cli",
     "aw-workspace-cli — commands auto-discovered from core and from each "
     "installed app's commands/ dir."),
    ("workspace-libs", "Workspace libs", "libs", "backend",
     "Shared helpers used across the API, the runtime and the CLI."),
]

#: manifest `tier` -> the catalog's `layer`. Two values, both explicit in the
#: manifest, so no guessing.
_TIER_LAYER = {"inprocess": "app", "container": "app-container"}


def _repo_dirs() -> list[str]:
    root = workspace_root()
    return sorted(glob.glob(os.path.join(root, "repos", "aw-app-*")))


def _plain_repo_dirs() -> list[str]:
    """Checked-out repos that are NOT apps — aw-backend, aw-workspace-ui,
    aw-mobile, agentic-workspace, and so on.

    They have no manifest, so almost nothing is derivable: no description, no
    layer, no connections. What IS derivable is that they exist and what
    they're written in — and "this repo is in the workspace and nobody has
    described it" is a fact worth showing rather than an omission. The
    monolith's catalog missed this class entirely, which is how it ended up
    pointing at `aw-meta-display` for two years after that repo was renamed to
    `aw-mobile`.

    Nothing is invented here: description and layer stay null, waiting for a
    person or an agent, and the provenance rule then protects whatever they
    write.
    """
    root = workspace_root()
    out = []
    repos_dir = os.path.join(root, "repos")
    if not os.path.isdir(repos_dir):
        return out
    for name in sorted(os.listdir(repos_dir)):
        path = os.path.join(repos_dir, name)
        if name.startswith("aw-app-") or not os.path.isdir(path):
            continue
        if not os.path.isdir(os.path.join(path, ".git")):
            continue  # a plain directory is not a component
        out.append(path)
    return out


#: extension -> technology, for repos with no manifest to ask. Only languages
#: whose presence is unambiguous from a file extension.
_EXT_TECH = {".py": "python", ".swift": "swift", ".go": "go", ".rs": "rust",
             ".ts": "typescript", ".tsx": "typescript", ".kt": "kotlin"}


def _detect_tech(repo_dir: str) -> list[str]:
    """Sample the top two levels rather than walking the whole tree — a repo
    with 40k files should not make the nightly scan expensive."""
    found = set()
    for depth in ("*", "*/*"):
        for path in glob.glob(os.path.join(repo_dir, depth)):
            ext = os.path.splitext(path)[1]
            if ext in _EXT_TECH:
                found.add(_EXT_TECH[ext])
    if os.path.isfile(os.path.join(repo_dir, "package.json")):
        found.add("node")
    if glob.glob(os.path.join(repo_dir, "*.xcodeproj")):
        found.add("xcode")
    return sorted(found)


def _plain_test_paths(repo_dir: str) -> str | None:
    """Conventional test directories, by name. A Swift `*UITests` dir counts:
    discovery recognises `*Tests.swift`, and those cases land as `unknown`
    until someone registers a run_command — which is correct, not a gap. There
    is no generic "run an XCTest" command, and recording `fail` because pytest
    could not collect a Swift file would be a false negative on a suite that
    may well be green."""
    root = workspace_root()
    candidates = [os.path.join(repo_dir, "tests"),
                  os.path.join(repo_dir, "src", "tests")]
    candidates += sorted(glob.glob(os.path.join(repo_dir, "*Tests")))
    candidates += sorted(glob.glob(os.path.join(repo_dir, "*UITests")))
    paths = [os.path.relpath(p, root) for p in candidates if os.path.isdir(p)]
    return ",".join(paths) or None


def _read_manifest(repo_dir: str) -> dict | None:
    path = os.path.join(repo_dir, "aw-app.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _log.warning("scan: skipping %s — %s", path, exc)
        return None


def _tech(manifest: dict, repo_dir: str) -> list[str]:
    """Only what's stated or unambiguously present on disk."""
    tech = []
    if (manifest.get("runtime") or {}).get("python"):
        tech.append("python")
    if os.path.isdir(os.path.join(repo_dir, "ui")):
        tech.append("react")
    if manifest.get("tier") == "container":
        tech.append("docker")
    return tech


def _test_base_path(repo_dir: str) -> str | None:
    root = workspace_root()
    tests = os.path.join(repo_dir, "tests")
    if os.path.isdir(tests):
        return os.path.relpath(tests, root)
    return None


def scan_workspace() -> dict:
    """Derive the catalog from the workspace's own manifests. Idempotent.

    Returns a summary of what was written and — importantly — what was left
    alone because someone had curated it.
    """
    root = workspace_root()
    created_components = skipped_curated = connections = tools = 0

    curated = {
        c["slug"] for c in db.list_components()
        if c.get("edited_by") and c["edited_by"] != db.SCAN_PROVENANCE
    }

    def put(slug: str, **kw) -> bool:
        """Upsert as scan-owned. False when a curated row refused the write."""
        nonlocal skipped_curated
        if slug in curated:
            skipped_curated += 1
            return False
        db.upsert_component(slug=slug, edited_by=db.SCAN_PROVENANCE, **kw)
        return True

    # ---- infrastructure + the workspace itself -----------------------------
    for infra in _INFRA:
        if put(**infra):
            created_components += 1

    if put(slug="aw-workspace", name="aw-workspace", repo="aw-workspace",
           layer="platform",
           description="The decoupled workspace host: app runtime, capability "
                       "system, CLI, REST/WS API.",
           technologies=["python", "fastapi", "sqlalchemy"]):
        created_components += 1

    for slug, name, pkg, layer, desc in _CORE_SUBPACKAGES:
        src = os.path.join(root, "src", pkg)
        if not os.path.isdir(src):
            continue
        tests = os.path.join(root, "src", "tests", "unit", pkg)
        integration = os.path.join(root, "src", "tests", "integration", pkg)
        paths = [os.path.relpath(p, root) for p in (tests, integration)
                 if os.path.isdir(p)]
        if put(slug=slug, name=name, parent_slug="aw-workspace",
               repo="aw-workspace", layer=layer, description=desc,
               technologies=["python"],
               test_base_path=",".join(paths) or None):
            created_components += 1

    # ---- repos that aren't apps -------------------------------------------
    for repo_dir in _plain_repo_dirs():
        name = os.path.basename(repo_dir)
        if put(slug=name, name=name, repo=name,
               # description and layer stay null on purpose: nothing in a bare
               # checkout states them, and a placeholder would be a guess that
               # then looks like curated fact.
               technologies=_detect_tech(repo_dir),
               test_base_path=_plain_test_paths(repo_dir)):
            created_components += 1

    # ---- pass 1: every component, before any edge -------------------------
    #
    # Two passes, not one. `create_connection` resolves both endpoints by slug
    # and raises if either is missing, so a single interleaved pass drops every
    # edge that points *forward* — an app declaring a dependency on one the
    # loop hasn't reached yet. That made the first run land 44 edges and the
    # second 49: the scan converged, but only by being run twice, which is the
    # kind of "works if you do it again" that hides in a nightly job.
    pending: list[tuple[str, dict, str]] = []
    for repo_dir in _repo_dirs():
        manifest = _read_manifest(repo_dir)
        if not manifest or not manifest.get("id"):
            continue
        slug = f"aw-app-{manifest['id']}"
        if put(slug=slug, name=manifest.get("name") or manifest["id"],
               repo=os.path.basename(repo_dir),
               layer=_TIER_LAYER.get(manifest.get("tier"), "app"),
               description=manifest.get("description"),
               technologies=_tech(manifest, repo_dir),
               test_base_path=_test_base_path(repo_dir)):
            created_components += 1
        # Edges and tools are derived even for a curated component: the
        # provenance rule protects prose someone wrote, not the topology, which
        # is a fact restated from the manifest either way.
        pending.append((slug, manifest, repo_dir))

    # ---- pass 2: edges + tool rows, with every endpoint now present --------
    for slug, manifest, _repo_dir in pending:
        contributes = manifest.get("contributes") or {}
        perms = manifest.get("permissions") or []
        edges = []
        if "db:own-tables" in perms:
            edges.append(("postgres", "db", "app-owned tables in the workspace schema"))
        if contributes.get("routes"):
            prefix = (contributes["routes"][0] or {}).get("prefix", "")
            edges.append(("aw-workspace", "http", f"routes mounted at {prefix}"))
        if (contributes.get("mcp") or {}).get("provides"):
            edges.append(("mcp-gateway", "stdio-mcp", "MCP surface aggregated by the gateway"))
        for dep in (manifest.get("dependencies") or {}).get("apps") or []:
            if dep.get("id"):
                edges.append((f"aw-app-{dep['id']}", "other",
                              (dep.get("reason") or "").split(".")[0] or "declared dependency"))

        for to_slug, kind, desc in edges:
            try:
                db.create_connection(slug, to_slug, kind, desc)
                connections += 1
            except Exception as exc:
                # A dependency on an app that isn't checked out here still has
                # no component to point at, and that's legitimate — skip the
                # edge, keep the component. Refusing the whole scan over one
                # missing target would make the catalog hostage to which repos
                # happen to be cloned.
                _log.debug("scan: connection %s -> %s skipped: %s", slug, to_slug, exc)

        for tool in (contributes.get("mcp") or {}).get("provides") or []:
            try:
                db.upsert_mcp_tool(slug, tool)
                tools += 1
            except Exception as exc:
                _log.debug("scan: mcp tool %s on %s skipped: %s", tool, slug, exc)

    summary = {
        "components": created_components,
        "connections": connections,
        "mcp_tools": tools,
        "skipped_curated": skipped_curated,
    }
    _log.info("architecture scan: %s", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(scan_workspace(), indent=2))
