"""Architecture namespace — deterministic Markdown generator + KB hand-off.

Renders the structured `store` tables into one `.md` file per component under
the workspace's `docs/architecture/` tree, which the `kb` app already indexes
as a mapped folder — so a generated file becomes searchable without this app
knowing anything about how the KB works.

Design guarantees:
* **Byte-deterministic** — same rows in ⇒ identical bytes ⇒ stable checksum ⇒
  the checksum-skipping KB build re-embeds nothing that didn't change.
* **Push-on-write** — ``sync_component(slug)`` regenerates one file immediately
  after a write.
* **Generator owns deletion** — ``regenerate_all()`` writes the current set and
  prunes any generated ``.md`` no longer backed by a row.

**What changed in the port.** The monolith debounced writes (~45s) and then
POSTed ``/api/kb/build`` on awserv to force a re-embed. That route does not
exist in this architecture — the KB is the `kb` app, and it indexes mapped
folders on its own cadence (see `kb-indexes-workspace-mapped-folders`). The
debounce timer, the api-key read and the retry-on-lock branch all existed
solely to drive that one call, so they are gone rather than kept as dead code
pointing at a 404. Files land in an indexed folder; the KB picks them up.
The ``trigger_build`` parameter is kept on the public functions so callers
(and the MCP tool signatures) don't change, but it no longer does anything —
documented on each function rather than silently ignored.
"""

from __future__ import annotations

import hashlib
import logging
import os

from . import store as db

_log = logging.getLogger(__name__)


def workspace_root() -> str:
    """Resolved per call, not captured at import: the CLI, the server and app
    containers run from different cwds."""
    return os.environ.get("AW_WORKSPACE_CONTAINER_DIR", "/opt/aw-workspace")


def arch_dir() -> str:
    """Where GENERIC component docs go — the workspace's own `docs/` tree,
    a mapped folder the KB indexes."""
    return os.path.join(workspace_root(), "docs", "architecture")


def dir_for_component(component: dict | None) -> str:
    """A component's doc belongs to whichever repo the component lives in.

    An app's architecture doc in `repos/<app>/docs/architecture/` is committed
    with that app, travels with it, and survives an uninstall/reinstall —
    whereas the same file in the workspace's own tree is orphaned the moment
    the app is removed, and then describes something that isn't there.

    Generic components (aw-workspace itself, its subpackages, postgres,
    mcp-gateway) have no repo of their own and stay in the workspace's docs/.
    A repo that isn't checked out here falls back there too: a doc in a
    slightly odd place beats no doc.
    """
    repo = (component or {}).get("repo")
    if not repo or repo == "aw-workspace":
        return arch_dir()
    repo_dir = os.path.join(workspace_root(), "repos", repo)
    if not os.path.isdir(repo_dir):
        return arch_dir()
    return os.path.join(repo_dir, "docs", "architecture")


# ---------------------------------------------------------------------------
# Rendering (byte-deterministic)
# ---------------------------------------------------------------------------

