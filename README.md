# aw-app-architecture

The Architecture namespace as a decoupled aw-workspace app: a structured
catalog of **components**, **BDD requirements**, **test traceability**, **bug
history**, **technical debt**, **typed connections** and **exposed MCP tools**
— with health always *derived*, never stored.

That last property is the point of the whole thing. `v_requirement_health` and
`v_component_health` are Postgres VIEWs, so a row cannot claim `implemented`
while a linked test is failing or a bug is open. There is no code path that
writes a health value, which means there is no code path that can lie about one.

## Where this came from

It was three disconnected pieces in the `agentic-workspace` monolith:

| Monolith | Here |
|---|---|
| `src/libs/architecture_db.py` | `architecture_app/store.py` |
| `src/libs/architecture_discovery.py` | `architecture_app/discovery.py` |
| `src/libs/architecture_test_runner.py` | `architecture_app/test_runner.py` |
| `src/libs/architecture_md.py` | `architecture_app/md_export.py` |
| `src/mcp/architecture.py` (stdio MCP) | `architecture_app/mcp_tools.py` + `POST /mcp` |
| `src/api/routes/architecture.py` | `architecture_app/routes.py` |
| Settings > Architecture (`ArchitectureTab.jsx`) | `ui/src/plugin.jsx`, left rail |
| Workspace > Tests (`TestsPanel.jsx`) | `ui/src/plugin.jsx`, Tests tab |

All of it had also been copied verbatim into `aw-backend` / `aw-workspace-ui`
during the monolith split. Those copies are deleted — the routes were never
mounted in this architecture, so the "Workspace > Tests" entry in the nav was
UI with no backend behind it.

## What changed in the port, and why

**Storage.** Tables moved from a shared `awserv` database onto this app's own
`app__architecture__*` tables in the workspace schema, via `ctx.db`. The prefix
is enforced by the `db:own-tables` capability; index and constraint names carry
it too, because several apps now share one schema and `idx_component_parent` is
not a name only this app could want.

**Two core additions were needed** (`aw-workspace/src/apps/db_tables.py`):

- `ctx.db.session(metadata)` — an ORM session on the workspace engine, with the
  metadata prefix-validated on the way through. Without it the port would have
  meant rewriting 1300 lines of ORM into SQL strings, against this codebase's
  own data-access standard.
- `ctx.db.execute_multi(sql, names)` — a statement spanning several of the app's
  tables. `execute()` validates exactly one table name, which makes a join (or a
  VIEW over several tables) inexpressible; the health VIEWs are exactly that.

**MCP.** Was a stdio server with its own process. It can't be: the store's
session comes from `ctx.db`, which exists only inside the workspace process. It
is now `POST /api/apps/architecture/mcp` in-process, which `aw-mcp-gateway`
aggregates as `aw__architecture__*`.

**Discovery scope.** The monolith resolved paths against its own single
checkout. Here the root is the workspace, so one scan covers components in
`repos/aw-workspace`, `repos/aw-app-tasks` and anywhere else at once — the
thing the catalog needs now that the code lives in many repos.

**KB hand-off.** The generator used to debounce writes ~45s and then POST
`/api/kb/build` on awserv. That route doesn't exist here; the KB is an app that
indexes mapped folders on its own cadence. Generated docs land in
`docs/architecture/`, which is already indexed. The timer, the API-key read and
the retry-on-lock branch are gone rather than kept as dead code aimed at a 404.

**The scheduled task.** "Architecture Test Discovery" was ported as-is and ran
`.venv/aw/bin/python -m src.libs.architecture_discovery` — an interpreter and a
module that don't exist in this workspace, which is why it sat disabled and
would have failed if enabled. It now runs `aw-workspace-cli architecture
discover`, which goes through the API to the process that holds the session.
Seeded **disabled**, like every contributed task.

## The window

One window, `core.window.body:architecture.main`. Components are the left rail
(a **tree** — `parent_slug` was always in the schema and the old flat table
dropped it); Tests / Requirements / Debt & Bugs / Detail are tabs on the right,
scoped to the selection. The old UI made you match slugs by eye across two
screens to answer "is this component healthy and which of its tests is red?" —
selection is that join, done once.

## Layout

```
architecture_app/
  store.py         8 tables + 2 derived-health VIEWs, ORM data access
  discovery.py     the test scanner
  test_runner.py   runs one testcase, records the result
  md_export.py     deterministic Markdown -> docs/architecture/
  mcp_tools.py     41 MCP tools (JSON-RPC handling, no transport)
  routes.py        REST + /mcp
  plugin.py        activate: bind -> ensure_schema -> register routes
commands/
  architecture.py  aw-workspace-cli architecture <discover|components|tests|run|regenerate-docs>
ui/src/plugin.jsx  the merged window + nav entry
tests/             port invariants (no Postgres needed)
```

## Tests

```bash
python3 -m pytest tests/ -q
```

They check what the port could plausibly have broken — that no table, FK, view
or index lost its prefix; that no raw DDL kept a bare table name; that the
statements survive the semicolon split `text()` binding requires; that the store
raises instead of silently reaching for another engine when unbound; and that no
module imports `src.*`. They are not a re-test of the data-access logic, which
came across unchanged.

## Running tests

The play button does not hold the request open — it starts a job and polls.
See [docs/running-tests.md](docs/running-tests.md) for the job contract, the
concurrency cap, and why job state is deliberately not persisted.

## Filesystem reach

Discovery walks `repos/` and `md_export` writes into each repo's
`docs/architecture/`. That is declared: the manifest asks for
**`fs:workspace-read`**, a capability added to the core catalog for exactly
this (workspace v0.1.64). Before it existed, the `$AW_WORKSPACE_REPOS` and
`$AW_WORKSPACE_SKILLS` volumes were ungated — any app could mount the user's
entire checkout tree without asking — and this app's reads were legal only
because a Tier-1 app runs in-process, so nothing was there to stop them. The
manifest is now a complete description of what this app touches.
