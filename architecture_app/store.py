"""Architecture namespace — app-owned tables + data access (SQLAlchemy ORM).

Structured backing store for the ``architecture`` namespace: components
(self-referencing), requirements (BDD Given/When/Then), test traceability
(N:N), bug history, typed connections between components, and the MCP tools a
component exposes.

Health is always **DERIVED** through the ``v_requirement_health`` /
``v_component_health`` Postgres VIEWs — a "broken" state is never stored, so a
row can't claim "implemented" while a linked test fails or an open bug exists.
The views are mapped as read-only ORM classes (queried, never written); table
health is never cached in Python.

Ported from the monolith's ``src/libs/architecture_db.py``. Two things changed
and nothing else did:

* **Where the tables live.** Every ``__tablename__`` (and the two VIEWs, the
  FK targets and the index names) carries the ``app__architecture__`` prefix
  the ``db:own-tables`` capability enforces, and they land in *this
  workspace's* schema rather than a shared ``awserv`` database. The prefix is
  also what keeps index names from colliding with another app's in the one
  schema they now share.
* **How the session is obtained.** ``ctx.db.session(Base.metadata)`` instead of
  reaching into ``src.api.pg_db`` — the app has no business importing core
  modules, and the facade prefix-validates the metadata on the way through, so
  the ORM path is gated exactly like the SQL one.

Data-access stays ORM-only — no raw SQL strings for reads/writes. The only raw
SQL is the idempotent schema bootstrap (``ensure_schema``): additive migrations
and the two derived-health VIEW definitions, which have no clean declarative
equivalent, and which go through ``ctx.db.execute_multi`` because they span
several of this app's tables at once.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Session, aliased, mapped_column

_log = logging.getLogger(__name__)

TABLE_PREFIX = "app__architecture__"

#: ``Component.edited_by`` value that marks a row as machine-derived and
#: therefore still safe for the scan to overwrite. Any other value means a
#: person or an agent has taken ownership of that row — see
#: ``upsert_component``.
SCAN_PROVENANCE = "scan"

#: Sentinel for "this caller has no opinion about that column".
#: ``upsert_component`` needs to tell an explicit ``None`` (clear the field)
#: apart from an omitted argument (leave whatever is there). Without it every
#: upsert wrote NULL into every column it wasn't given — so a `test_cmd` set by
#: hand survived until the nightly scan, which has no opinion about test_cmd
#: and silently blanked it.
_UNSET = object()

#: Every table/VIEW this module owns, in the order ``execute_multi`` needs them
#: declared. Kept next to the models so adding a model without registering it
#: here fails loudly at bootstrap instead of silently skipping its migrations.
OWNED = [
    TABLE_PREFIX + n for n in (
        "component", "requirement", "testcase", "req_testcase", "bugevent",
        "debtnote", "connection", "mcptool",
        "v_requirement_health", "v_component_health",
    )
]

# ---------------------------------------------------------------------------
# Session — supplied by the app runtime (ctx.db), never imported from core
# ---------------------------------------------------------------------------

_ctx = None


def bind(ctx) -> None:
    """Hand this module the app context. Called once from ``plugin.activate``.

    Everything below goes through ``ctx.db``; without this the module raises
    rather than silently falling back to some other engine — a store that
    quietly wrote to the wrong database is exactly the class of silent
    degradation this workspace keeps getting bitten by.

    Also checks up front that this workspace's ``ctx.db`` actually has the two
    methods this app was built against. They landed in aw-workspace on
    2026-08-15 (``session()`` and ``execute_multi()`` in ``src/apps/
    db_tables.py``), and an ``aw-app.json`` has no way to declare a minimum
    core version — ``dependencies`` only covers other apps. So on an older
    workspace (a rollback, or a BYOD box on a stale image) the app installs
    fine and then dies with ``AttributeError: 'DbFacade' object has no
    attribute 'session'`` somewhere deep in a request. Naming the requirement
    here turns that into one legible line in the activation log.
    """
    db = getattr(ctx, "db", None)
    missing = [m for m in ("session", "execute_multi") if not callable(getattr(db, m, None))]
    if missing:
        raise RuntimeError(
            f"this workspace's ctx.db is missing {', '.join(missing)} — "
            f"aw-app-architecture needs the multi-table db facade added to "
            f"aw-workspace on 2026-08-15 (src/apps/db_tables.py). Update the "
            f"workspace, or install an older version of this app."
        )
    global _ctx
    _ctx = ctx


def get_session() -> Session:
    """A fresh ORM ``Session`` on this workspace's engine. Prefer the
    context-manager form (``with get_session() as s: ... s.commit()``)."""
    if _ctx is None:
        raise RuntimeError(
            "architecture store not bound — plugin.activate() must call "
            "store.bind(ctx) before any data access")
    return _ctx.db.session(Base.metadata)


def get_engine():
    """The Engine behind ``get_session()`` — needed for ``create_all``."""
    with get_session() as s:
        return s.get_bind()


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class ViewBase(DeclarativeBase):
    """Separate declarative base for the read-only health VIEWs so they are
    never touched by ``create_all`` (the VIEWs are defined via raw SQL)."""


_UUID = PGUUID(as_uuid=True)
_UUID_PK = dict(primary_key=True, server_default=text("gen_random_uuid()"))
_NOW = dict(nullable=False, server_default=text("now()"))


class Component(Base):
    __tablename__ = "app__architecture__component"
    id = mapped_column(_UUID, **_UUID_PK)
    slug = mapped_column(Text, nullable=False, unique=True)
    name = mapped_column(Text, nullable=False)
    parent_id = mapped_column(_UUID, ForeignKey("app__architecture__component.id", ondelete="SET NULL"))
    repo = mapped_column(Text)
    layer = mapped_column(Text)
    description = mapped_column(Text)
    technologies = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    docs_dir = mapped_column(Text)
    run_cmd = mapped_column(Text)
    test_cmd = mapped_column(Text)
    # Base directory to scan for this component's tests (repo-relative, e.g.
    # "repos/aw-meta-display/WatchUITests" or "src/tests/unit/mcp") — feeds
    # the discovery scanner (architecture_discovery.py) so the traceability
    # matrix stays populated without hand-registering every test file.
    test_base_path = mapped_column(Text)
    edited_by = mapped_column(Text, nullable=False, server_default=text("'generated'"))
    created_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    updated_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    __table_args__ = (Index("app__architecture__idx_component_parent", "parent_id"),)


class Requirement(Base):
    __tablename__ = "app__architecture__requirement"
    id = mapped_column(_UUID, **_UUID_PK)
    component_id = mapped_column(
        _UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"), nullable=False
    )
    title = mapped_column(Text, nullable=False)
    gherkin_given = mapped_column(Text, nullable=False)
    gherkin_when = mapped_column(Text, nullable=False)
    gherkin_then = mapped_column(Text, nullable=False)
    intended_status = mapped_column(
        Text, nullable=False, server_default=text("'not_implemented'")
    )
    implemented_at = mapped_column(TIMESTAMP(timezone=True))
    implemented_ref = mapped_column(Text)
    # Every requirement is meant to be implemented through a Kanban card
    # (see docs/knowledge_base/docs/architecture/standards/requirement-kanban-link.md).
    # kanban_page_id is the Notion page id; nullable because a requirement can
    # be documented before a card is created, but set_requirement_status()
    # refuses to move a requirement to 'implemented' without one.
    kanban_page_id = mapped_column(Text)
    kanban_url = mapped_column(Text)
    # Which logger this rule's failure/success path reports through (e.g.
    # "src.api.routes.notion_kanban") — lets the traceability matrix answer
    # "how is this logged" without re-reading the implementation every time.
    logger_name = mapped_column(Text)
    created_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    updated_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    __table_args__ = (
        CheckConstraint("intended_status IN ('not_implemented', 'implemented')"),
        Index("app__architecture__idx_requirement_component", "component_id"),
    )


class Testcase(Base):
    __tablename__ = "app__architecture__testcase"
    id = mapped_column(_UUID, **_UUID_PK)
    kind = mapped_column(Text, nullable=False)
    file_path = mapped_column(Text, nullable=False, unique=True)
    test_plan_notes = mapped_column(Text)
    last_run_status = mapped_column(
        Text, nullable=False, server_default=text("'unknown'")
    )
    last_run_at = mapped_column(TIMESTAMP(timezone=True))
    # Flaky-test policy: a test that fails intermittently gets flagged here
    # instead of being silently re-run until green — makes eroding suite
    # confidence visible/listable instead of invisible.
    is_flaky = mapped_column(Boolean, nullable=False, server_default=text("false"))
    flaky_note = mapped_column(Text)
    # Explicit override for HOW to run this test, when it isn't a plain
    # `pytest <file_path>` — e.g. a Swift XCTest that needs a Python wrapper
    # dispatching to a Remote Agent (Xcode Simulator on macbook-fred). Run
    # from BASE_DIR; exit 0 = passing, non-zero = fail, same convention as
    # pytest so the Play button works identically regardless of runner.
    run_command = mapped_column(Text)
    # Direct owner, set by the discovery scanner — independent of any
    # req_testcase link, so a test shows up under its component immediately
    # on discovery, before anyone writes a BDD requirement for it.
    component_id = mapped_column(_UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"))
    __table_args__ = (
        CheckConstraint("kind IN ('unit', 'integration', 'e2e')"),
        CheckConstraint("last_run_status IN ('passing', 'fail', 'unknown')"),
        Index("app__architecture__idx_testcase_component", "component_id"),
    )


class ReqTestcase(Base):
    __tablename__ = "app__architecture__req_testcase"
    requirement_id = mapped_column(
        _UUID, ForeignKey("app__architecture__requirement.id", ondelete="CASCADE"), primary_key=True
    )
    testcase_id = mapped_column(
        _UUID, ForeignKey("app__architecture__testcase.id", ondelete="CASCADE"), primary_key=True
    )


class BugEvent(Base):
    __tablename__ = "app__architecture__bugevent"
    id = mapped_column(_UUID, **_UUID_PK)
    requirement_id = mapped_column(
        _UUID, ForeignKey("app__architecture__requirement.id", ondelete="CASCADE"), nullable=False
    )
    detected_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    description = mapped_column(Text, nullable=False)
    resolved_at = mapped_column(TIMESTAMP(timezone=True))
    resolved_ref = mapped_column(Text)
    __table_args__ = (
        Index("app__architecture__idx_bugevent_req", "requirement_id"),
        Index(
            TABLE_PREFIX + "idx_bugevent_open", "requirement_id",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )


class DebtNote(Base):
    """Known technical debt against a component — distinct from BugEvent:
    not a user-observed breakage, just something noted during a periodic
    review (e.g. a requirement with no linked test, a broken abstraction) so
    it's listable instead of living only in someone's memory."""
    __tablename__ = "app__architecture__debtnote"
    id = mapped_column(_UUID, **_UUID_PK)
    component_id = mapped_column(
        _UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id = mapped_column(
        _UUID, ForeignKey("app__architecture__requirement.id", ondelete="SET NULL")
    )
    description = mapped_column(Text, nullable=False)
    noted_at = mapped_column(TIMESTAMP(timezone=True), **_NOW)
    resolved_at = mapped_column(TIMESTAMP(timezone=True))
    resolved_ref = mapped_column(Text)
    __table_args__ = (
        Index("app__architecture__idx_debtnote_component", "component_id"),
        Index(
            TABLE_PREFIX + "idx_debtnote_open", "component_id",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )


class Connection(Base):
    __tablename__ = "app__architecture__connection"
    id = mapped_column(_UUID, **_UUID_PK)
    from_component_id = mapped_column(
        _UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"), nullable=False
    )
    to_component_id = mapped_column(
        _UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"), nullable=False
    )
    kind = mapped_column(Text, nullable=False)
    description = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("kind IN ('http', 'db', 'stdio-mcp', 'queue', 'other')"),
        Index("app__architecture__idx_connection_from", "from_component_id"),
        Index("app__architecture__idx_connection_to", "to_component_id"),
        Index(
            TABLE_PREFIX + "uq_connection_edge",
            "from_component_id", "to_component_id", "kind", unique=True,
        ),
    )


class McpTool(Base):
    __tablename__ = "app__architecture__mcptool"
    id = mapped_column(_UUID, **_UUID_PK)
    provider_component_id = mapped_column(
        _UUID, ForeignKey("app__architecture__component.id", ondelete="CASCADE"), nullable=False
    )
    name = mapped_column(Text, nullable=False)
    description = mapped_column(Text)
    __table_args__ = (UniqueConstraint("provider_component_id", "name"),)


class VRequirementHealth(ViewBase):
    __tablename__ = "app__architecture__v_requirement_health"
    requirement_id = mapped_column(_UUID, primary_key=True)
    health = mapped_column(Text)


class VComponentHealth(ViewBase):
    __tablename__ = "app__architecture__v_component_health"
    component_id = mapped_column(_UUID, primary_key=True)
    health = mapped_column(Text)


# ---------------------------------------------------------------------------
# Schema bootstrap — idempotent raw DDL / VIEWs (no clean declarative form)
# ---------------------------------------------------------------------------

# The two derived-health VIEWs are dropped+recreated on every ensure so their
# definition always tracks this file. Health is DERIVED here, never stored.
#
# v_component_health ROLLS UP the subtree, not just a component's own
# requirements. Without that a parent read 'planned' while a child sat
# 'broken' — the tree's whole purpose is that a glance at the root tells you
# whether anything underneath is on fire, and the un-rolled version made the
# root the least informative row in the view.
#
# `depth < 32` is a cycle guard, not a modelling limit. parent_id is a
# self-referencing FK with nothing stopping a -> b -> a, and a WITH RECURSIVE
# over a cycle does not terminate: one bad row would hang every query that
# touches component health, including the window's first paint.
_VIEWS = """
CREATE OR REPLACE VIEW {table:app__architecture__v_requirement_health} AS
SELECT
  r.id AS requirement_id,
  CASE
    WHEN EXISTS (
      SELECT 1 FROM {table:app__architecture__bugevent} b
      WHERE b.requirement_id = r.id AND b.resolved_at IS NULL
    ) THEN 'broken'
    WHEN EXISTS (
      SELECT 1 FROM {table:app__architecture__req_testcase} rt
      JOIN {table:app__architecture__testcase} t ON t.id = rt.testcase_id
      WHERE rt.requirement_id = r.id AND t.last_run_status = 'fail'
    ) THEN 'broken'
    WHEN r.intended_status = 'implemented' THEN 'implemented'
    ELSE 'not_implemented'
  END AS health