def _body(c: dict) -> str:
    """Render the Markdown body (everything after the frontmatter) for one
    component dict as returned by ``architecture_db.full_component``."""
    lines: list[str] = []
    lines.append(f"# {c['name']}")
    lines.append("")
    lines.append(f"- **repo**: {c.get('repo') or '—'}")
    lines.append(f"- **layer**: {c.get('layer') or '—'}")
    if c.get("parent_slug"):
        lines.append(f"- **parent**: {c['parent_slug']}")
    techs = c.get("technologies") or []
    lines.append(f"- **technologies**: {', '.join(techs) or '—'}")
    lines.append(f"- **health** (derived): {c.get('health') or 'planned'}")
    if c.get("description"):
        lines.append("")
        lines.append(c["description"].strip())

    lines.append("")
    lines.append("## Connections")
    if c["connections"]:
        for conn in c["connections"]:
            desc = f" — {conn['description']}" if conn.get("description") else ""
            lines.append(f"- `{conn['kind']}` → **{conn['to_slug']}**{desc}")
    else:
        lines.append("_none_")

    lines.append("")
    lines.append("## MCP tools")
    if c["tools"]:
        for t in c["tools"]:
            desc = f" — {t['description']}" if t.get("description") else ""
            lines.append(f"- `{t['name']}`{desc}")
    else:
        lines.append("_none exposed_")

    lines.append("")
    lines.append("## Requirements")
    if not c["requirements"]:
        lines.append("_none documented_")
    for r in c["requirements"]:
        lines.append(f"### {r['title']}")
        lines.append(f"- Given {r['gherkin_given']}")
        lines.append(f"- When {r['gherkin_when']}")
        lines.append(f"- Then {r['gherkin_then']}")
        lines.append(
            f"- intended_status: `{r['intended_status']}` · "
            f"derived health: `{r.get('health') or 'not_implemented'}`"
        )
        if r["tests"]:
            joined = ", ".join(
                f"`{t['file_path']}` ({t['last_run_status'] or 'unknown'})"
                for t in r["tests"]
            )
            lines.append(f"- tests: {joined}")
        else:
            lines.append("- tests: _none linked_")
        for b in r["bugs"]:
            date = b["detected_at"].strftime("%Y-%m-%d") if b.get("detected_at") else "?"
            state = "resolved" if b.get("resolved_at") else "open"
            lines.append(f"  - bug {date}: {b['description']} ({state})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_component_md(slug: str) -> str | None:
    """Full deterministic file contents (frontmatter + body) for one component,
    or None if the slug has no row."""
    c = db.full_component(slug)
    if not c:
        return None
    body = _body(c)
    checksum = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    front = [
        "---",
        "repo: architecture",
        f"path: docs/architecture/{slug}.md",
        "source: generated",
        "edited: false",
        f"checksum: {checksum}",
        "---",
        "",
    ]
    return "\n".join(front) + body


# ---------------------------------------------------------------------------
# Writing / pruning
# ---------------------------------------------------------------------------

def _file_for(slug: str, component: dict | None = None) -> str:
    if component is None:
        component = db.get_component(slug)
    return os.path.join(dir_for_component(component), f"{slug}.md")


def _write_if_changed(path: str, content: str) -> bool:
    if os.path.isfile(path):
        with open(path) as f:
            if f.read() == content:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return True


def sync_component(slug: str, trigger_build: bool = True) -> bool:
    """Push-on-write: (re)generate one component's MD file immediately. If the
    slug no longer exists, remove its file. Returns True if the file changed.

    ``trigger_build`` is accepted and ignored — see the module docstring; the
    KB indexes this directory on its own cadence."""
    content = render_component_md(slug)
    path = _file_for(slug)
    if content is None:
        changed = os.path.isfile(path)
        if changed:
            os.remove(path)
    else:
        changed = _write_if_changed(path, content)
    return changed


def regenerate_all(trigger_build: bool = True) -> dict:
    """Write the current set of component files and prune any generated ``.md``
    with no backing row. Idempotent and deterministic.

    ``trigger_build`` is accepted and ignored — see the module docstring.

    Docs are spread across repos now, so pruning has to sweep every directory
    it ever wrote to, not just the workspace's. It only ever deletes a file
    whose frontmatter says ``source: generated`` — a hand-written ADR sitting
    in the same folder is not this function's to remove, and deleting one would
    be unrecoverable from here."""
    slugs = set(db.all_component_slugs())
    components = {c["slug"]: c for c in db.list_components()}

    changed = 0
    dirs = {arch_dir()}
    for slug in sorted(slugs):
        target_dir = dir_for_component(components.get(slug))
        dirs.add(target_dir)
        os.makedirs(target_dir, exist_ok=True)
        content = render_component_md(slug)
        if content is None:
            continue
        if _write_if_changed(os.path.join(target_dir, f"{slug}.md"), content):
            changed += 1

    pruned = 0
    for d in sorted(dirs):
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".md") or fname[:-3] in slugs:
                continue
            path = os.path.join(d, fname)
            try:
                with open(path) as f:
                    head = f.read(400)
            except OSError:
                continue
            if "source: generated" not in head:
                continue     # someone wrote this by hand; not ours to delete
            os.remove(path)
            pruned += 1

    return {"changed": changed, "pruned": pruned}