FROM {table:app__architecture__requirement} r;

CREATE OR REPLACE VIEW {table:app__architecture__v_component_health} AS
WITH RECURSIVE subtree(root_id, node_id, depth) AS (
    SELECT id, id, 0 FROM {table:app__architecture__component}
  UNION ALL
    SELECT s.root_id, c.id, s.depth + 1
    FROM subtree s
    JOIN {table:app__architecture__component} c ON c.parent_id = s.node_id
    WHERE s.depth < 32
)
SELECT
  s.root_id AS component_id,
  CASE
    WHEN count(r.id) = 0                        THEN 'planned'
    WHEN bool_or(h.health = 'broken')           THEN 'broken'
    WHEN bool_and(h.health = 'implemented')     THEN 'implemented'
    WHEN bool_or(h.health = 'implemented')      THEN 'partial'
    ELSE 'planned'
  END AS health
FROM subtree s
LEFT JOIN {table:app__architecture__requirement} r ON r.component_id = s.node_id
LEFT JOIN {table:app__architecture__v_requirement_health} h ON h.requirement_id = r.id
GROUP BY s.root_id;
"""

# Idempotent migrations for tables that predate a field/constraint (safe no-ops).
_MIGRATIONS = """
ALTER TABLE {table:app__architecture__component} ADD COLUMN IF NOT EXISTS description TEXT;
UPDATE {table:app__architecture__testcase} SET last_run_status = 'unknown' WHERE last_run_status IS NULL;
ALTER TABLE {table:app__architecture__testcase} ALTER COLUMN last_run_status SET DEFAULT 'unknown';
ALTER TABLE {table:app__architecture__testcase} ALTER COLUMN last_run_status SET NOT NULL;
ALTER TABLE {table:app__architecture__requirement} ADD COLUMN IF NOT EXISTS kanban_page_id TEXT;
ALTER TABLE {table:app__architecture__requirement} ADD COLUMN IF NOT EXISTS kanban_url TEXT;
ALTER TABLE {table:app__architecture__requirement} ADD COLUMN IF NOT EXISTS logger_name TEXT;
ALTER TABLE {table:app__architecture__testcase} ADD COLUMN IF NOT EXISTS is_flaky BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE {table:app__architecture__testcase} ADD COLUMN IF NOT EXISTS flaky_note TEXT;
ALTER TABLE {table:app__architecture__testcase} ADD COLUMN IF NOT EXISTS run_command TEXT;
ALTER TABLE {table:app__architecture__component} ADD COLUMN IF NOT EXISTS test_base_path TEXT;
ALTER TABLE {table:app__architecture__testcase} ADD COLUMN IF NOT EXISTS component_id UUID REFERENCES {table:app__architecture__component}(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS app__architecture__idx_testcase_component ON {table:app__architecture__testcase}(component_id);
"""


def _split_statements(block: str) -> list[str]:
    """Split a DDL block into single statements for ``text()`` binding.

    A plain ``;`` split is safe *for these two blocks specifically* — neither
    ``_MIGRATIONS`` nor ``_VIEWS`` contains a semicolon inside a string literal
    or a function body. Any DDL added later that does must be appended as its
    own constant rather than smuggled in here.
    """
    return [s.strip() for s in block.split(";") if s.strip()]


def ensure_schema(retries: int = 12, delay: float = 1.0) -> None:
    """Idempotent create of tables + views. Retries while aw-postgres boots.

    Tables come from the declarative models (``create_all``); the additive
    migrations and the two derived-health VIEWs go through
    ``ctx.db.execute_multi``, which prefix-validates every table they name.

    The monolith ran both DDL blocks as one multi-statement DBAPI cursor
    execute; ``execute_multi`` binds through SQLAlchemy ``text()``, which is
    single-statement, so they are split on ``;`` and applied in order. Order
    matters for the VIEWs — ``v_component_health`` selects from
    ``v_requirement_health`` — and ``_VIEWS`` already declares them that way."""
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            Base.metadata.create_all(get_engine(), checkfirst=True)
            for block in (_MIGRATIONS, _VIEWS):
                for stmt in _split_statements(block):
                    _ctx.db.execute_multi(stmt, OWNED)
            return
        except Exception as exc:  # Postgres may still be starting
            last_exc = exc
            time.sleep(delay)
    if last_exc:
        raise last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_dict(obj) -> dict:
    """Map an ORM instance to a plain dict of its column values."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _resolve_parent_id(session: Session, parent_slug: str | None):
    if not parent_slug:
        return None
    pid = session.execute(
        select(Component.id).where(Component.slug == parent_slug)
    ).scalar_one_or_none()
    if pid is None:
        raise ValueError(f"parent_slug '{parent_slug}' does not exist")
    return pid


def _component_id(session: Session, slug: str):
    cid = session.execute(
        select(Component.id).where(Component.slug == slug)
    ).scalar_one_or_none()
    if cid is None:
        raise ValueError(f"component '{slug}' not found")
    return cid


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

def upsert_component(
    slug: str,
    name: str,
    parent_slug=_UNSET,
    repo=_UNSET,
    layer=_UNSET,
    description=_UNSET,
    technologies=_UNSET,
    docs_dir=_UNSET,
    run_cmd=_UNSET,
    test_cmd=_UNSET,
    test_base_path=_UNSET,
    edited_by: str = "generated",
) -> dict:
    """Create or update a component by its stable slug (idempotent).

    **Provenance.** ``edited_by`` is not decoration — it decides whether this
    write is allowed to overwrite what's already there:

    * ``edited_by="scan"`` — a machine-derived write (see ``scan.py``). It
      only updates a row that is *still* ``'scan'``. The moment anything else
      touches that component, the scan stops overwriting it, forever.
    * anything else (``'generated'`` — the MCP tools' default — or an explicit
      ``'curated'``) — a deliberate write by an agent or a person. Overwrites,
      and stamps the row so the scan backs off.

    Without that rule a scan on a schedule silently erases every description
    anyone writes, once per tick. The column existed from the start and nothing
    read it; ``upsert_testcase`` had already learned the same lesson on the
    other side of the schema, where it refuses to clobber ``run_command`` /
    ``is_flaky`` / ``last_run_status`` on a rescan.

    A refused update is a no-op, not an error: the scan re-running against a
    fully curated catalog should be silent, not noisy.
    """
    supplied = {
        "repo": repo, "layer": layer, "description": description,
        "technologies": technologies, "docs_dir": docs_dir, "run_cmd": run_cmd,
        "test_cmd": test_cmd, "test_base_path": test_base_path,
    }
    supplied = {k: v for k, v in supplied.items() if v is not _UNSET}
    if "technologies" in supplied:
        supplied["technologies"] = supplied["technologies"] or []

    with get_session() as s:
        values = dict(slug=slug, name=name, edited_by=edited_by, **supplied)
        if parent_slug is not _UNSET:
            values["parent_id"] = _resolve_parent_id(s, parent_slug)
        stmt = pg_insert(Component).values(**values)
        # Only the columns this caller actually spoke about. An omitted one
        # keeps whatever is in the row: the scan has no opinion about
        # `test_cmd`, and used to blank it on every nightly run, so a command
        # someone set by hand survived exactly until 05:00.
        updates = {k: getattr(stmt.excluded, k) for k in values if k != "slug"}
        updates["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_=updates,
            # Only present for a scan write — a curated write has no condition
            # and overwrites as before.
            where=(Component.edited_by == SCAN_PROVENANCE)
            if edited_by == SCAN_PROVENANCE else None,
        )
        s.execute(stmt)
        s.commit()
    return {"slug": slug}


_COMPONENT_FIELDS = {
    "name", "repo", "layer", "description", "technologies",
    "docs_dir", "run_cmd", "test_cmd", "test_base_path", "edited_by",
}


def update_component(slug: str, **fields) -> dict:
    """Partial update of any subset of component fields. ``parent_slug`` is
    resolved to ``parent_id``."""
    with get_session() as s:
        comp = s.execute(
            select(Component).where(Component.slug == slug)
        ).scalar_one_or_none()
        if comp is None:
            raise ValueError(f"component '{slug}' not found")

        changed = False
        if "parent_slug" in fields:
            comp.parent_id = _resolve_parent_id(s, fields.pop("parent_slug"))
            changed = True
        for k, v in fields.items():
            if k not in _COMPONENT_FIELDS:
                raise ValueError(f"unknown component field '{k}'")
            setattr(comp, k, v)
            changed = True
        if not changed:
            return {"slug": slug}
        comp.updated_at = func.now()
        s.commit()
    return {"slug": slug}


def delete_component(slug: str, cascade: bool = True) -> dict:
    """Delete a component (and, via FK cascade, its requirements / connections /
    tools). Refuses if it still has sub-components unless ``cascade`` is set."""
    with get_session() as s:
        cid = s.execute(
            select(Component.id).where(Component.slug == slug)
        ).scalar_one_or_none()
        if cid is None:
            raise ValueError(f"component '{slug}' not found")
        kids = s.execute(
            select(Component.slug).where(Component.parent_id == cid)
        ).scalars().all()
        if kids and not cascade:
            names = ", ".join(kids)
            raise ValueError(
                f"component '{slug}' has sub-components ({names}); "
                f"pass cascade=true to delete the subtree"
            )
        # Delete children explicitly (parent_id is ON DELETE SET NULL, not cascade).
        for k in kids:
            delete_component(k, cascade=True)
        s.execute(delete(Component).where(Component.slug == slug))
        s.commit()
    return {"ok": True, "slug": slug}


def get_component(slug: str) -> dict | None:
    with get_session() as s:
        return _get_component(s, slug)


def _get_component(session: Session, slug: str) -> dict | None:
    parent = aliased(Component)
    row = session.execute(
        select(Component, parent.slug.label("parent_slug"), VComponentHealth.health)
        .outerjoin(parent, parent.id == Component.parent_id)
        .outerjoin(VComponentHealth, VComponentHealth.component_id == Component.id)
        .where(Component.slug == slug)
    ).first()
    if row is None:
        return None
    comp, parent_slug, health = row
    d = _to_dict(comp)
    d["parent_slug"] = parent_slug
    d["health"] = health
    return d


def _root_ancestor_map(session: Session) -> dict:
    """slug -> (root_slug, root_name), walking each component's parent_id
    chain to its topmost ancestor. Used so the traceability matrix can group
    by "the component of the repository" instead of a narrowly-scoped leaf
    (e.g. a sub-feature component created just to hold one requirement)."""
    rows = session.execute(
        select(Component.id, Component.slug, Component.name, Component.parent_id)
    ).all()
    by_id = {r.id: (r.slug, r.name, r.parent_id) for r in rows}
    result = {}
    for r in rows:
        slug, name, parent_id = r.slug, r.name, r.parent_id
        seen = {r.id}
        cur_id = parent_id
        while cur_id is not None and cur_id in by_id and cur_id not in seen:
            slug, name, cur_id2 = by_id[cur_id]
            seen.add(cur_id)
            cur_id = cur_id2
        result[r.slug] = (slug, name)
    return result


def list_components(repo: str | None = None, layer: str | None = None) -> list[dict]:
    parent = aliased(Component)
    stmt = (
        select(
            Component.slug, Component.name, Component.repo, Component.layer,
            Component.technologies, parent.slug.label("parent_slug"),
            # Provenance is projected because callers need to act on it, not
            # merely display it: the scan reads this to know which rows a
            # person has taken over, and skips them (see scan.py). It was a
            # write-only column until then.
            Component.edited_by,
            # Projected because a caller needs to know whether a component can
            # be RUN, not just that it exists. Its absence made an audit of
            # "which components still lack a test command" answer "all of
            # them", including the seven that had one.
            Component.test_cmd,
            VComponentHealth.health,
        )
        .outerjoin(parent, parent.id == Component.parent_id)
        .outerjoin(VComponentHealth, VComponentHealth.component_id == Component.id)
    )
    if repo:
        stmt = stmt.where(Component.repo == repo)
    if layer:
        stmt = stmt.where(Component.layer == layer)
    stmt = stmt.order_by(Component.slug)
    with get_session() as s:
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------

def create_requirement(
    component_slug: str,
    title: str,
    given: str,
    when: str,
    then: str,
    intended_status: str = "not_implemented",
) -> dict:
    with get_session() as s:
        cid = _component_id(s, component_slug)
        req = Requirement(
            component_id=cid, title=title, gherkin_given=given,
            gherkin_when=when, gherkin_then=then, intended_status=intended_status,
        )
        s.add(req)
        s.flush()
        rid = req.id
        s.commit()
    return {"id": rid}


def update_requirement(req_id: str, **fields) -> dict:
    mapping = {
        "title": "title", "given": "gherkin_given", "when": "gherkin_when",
        "then": "gherkin_then", "intended_status": "intended_status",
        "implemented_ref": "implemented_ref", "logger_name": "logger_name",
    }
    for k in fields:
        if k not in mapping:
            raise ValueError(f"unknown requirement field '{k}'")
    if not fields:
        return {"id": req_id}
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        for k, v in fields.items():
            setattr(req, mapping[k], v)
        req.updated_at = func.now()
        s.commit()
    return {"id": req_id}


def set_requirement_status(
    req_id: str, intended_status: str, implemented_ref: str | None = None
) -> dict:
    if intended_status not in ("not_implemented", "implemented"):
        raise ValueError("intended_status must be not_implemented | implemented")
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        if intended_status == "implemented" and not req.kanban_page_id:
            raise ValueError(
                "requirement has no linked Kanban card — link one via "
                "link_requirement_kanban before marking it implemented"
            )
        req.intended_status = intended_status
        if implemented_ref is not None:
            req.implemented_ref = implemented_ref
        if intended_status == "implemented":
            if req.implemented_at is None:
                req.implemented_at = func.now()
        else:
            req.implemented_at = None
        req.updated_at = func.now()
        s.commit()
    return {"id": req_id}


def link_requirement_kanban(
    req_id: str, kanban_page_id: str, kanban_url: str | None = None
) -> dict:
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        req.kanban_page_id = kanban_page_id
        req.kanban_url = kanban_url
        req.updated_at = func.now()
        s.commit()
    return {"id": req_id, "kanban_page_id": kanban_page_id, "kanban_url": kanban_url}


def unlink_requirement_kanban(req_id: str) -> dict:
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        req.kanban_page_id = None
        req.kanban_url = None
        req.updated_at = func.now()
        s.commit()
    return {"id": req_id}


def delete_requirement(req_id: str) -> dict:
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        s.delete(req)
        s.commit()
    return {"ok": True}


def get_component_requirements(slug: str) -> list[dict]:
    with get_session() as s:
        cid = _component_id(s, slug)
        stmt = (
            select(
                Requirement.id, Requirement.title,
                Requirement.gherkin_given.label("given"),
                Requirement.gherkin_when.label("when"),
                Requirement.gherkin_then.label("then"),
                Requirement.intended_status, Requirement.implemented_ref,
                Requirement.kanban_page_id, Requirement.kanban_url,
                Requirement.logger_name,
                VRequirementHealth.health,
            )
            .outerjoin(
                VRequirementHealth,
                VRequirementHealth.requirement_id == Requirement.id,
            )
            .where(Requirement.component_id == cid)
            .order_by(Requirement.created_at)
        )
        return [dict(r._mapping) for r in s.execute(stmt)]


def get_traceability_matrix(component_slug: str | None = None) -> list[dict]:
    """One row per requirement: the rule asked for (Given/When/Then), what
    implemented it (Kanban card / implemented_ref), how it's tested (linked
    testcases + last result), how it's logged (logger_name), and derived
    health — the whole ask -> build -> test -> observe chain in one place
    instead of five separate lookups. Pass component_slug to scope to one
    component; omit for the whole catalog."""
    with get_session() as s:
        stmt = (
            select(
                Component.slug.label("component_slug"),
                Component.name.label("component_name"),
                Requirement.id.label("requirement_id"),
                Requirement.title,
                Requirement.gherkin_given.label("given"),
                Requirement.gherkin_when.label("when"),
                Requirement.gherkin_then.label("then"),
                Requirement.intended_status, Requirement.implemented_ref,
                Requirement.kanban_page_id, Requirement.kanban_url,
                Requirement.logger_name,
                VRequirementHealth.health,
            )
            .join(Component, Component.id == Requirement.component_id)
            .outerjoin(
                VRequirementHealth,
                VRequirementHealth.requirement_id == Requirement.id,
            )
        )
        if component_slug:
            stmt = stmt.where(Component.slug == component_slug)
        stmt = stmt.order_by(Component.slug, Requirement.created_at)
        rows = [dict(r._mapping) for r in s.execute(stmt)]

        root_map = _root_ancestor_map(s)
        for r in rows:
            root_slug, root_name = root_map.get(r["component_slug"], (r["component_slug"], r["component_name"]))
            r["root_component_slug"] = root_slug
            r["root_component_name"] = root_name

        req_ids = [r["requirement_id"] for r in rows]
        tests_by_req: dict = {}
        if req_ids:
            test_stmt = (
                select(
                    ReqTestcase.requirement_id,
                    Testcase.file_path, Testcase.kind,
                    Testcase.last_run_status, Testcase.last_run_at,
                    Testcase.run_command,
                )
                .join(Testcase, Testcase.id == ReqTestcase.testcase_id)
                .where(ReqTestcase.requirement_id.in_(req_ids))
            )
            for row in s.execute(test_stmt):
                tests_by_req.setdefault(row.requirement_id, []).append({
                    "file_path": row.file_path, "kind": row.kind,
                    "last_run_status": row.last_run_status,
                    "last_run_at": row.last_run_at,
                    "run_command": row.run_command,
                })
        for r in rows:
            r["tests"] = tests_by_req.get(r["requirement_id"], [])
        return rows


# ---------------------------------------------------------------------------
# Testcase + N:N traceability
# ---------------------------------------------------------------------------

def upsert_testcase(
    kind: str, file_path: str, test_plan_notes: str | None = None,
    component_slug: str | None = None,
) -> dict:
    """Idempotent on file_path. Never clobbers run_command/is_flaky/
    last_run_status/flaky_note of an already-known test — the discovery
    scanner re-runs this on every scan and must not erase manual overrides
    (e.g. a Swift test's registered run_command)."""
    with get_session() as s:
        component_id = _component_id(s, component_slug) if component_slug else None
        stmt = pg_insert(Testcase).values(
            kind=kind, file_path=file_path, test_plan_notes=test_plan_notes,
            component_id=component_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["file_path"],
            set_=dict(
                kind=stmt.excluded.kind,
                test_plan_notes=func.coalesce(
                    stmt.excluded.test_plan_notes, Testcase.test_plan_notes
                ),
                component_id=func.coalesce(stmt.excluded.component_id, Testcase.component_id),
            ),
        ).returning(Testcase.id)
        tid = s.execute(stmt).scalar_one()
        s.commit()
    return {"id": tid}


def update_testcase_result(
    file_path: str, last_run_status: str, last_run_at=None
) -> dict:
    if last_run_status not in ("passing", "fail", "unknown"):
        raise ValueError("last_run_status must be passing | fail | unknown")
    with get_session() as s:
        tc = s.execute(
            select(Testcase).where(Testcase.file_path == file_path)
        ).scalar_one_or_none()
        if tc is None:
            raise ValueError(f"testcase '{file_path}' not found")
        tc.last_run_status = last_run_status
        tc.last_run_at = last_run_at if last_run_at is not None else func.now()
        s.commit()
    return {"ok": True}


def set_testcase_run_command(file_path: str, run_command: str | None) -> dict:
    """Register (or clear, with None) an explicit override for how to run
    this test, when it isn't a plain `pytest <file_path>` (e.g. a Swift
    XCTest dispatched to a Remote Agent). See Testcase.run_command."""
    with get_session() as s:
        tc = s.execute(
            select(Testcase).where(Testcase.file_path == file_path)
        ).scalar_one_or_none()
        if tc is None:
            raise ValueError(f"testcase '{file_path}' not found")
        tc.run_command = run_command
        s.commit()
    return {"ok": True}


def delete_testcase(testcase_id: str) -> dict:
    with get_session() as s:
        tc = s.get(Testcase, testcase_id)
        if tc is None:
            raise ValueError(f"testcase '{testcase_id}' not found")
        s.delete(tc)
        s.commit()
    return {"ok": True}


def link_requirement_test(requirement_id: str, testcase_id: str) -> dict:
    with get_session() as s:
        stmt = pg_insert(ReqTestcase).values(
            requirement_id=requirement_id, testcase_id=testcase_id,
        ).on_conflict_do_nothing()
        s.execute(stmt)
        s.commit()
    return {"ok": True}


def unlink_requirement_test(requirement_id: str, testcase_id: str) -> dict:
    with get_session() as s:
        s.execute(
            delete(ReqTestcase).where(
                ReqTestcase.requirement_id == requirement_id,
                ReqTestcase.testcase_id == testcase_id,
            )
        )
        s.commit()
    return {"ok": True}


def list_components_with_test_base_path() -> list[dict]:
    """Every component that has a test_base_path set — what the discovery
    scanner iterates over."""
    with get_session() as s:
        stmt = (
            select(Component.slug, Component.name, Component.test_base_path)
            .where(Component.test_base_path.is_not(None))
            .order_by(Component.slug)
        )
        return [dict(r._mapping) for r in s.execute(stmt)]


def get_testcase_owner_slug(file_path: str) -> str | None:
    """The slug of the component a testcase currently belongs to (None if
    unowned or unknown) — used by discovery to detect cross-component
    ownership steals before upserting."""
    with get_session() as s:
        return s.execute(
            select(Component.slug)
            .join(Testcase, Testcase.component_id == Component.id)
            .where(Testcase.file_path == file_path)
        ).scalar_one_or_none()


def list_component_tests(component_slug: str | None = None) -> list[dict]:
    """Every test case directly owned by a component (component_id set by the
    discovery scanner or a manual create_testcase), regardless of whether
    it's linked to a BDD requirement yet — so a freshly-discovered test shows
    up under its component before anyone writes a rule for it. Includes
    `linked` (bool): whether it has at least one req_testcase link."""
    linked_ids = select(ReqTestcase.testcase_id).distinct().scalar_subquery()
    stmt = (
        select(
            Testcase.id, Testcase.kind, Testcase.file_path,
            Testcase.last_run_status, Testcase.last_run_at,
            Testcase.run_command, Testcase.is_flaky, Testcase.flaky_note,
            Component.slug.label("component_slug"),
            Component.name.label("component_name"),
            Testcase.id.in_(linked_ids).label("linked"),
        )
        .join(Component, Component.id == Testcase.component_id)
    )
    if component_slug:
        stmt = stmt.where(Component.slug == component_slug)
    stmt = stmt.order_by(Component.slug, Testcase.file_path)
    with get_session() as s:
        return [dict(r._mapping) for r in s.execute(stmt)]


def get_testcase_by_path(file_path: str) -> dict | None:
    """One testcase, plus its owning component's ``test_cmd`` and ``repo``.

    The component fields ride along because the runner needs them and asking
    separately would mean a second round-trip for every play-button press.
    ``test_cmd`` is the per-repo template that spares anyone from registering a
    ``run_command`` on each of a few hundred discovered files.
    """
    with get_session() as s:
        row = s.execute(
            select(
                Testcase.id, Testcase.kind, Testcase.file_path, Testcase.run_command,
                Component.test_cmd.label("component_test_cmd"),
                Component.repo.label("component_repo"),
                Component.slug.label("component_slug"),
            )
            .outerjoin(Component, Component.id == Testcase.component_id)
            .where(Testcase.file_path == file_path)
        ).mappings().first()
        return dict(row) if row else None


def get_requirement_tests(req_id: str) -> list[dict]:
    stmt = (
        select(
            Testcase.id, Testcase.kind, Testcase.file_path,
            Testcase.last_run_status, Testcase.last_run_at, Testcase.run_command,
        )
        .join(ReqTestcase, ReqTestcase.testcase_id == Testcase.id)
        .where(ReqTestcase.requirement_id == req_id)
        .order_by(Testcase.file_path)
    )
    with get_session() as s:
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Bug history
# ---------------------------------------------------------------------------

def report_bug(requirement_id: str, description: str, detected_at=None) -> dict:
    with get_session() as s:
        bug = BugEvent(requirement_id=requirement_id, description=description)
        if detected_at is not None:
            bug.detected_at = detected_at
        s.add(bug)
        s.flush()
        bid = bug.id
        s.commit()
    return {"id": bid}


def resolve_bug(bug_id: str, resolved_ref: str | None = None, resolved_at=None) -> dict:
    with get_session() as s:
        bug = s.get(BugEvent, bug_id)
        if bug is None:
            raise ValueError(f"bugevent '{bug_id}' not found")
        bug.resolved_at = resolved_at if resolved_at is not None else func.now()
        bug.resolved_ref = resolved_ref
        s.commit()
    return {"ok": True}


def get_requirement_bug_history(req_id: str) -> list[dict]:
    stmt = (
        select(
            BugEvent.id, BugEvent.detected_at, BugEvent.description,
            BugEvent.resolved_at, BugEvent.resolved_ref,
        )
        .where(BugEvent.requirement_id == req_id)
        .order_by(BugEvent.detected_at)
    )
    with get_session() as s:
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Flaky-test tracking
# ---------------------------------------------------------------------------

def mark_testcase_flaky(file_path: str, is_flaky: bool, flaky_note: str | None = None) -> dict:
    with get_session() as s:
        tc = s.execute(
            select(Testcase).where(Testcase.file_path == file_path)
        ).scalar_one_or_none()
        if tc is None:
            raise ValueError(f"testcase '{file_path}' not found")
        tc.is_flaky = is_flaky
        if flaky_note is not None:
            tc.flaky_note = flaky_note
        elif not is_flaky:
            tc.flaky_note = None
        s.commit()
    return {"ok": True}


def list_flaky_testcases() -> list[dict]:
    stmt = (
        select(
            Testcase.id, Testcase.file_path, Testcase.kind,
            Testcase.last_run_status, Testcase.last_run_at, Testcase.flaky_note,
        )
        .where(Testcase.is_flaky.is_(True))
        .order_by(Testcase.file_path)
    )
    with get_session() as s:
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Technical debt notes
# ---------------------------------------------------------------------------

def create_debt_note(
    component_slug: str, description: str, requirement_id: str | None = None,
) -> dict:
    with get_session() as s:
        cid = _component_id(s, component_slug)
        note = DebtNote(
            component_id=cid, requirement_id=requirement_id, description=description,
        )
        s.add(note)
        s.flush()
        nid = note.id
        s.commit()
    return {"id": nid}


def resolve_debt_note(debt_id: str, resolved_ref: str | None = None, resolved_at=None) -> dict:
    with get_session() as s:
        note = s.get(DebtNote, debt_id)
        if note is None:
            raise ValueError(f"debtnote '{debt_id}' not found")
        note.resolved_at = resolved_at if resolved_at is not None else func.now()
        note.resolved_ref = resolved_ref
        s.commit()
    return {"ok": True}


def list_debt_notes(component_slug: str | None = None, open_only: bool = True) -> list[dict]:
    with get_session() as s:
        stmt = (
            select(
                DebtNote.id, Component.slug.label("component_slug"),
                DebtNote.requirement_id, DebtNote.description,
                DebtNote.noted_at, DebtNote.resolved_at, DebtNote.resolved_ref,
            )
            .join(Component, Component.id == DebtNote.component_id)
        )
        if component_slug:
            stmt = stmt.where(Component.slug == component_slug)
        if open_only:
            stmt = stmt.where(DebtNote.resolved_at.is_(None))
        stmt = stmt.order_by(DebtNote.noted_at)
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def create_connection(
    from_slug: str, to_slug: str, kind: str, description: str | None = None
) -> dict:
    with get_session() as s:
        fid = _component_id(s, from_slug)
        tid = _component_id(s, to_slug)
        stmt = pg_insert(Connection).values(
            from_component_id=fid, to_component_id=tid, kind=kind,
            description=description,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["from_component_id", "to_component_id", "kind"],
            set_=dict(description=stmt.excluded.description),
        ).returning(Connection.id)
        cid = s.execute(stmt).scalar_one()
        s.commit()
    return {"id": cid}


def delete_connection(connection_id: str) -> dict:
    with get_session() as s:
        conn = s.get(Connection, connection_id)
        if conn is None:
            raise ValueError(f"connection '{connection_id}' not found")
        s.delete(conn)
        s.commit()
    return {"ok": True}


def get_component_connections(slug: str) -> list[dict]:
    fc = aliased(Component)
    tc = aliased(Component)
    with get_session() as s:
        cid = _component_id(s, slug)
        stmt = (
            select(
                Connection.id, fc.slug.label("from"), tc.slug.label("to"),
                Connection.kind, Connection.description,
            )
            .join(fc, fc.id == Connection.from_component_id)
            .join(tc, tc.id == Connection.to_component_id)
            .where(
                (Connection.from_component_id == cid)
                | (Connection.to_component_id == cid)
            )
            .order_by(Connection.kind, tc.slug)
        )
        return [dict(r._mapping) for r in s.execute(stmt)]


def get_requirement_impact(req_id: str) -> dict:
    """What else might break if this requirement's component changes.

    Derived, not stored (same philosophy as health): walks the existing
    `connection` graph one hop from the requirement's own component, in both
    directions, and lists the requirements documented on each neighbor. Meant
    to be checked before flipping a requirement to 'implemented' after a
    breaking-ish change, not a replacement for actually reading the diff."""
    with get_session() as s:
        req = s.get(Requirement, req_id)
        if req is None:
            raise ValueError(f"requirement '{req_id}' not found")
        cid = req.component_id
        own_slug = s.execute(
            select(Component.slug).where(Component.id == cid)
        ).scalar_one()

        fc = aliased(Component)
        tc = aliased(Component)
        neighbor_stmt = (
            select(
                Connection.kind,
                fc.slug.label("from_slug"), tc.slug.label("to_slug"),
                tc.id.label("to_id"), fc.id.label("from_id"),
            )
            .join(fc, fc.id == Connection.from_component_id)
            .join(tc, tc.id == Connection.to_component_id)
            .where(
                (Connection.from_component_id == cid)
                | (Connection.to_component_id == cid)
            )
        )
        neighbors = []
        for row in s.execute(neighbor_stmt):
            other_id = row.to_id if row.from_id == cid else row.from_id
            other_slug = row.to_slug if row.from_id == cid else row.from_slug
            reqs = [
                dict(r._mapping)
                for r in s.execute(
                    select(Requirement.id, Requirement.title, VRequirementHealth.health)
                    .outerjoin(
                        VRequirementHealth,
                        VRequirementHealth.requirement_id == Requirement.id,
                    )
                    .where(Requirement.component_id == other_id)
                )
            ]
            neighbors.append({
                "component_slug": other_slug, "connection_kind": row.kind,
                "requirements": reqs,
            })
        return {
            "requirement_id": req_id,
            "component_slug": own_slug,
            "potentially_impacted_components": neighbors,
        }


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def upsert_mcp_tool(component_slug: str, name: str, description: str | None = None) -> dict:
    with get_session() as s:
        cid = _component_id(s, component_slug)
        stmt = pg_insert(McpTool).values(
            provider_component_id=cid, name=name, description=description,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider_component_id", "name"],
            set_=dict(description=stmt.excluded.description),
        ).returning(McpTool.id)
        tid = s.execute(stmt).scalar_one()
        s.commit()
    return {"id": tid}


def delete_mcp_tool(tool_id: str) -> dict:
    with get_session() as s:
        tool = s.get(McpTool, tool_id)
        if tool is None:
            raise ValueError(f"mcptool '{tool_id}' not found")
        s.delete(tool)
        s.commit()
    return {"ok": True}


def get_component_tools(slug: str) -> list[dict]:
    with get_session() as s:
        cid = _component_id(s, slug)
        stmt = (
            select(McpTool.id, McpTool.name, McpTool.description)
            .where(McpTool.provider_component_id == cid)
            .order_by(McpTool.name)
        )
        return [dict(r._mapping) for r in s.execute(stmt)]


# ---------------------------------------------------------------------------
# Aggregate reads (for the MD generator)
# ---------------------------------------------------------------------------

def component_testcases(slug: str) -> list[dict]:
    """Distinct testcases linked (via any of the component's requirements) to a
    component — what ``run_component_tests`` executes."""
    with get_session() as s:
        cid = _component_id(s, slug)
        stmt = (
            select(
                Testcase.id, Testcase.kind, Testcase.file_path,
                Testcase.last_run_status,
            )
            .join(ReqTestcase, ReqTestcase.testcase_id == Testcase.id)
            .join(Requirement, Requirement.id == ReqTestcase.requirement_id)
            .where(Requirement.component_id == cid)
            .distinct()
            .order_by(Testcase.file_path)
        )
        return [dict(r._mapping) for r in s.execute(stmt)]


def all_component_slugs() -> list[str]:
    with get_session() as s:
        return list(
            s.execute(select(Component.slug).order_by(Component.slug)).scalars()
        )


def full_component(slug: str) -> dict | None:
    """A single nested dict with everything the MD generator needs for one
    component: fields + derived health + connections + tools + requirements
    (each with derived health, linked tests, and bug history). Deterministic
    ordering throughout."""
    with get_session() as s:
        c = _get_component(s, slug)
        if not c:
            return None
        cid = c["id"]

        reqs = [
            dict(r._mapping)
            for r in s.execute(
                select(
                    Requirement.id, Requirement.title, Requirement.gherkin_given,
                    Requirement.gherkin_when, Requirement.gherkin_then,
                    Requirement.intended_status, Requirement.implemented_ref,
                    Requirement.kanban_page_id, Requirement.kanban_url,
                    Requirement.logger_name,
                    VRequirementHealth.health,
                )
                .outerjoin(
                    VRequirementHealth,
                    VRequirementHealth.requirement_id == Requirement.id,
                )
                .where(Requirement.component_id == cid)
                .order_by(Requirement.created_at, Requirement.id)
            )
        ]
        for r in reqs:
            r["tests"] = [
                dict(t._mapping)
                for t in s.execute(
                    select(
                        Testcase.kind, Testcase.file_path, Testcase.last_run_status
                    )
                    .join(ReqTestcase, ReqTestcase.testcase_id == Testcase.id)
                    .where(ReqTestcase.requirement_id == r["id"])
                    .order_by(Testcase.file_path)
                )
            ]
            r["bugs"] = [
                dict(b._mapping)
                for b in s.execute(
                    select(
                        BugEvent.detected_at, BugEvent.description,
                        BugEvent.resolved_at, BugEvent.resolved_ref,
                    )
                    .where(BugEvent.requirement_id == r["id"])
                    .order_by(BugEvent.detected_at, BugEvent.id)
                )
            ]
        c["requirements"] = reqs

        tc = aliased(Component)
        c["connections"] = [
            dict(r._mapping)
            for r in s.execute(
                select(
                    tc.slug.label("to_slug"), Connection.kind, Connection.description
                )
                .join(tc, tc.id == Connection.to_component_id)
                .where(Connection.from_component_id == cid)
                .order_by(Connection.kind, tc.slug)
            )
        ]
        c["tools"] = [
            dict(r._mapping)
            for r in s.execute(
                select(McpTool.name, McpTool.description)
                .where(McpTool.provider_component_id == cid)
                .order_by(McpTool.name)
            )
        ]
        return c
