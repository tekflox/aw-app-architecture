"""Tests for the things the port could plausibly have broken.

These are deliberately not a re-test of the monolith's data-access logic — that
code came across unchanged and its behaviour is the same. What changed is the
*names* (the `app__architecture__` prefix the `db:own-tables` capability
enforces) and the *plumbing* (session from `ctx.db`, KB trigger dropped, paths
resolved against the workspace instead of one repo). A rename that misses one
table is the failure mode here: `ensure_schema` would still create seven tables
and the eighth would silently land unprefixed, which the runtime would refuse —
at boot, in a log nobody reads.

No Postgres needed: the ORM metadata and the DDL strings are inspected
statically, and the one behavioural test fakes the store.
"""
from __future__ import annotations

import json
import os
import threading
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from architecture_app import store  # noqa: E402

PREFIX = "app__architecture__"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestTableNaming:
    def test_every_model_table_is_prefixed(self):
        """The capability facade rejects any name without the prefix, so an
        unprefixed model can never be created — it just fails at bootstrap."""
        for name in store.Base.metadata.tables:
            assert name.startswith(PREFIX), f"{name} would be refused by db:own-tables"

    def test_every_view_is_prefixed(self):
        for name in store.ViewBase.metadata.tables:
            assert name.startswith(PREFIX)

    def test_owned_covers_every_model_and_view(self):
        """`OWNED` is what `execute_multi` validates the DDL against. A model
        missing from it means its migrations silently never run."""
        declared = set(store.Base.metadata.tables) | set(store.ViewBase.metadata.tables)
        assert declared == set(store.OWNED), (
            f"OWNED is out of sync: missing={declared - set(store.OWNED)}, "
            f"stale={set(store.OWNED) - declared}"
        )

    def test_foreign_keys_point_at_prefixed_tables(self):
        for table in store.Base.metadata.tables.values():
            for fk in table.foreign_keys:
                assert fk.target_fullname.startswith(PREFIX), (
                    f"{table.name}: FK -> {fk.target_fullname} lost its prefix"
                )

    def test_index_names_are_prefixed(self):
        """Two apps' tables live in the SAME workspace schema now, so an index
        called `idx_component_parent` is a collision waiting to happen — the
        table prefix doesn't cover index names."""
        for table in store.Base.metadata.tables.values():
            for index in table.indexes:
                assert index.name.startswith(PREFIX), f"{index.name} is not namespaced"


class TestRawDDL:
    def test_every_ddl_table_reference_is_a_placeholder(self):
        """`execute_multi` substitutes `{table:<name>}` and refuses to run a
        statement with an unresolved placeholder left in it. A bare table name
        would instead resolve against the search_path — quietly hitting
        whatever `component` means to that session."""
        for block in (store._MIGRATIONS, store._VIEWS):
            for placeholder in re.findall(r"\{table:([^}]+)\}", block):
                assert placeholder in store.OWNED, f"{placeholder} not in OWNED"

    def test_no_bare_table_names_survive_in_ddl(self):
        bare = set()
        for block in (store._MIGRATIONS, store._VIEWS):
            stripped = re.sub(r"\{table:[^}]+\}", "", block)
            for name in store.OWNED:
                short = name[len(PREFIX):]
                if re.search(r"(?<![\w.]){}(?![\w])".format(re.escape(short)), stripped):
                    bare.add(short)
        assert not bare, f"unprefixed table reference(s) left in raw DDL: {sorted(bare)}"

    def test_statements_split_cleanly(self):
        """`text()` binds one statement at a time, unlike the monolith's raw
        DBAPI cursor — so the blocks have to survive a semicolon split."""
        for block in (store._MIGRATIONS, store._VIEWS):
            stmts = store._split_statements(block)
            assert stmts
            for s in stmts:
                assert ";" not in s

    def test_component_health_view_is_created_after_the_one_it_reads(self):
        """v_component_health SELECTs from v_requirement_health. Split into
        separate statements, creation order stops being incidental."""
        stmts = store._split_statements(store._VIEWS)
        order = [i for i, s in enumerate(stmts) if "CREATE OR REPLACE VIEW" in s]
        req = next(i for i in order if "v_requirement_health}" in stmts[i].split(" AS")[0])
        comp = next(i for i in order if "v_component_health}" in stmts[i].split(" AS")[0])
        assert req < comp


class TestUnboundStoreFailsLoudly:
    def test_get_session_without_bind_raises(self, monkeypatch):
        """A store that fell back to some other engine would write real rows to
        the wrong database and report success — the exact silent degradation
        this workspace keeps getting bitten by."""
        monkeypatch.setattr(store, "_ctx", None)
        with pytest.raises(RuntimeError, match="not bound"):
            store.get_session()


class TestManifest:
    def test_declares_the_capabilities_the_code_actually_uses(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            manifest = json.load(f)
        perms = set(manifest["permissions"])
        assert "db:own-tables" in perms   # store.py
        assert "routes:register" in perms  # plugin.py
        assert "ui:code" in perms          # contributes.frontend
        assert "tasks:contribute" in perms  # contributes.tasks

    def test_seeded_task_does_not_point_at_the_monolith(self):
        """The ported-as-is task ran `.venv/aw/bin/python -m
        src.libs.architecture_discovery` — an interpreter and a module that
        don't exist here, which is why it never worked."""
        with open(os.path.join(REPO, "aw-app.json")) as f:
            manifest = json.load(f)
        # By name, not by position: the seeding framework identifies a
        # contributed task by its name, and this file now ships two.
        task = next(t for t in manifest["contributes"]["tasks"]
                    if t["name"] == "Architecture Test Discovery")
        assert ".venv/aw" not in task["command"]
        assert "src.libs" not in task["command"]
        assert task["command"].startswith("aw-workspace-cli architecture")

    # NOTE: `enabled` used to be asserted False here, on the framework's
    # default ("a task that starts firing the moment an app is installed is a
    # surprise"). It's now True, deliberately — see
    # TestSeededTaskShape.test_enabled for the reasoning. Asserted there rather
    # than deleted, so flipping it back is still a decision someone makes.

    def test_agentic_output_task_names_an_agent(self):
        """Core's manifest validator requires `agent_slug` on `agentic_output`,
        not only on `agent_prompt` — the tasks app's runner bails with "no
        agent_slug configured" BEFORE running the command, so a task without one
        is seeded looking healthy and then never runs. (The app template's
        docs/contributing-tasks.md still documents this as agent_prompt-only;
        the validator is the authority.) Install refuses the manifest outright,
        which is how this was caught."""
        with open(os.path.join(REPO, "aw-app.json")) as f:
            manifest = json.load(f)
        for task in manifest["contributes"]["tasks"]:
            if task["type"] in ("agentic_output", "agent_prompt"):
                assert task.get("agent_slug", "").strip(), (
                    f"{task['name']}: would install but never fire"
                )


class TestDiscoveryPaths:
    def test_workspace_root_is_read_per_call(self, monkeypatch):
        """Captured at import, the root would freeze to whichever of the CLI /
        server / container cwds imported the module first."""
        from architecture_app import discovery

        monkeypatch.setenv("AW_WORKSPACE_CONTAINER_DIR", "/somewhere/else")
        assert discovery.workspace_root() == "/somewhere/else"

    def test_scan_returns_workspace_relative_paths(self, tmp_path, monkeypatch):
        from architecture_app import discovery

        (tmp_path / "repos" / "some-app" / "tests").mkdir(parents=True)
        (tmp_path / "repos" / "some-app" / "tests" / "test_thing.py").write_text("")
        (tmp_path / "repos" / "some-app" / "tests" / "helper.py").write_text("")
        monkeypatch.setenv("AW_WORKSPACE_CONTAINER_DIR", str(tmp_path))

        found = discovery._scan_dir(str(tmp_path / "repos" / "some-app"))
        assert found == ["repos/some-app/tests/test_thing.py"]

    def test_scan_reaches_across_repos(self, tmp_path, monkeypatch):
        """The point of re-rooting: one scan covers components living in
        different repos, which the monolith's single-checkout BASE_DIR
        couldn't express."""
        from architecture_app import discovery

        for repo in ("aw-workspace", "aw-app-tasks"):
            d = tmp_path / "repos" / repo / "tests"
            d.mkdir(parents=True)
            (d / "test_x.py").write_text("")
        monkeypatch.setenv("AW_WORKSPACE_CONTAINER_DIR", str(tmp_path))

        found = discovery._scan_dir(str(tmp_path / "repos"))
        assert found == [
            "repos/aw-app-tasks/tests/test_x.py",
            "repos/aw-workspace/tests/test_x.py",
        ]

    def test_kind_inference_unchanged(self):
        from architecture_app import discovery

        assert discovery._infer_kind("src/tests/unit/test_a.py") == "unit"
        assert discovery._infer_kind("src/tests/integration/test_a.py") == "integration"
        assert discovery._infer_kind("ui/e2e/test_a.py") == "e2e"


class TestNoCoreImports:
    """A decoupled app that imports core modules is coupled again — and the
    specific import the monolith used (`src.api.pg_db`) would give it a session
    onto a database the capability system never granted it."""

    @pytest.mark.parametrize("module", [
        "store.py", "discovery.py", "test_runner.py", "md_export.py",
        "mcp_tools.py", "routes.py", "plugin.py",
    ])
    def test_no_src_imports(self, module):
        path = os.path.join(REPO, "architecture_app", module)
        with open(path) as f:
            source = f.read()
        offenders = re.findall(r"^\s*(?:from|import)\s+src[\s.]", source, re.M)
        assert not offenders, f"{module} imports core: {offenders}"


class TestMcpSurface:
    """The 40 tools are the primary way the catalog is managed — the UI is a
    view onto it, not the editor. If the manifest doesn't declare them,
    aw-mcp-gateway serves none of them and every agent that would curate the
    namespace silently has nothing to call: the app installs green, doctor is
    happy, and the tools just aren't there. That exact shape (an app's whole
    MCP surface missing while everything reports healthy) is a documented
    failure mode of this workspace, so it gets a test."""

    def _manifest(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            return json.load(f)

    def _declared_tool_names(self):
        source = open(os.path.join(REPO, "architecture_app", "mcp_tools.py")).read()
        block = source[source.index("TOOLS = ["):]
        names = re.findall(r'\{"name": "([a-z_]+)"', block)
        return list(dict.fromkeys(names))

    def test_manifest_declares_every_tool_the_module_defines(self):
        provides = self._manifest()["contributes"]["mcp"]["provides"]
        assert set(provides) == set(self._declared_tool_names()), (
            f"manifest/code drift: only_in_manifest="
            f"{set(provides) - set(self._declared_tool_names())}, "
            f"only_in_code={set(self._declared_tool_names()) - set(provides)}"
        )

    def test_every_declared_tool_is_dispatchable(self):
        """A tool listed in TOOLS but missing from _dispatch answers
        'Unknown tool' at call time — advertised and dead."""
        source = open(os.path.join(REPO, "architecture_app", "mcp_tools.py")).read()
        dispatch = source[source.index("def _dispatch("):]
        for name in self._declared_tool_names():
            assert f'tool == "{name}"' in dispatch, f"{name} is advertised but not dispatched"


class TestGatewaySelfRegistration:
    def test_plugin_registers_itself_with_the_gateway(self):
        """contributes.mcp.provides is the marketplace's "what you get" list —
        it does NOT create a gateway upstream. That only happens when the app
        writes <package_dir>/mcp.json, which the gateway's app-scan reads. Miss
        it and the app installs green, doctor finds no degradation, /mcp answers
        by hand, and no agent is offered a single tool."""
        source = open(os.path.join(REPO, "architecture_app", "plugin.py")).read()
        assert "self_register.register_self(" in source

    def test_registered_name_matches_the_app_id(self):
        """The gateway prefixes tools with the upstream name (aw__<name>__*);
        a mismatch with the app id makes every tool answer to a name nothing
        else in the workspace uses."""
        from architecture_app import self_register

        with open(os.path.join(REPO, "aw-app.json")) as f:
            assert self_register.MCP_SERVER_NAME == json.load(f)["id"]


class TestBundleOnlyUsesClassesCoreShips:
    """An app bundle is loaded into the SPA at runtime, but the SPA's CSS was
    compiled from its OWN source — Tailwind only emitted the arbitrary-value
    utilities it saw there. A class this bundle invents resolves to no rule at
    all, and the failure is silent: `w-[240px] shrink-0` on the rail produced
    no width, so flex split the window ~50/50 and it read as a layout bug.

    This test can't see core's stylesheet (different repo, built separately),
    so it enforces the rule that makes the question moot: sizing lives in
    inline styles, and the only arbitrary-value classes allowed here are the
    CSS-variable colours, which core uses on nearly every element.
    """

    ALLOWED_ARBITRARY = re.compile(r"^\[var\(--[a-z-]+\)\]$")

    def test_no_invented_arbitrary_utilities(self):
        source = open(os.path.join(REPO, "ui", "src", "plugin.jsx")).read()
        # Only look at real className strings, not the header comment.
        offenders = set()
        for class_attr in re.findall(r'className="([^"]+)"', source):
            for cls in class_attr.split():
                m = re.search(r"\[[^\]]+\]", cls)
                if not m:
                    continue
                arg = m.group(0)
                # colour variables are fine; so is an opacity like bg-white/[0.06]
                if self.ALLOWED_ARBITRARY.match(arg) or re.match(r"^\[0?\.\d+\]$", arg):
                    continue
                offenders.add(cls)
        assert not offenders, (
            f"these classes may not exist in core's compiled CSS and would "
            f"silently do nothing — use an inline style instead: {sorted(offenders)}"
        )

    def test_rail_width_is_a_real_style(self):
        """The specific regression: the rail must carry a width no stylesheet
        has to provide."""
        source = open(os.path.join(REPO, "ui", "src", "plugin.jsx")).read()
        assert "width: RAIL_WIDTH" in source


class TestManifestMatchesTheCode:
    """A manifest that advertises something the code doesn't do is worse than
    one that advertises nothing — the user sets the knob and nothing changes."""

    def _manifest(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            return json.load(f)

    def test_every_config_key_is_read_somewhere(self):
        """`testcase_timeout_seconds` shipped in config_schema for four
        versions while run_testcase used its own default — the setting was
        editable, persisted, and inert."""
        props = self._manifest().get("config_schema", {}).get("properties", {})
        source = "".join(
            open(os.path.join(REPO, "architecture_app", f)).read()
            for f in os.listdir(os.path.join(REPO, "architecture_app"))
            if f.endswith(".py")
        )
        for key in props:
            assert key in source, f"config_schema declares {key!r} but no module reads it"

    def test_declared_icon(self):
        """Without one the Apps grid renders a generic tile."""
        assert self._manifest().get("icon")


class TestSeededTaskShape:
    """The ported task ran `.venv/aw/bin/python -m src.libs.architecture_discovery`
    against /opt/agentic-workspace — an interpreter, a module and a directory
    that don't exist in this workspace. It sat disabled for that reason. These
    pin the shape of the replacement so it can't regress into the same thing.
    """

    def _task(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            return next(t for t in json.load(f)["contributes"]["tasks"]
                        if t["name"] == "Architecture Test Discovery")

    def test_command_targets_this_workspace(self):
        cmd = self._task()["command"]
        for dead in ("/opt/agentic-workspace", ".venv/aw", "src.libs"):
            assert dead not in cmd, f"{dead} does not exist here"
        assert cmd == "aw-workspace-cli architecture discover"

    def test_keeps_the_cadence_the_ported_task_ran_at(self):
        """*/30 is what the monolith's version ran. Discovery is what keeps the
        Tests view current as tests are added; a daily scan leaves the matrix
        stale for the whole working day."""
        assert self._task()["schedules"] == [{"kind": "cron", "expr": "*/30 * * * *"}]

    def test_enabled(self):
        """Seeded tasks default disabled so an install doesn't surprise you.
        This is the documented exception: without the scan the Tests view only
        populates when someone clicks Rescan, which is the app not working
        rather than a preference. Deliberate — assert it so a later edit to
        `false` is a decision, not a drift."""
        assert self._task()["enabled"] is True

    def test_the_cli_subcommand_it_calls_exists(self):
        """The command is a string in JSON; nothing else checks it resolves."""
        source = open(os.path.join(REPO, "commands", "architecture.py")).read()
        assert 'COMMAND = "architecture"' in source
        assert 'sub == "discover"' in source


class TestCoreVersionGuard:
    """`aw-app.json`'s `dependencies` only expresses other APPS — there is no
    field for "needs aw-workspace >= X". This app genuinely does: ctx.db.session
    and ctx.db.execute_multi landed on 2026-08-15. Without a guard, an older
    workspace installs the app happily and then throws AttributeError from
    inside a request, which reads as an app bug rather than a version mismatch.
    """

    def test_bind_rejects_a_facade_without_the_methods(self):
        from architecture_app import store

        class OldFacade:            # what ctx.db looked like before 2026-08-15
            def create(self, *a): ...
            def execute(self, *a): ...

        class OldCtx:
            db = OldFacade()

        with pytest.raises(RuntimeError, match="execute_multi"):
            store.bind(OldCtx())

    def test_bind_accepts_a_current_facade(self, monkeypatch):
        from architecture_app import store

        class Facade:
            def session(self, metadata=None): ...
            def execute_multi(self, sql, names, params=None): ...

        class Ctx:
            db = Facade()

        store.bind(Ctx())
        assert store._ctx is not None
        monkeypatch.setattr(store, "_ctx", None)   # don't leak into other tests


class TestProvenance:
    """`edited_by` existed from the monolith and nothing ever read it. It is now
    the rule that lets a scan run every night without erasing what people
    write: a scan write only overwrites a row still marked 'scan'."""

    def test_scan_write_is_conditional(self):
        source = open(os.path.join(REPO, "architecture_app", "store.py")).read()
        upsert = source[source.index("def upsert_component("):source.index("_COMPONENT_FIELDS")]
        assert "where=(Component.edited_by == SCAN_PROVENANCE)" in upsert
        assert "if edited_by == SCAN_PROVENANCE else None" in upsert

    def test_curated_write_stays_unconditional(self):
        """An agent or a person must still be able to correct any row,
        including one the scan owns."""
        from architecture_app import store
        assert store.SCAN_PROVENANCE == "scan"
        source = open(os.path.join(REPO, "architecture_app", "store.py")).read()
        # the MCP tools' default provenance is NOT the scan's
        assert 'edited_by: str = "generated"' in source

    def test_list_components_projects_edited_by(self):
        """scan.py reads this to decide what to leave alone; if the projection
        drops it, every curated row silently becomes overwritable again."""
        source = open(os.path.join(REPO, "architecture_app", "store.py")).read()
        listing = source[source.index("def list_components("):source.index("def create_requirement(")]
        assert "Component.edited_by" in listing


class TestScanIsDeterministic:
    """The scan's whole claim is that it states only what a manifest states.
    The moment it starts inferring, its output stops being trustworthy and the
    catalog becomes something nobody can check."""

    def test_writes_everything_as_scan_owned(self):
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        assert "edited_by=db.SCAN_PROVENANCE" in source

    def test_core_subpackages_are_an_explicit_list(self):
        """Not `os.listdir('src')` — `tests` is not a component, and a catalog
        built from directory names is one nobody trusts."""
        from architecture_app import scan
        slugs = {s for s, *_ in scan._CORE_SUBPACKAGES}
        assert "tests" not in slugs
        assert {"apps-runtime", "workspace-cli", "workspace-api"} <= slugs

    def test_no_llm_or_network_in_the_scan(self):
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        for forbidden in ("httpx", "requests", "urllib", "openai", "anthropic"):
            assert forbidden not in source, f"scan.py reaches for {forbidden}"

    def test_tier_maps_without_guessing(self):
        from architecture_app import scan
        assert scan._TIER_LAYER["inprocess"] == "app"
        assert scan._TIER_LAYER["container"] == "app-container"

    def test_connection_targets_exist_as_components(self):
        """Every derived edge points at a slug the scan itself creates —
        otherwise create_connection raises for a component that isn't there."""
        from architecture_app import scan
        infra = {c["slug"] for c in scan._INFRA}
        assert {"postgres", "mcp-gateway"} <= infra


class TestScanTaskShape:
    def _tasks(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            return {t["name"]: t for t in json.load(f)["contributes"]["tasks"]}

    def test_both_scans_are_seeded(self):
        names = self._tasks()
        assert "Architecture Workspace Scan" in names
        assert "Architecture Test Discovery" in names

    def test_scan_runs_less_often_than_discovery(self):
        """A manifest changes when an app is installed or updated — rare. Test
        files change all day. Same cadence for both would be pure noise."""
        t = self._tasks()
        assert t["Architecture Workspace Scan"]["schedules"][0]["kind"] == "daily"
        assert t["Architecture Test Discovery"]["schedules"][0]["expr"] == "*/30 * * * *"

    def test_scan_task_names_an_agent(self):
        assert self._tasks()["Architecture Workspace Scan"]["agent_slug"]

    def test_components_are_created_before_any_edge(self):
        """create_connection resolves both endpoints by slug and raises if one
        is missing, so an interleaved single pass silently drops every
        forward-referencing dependency edge — the scan then converges only on
        the SECOND run. Observed live: 44 edges, then 49."""
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        body = source[source.index("def scan_workspace("):]
        assert body.index("pass 1") < body.index("pass 2")
        # every edge write happens after the component loop has finished
        assert body.index("pending.append(") < body.index("db.create_connection(")

    def test_the_summary_counts_only_what_was_written(self):
        """`created_components += 1` outside the `if put(...)` reported writes
        that the provenance rule had just refused — the scan claimed 33 while
        writing 29."""
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        body = source[source.index("def scan_workspace("):]
        for line_no, line in enumerate(body.splitlines()):
            if "created_components += 1" in line:
                indent = len(line) - len(line.lstrip())
                prev = [l for l in body.splitlines()[:line_no] if l.strip()][-1]
                assert "put(" in prev or "if put" in prev or indent > 4, (
                    f"unconditional increment: {line!r}"
                )

    def test_plain_repos_get_nothing_invented(self):
        """A bare checkout can only be described in its own words. This used to
        assert that the block passed no description or layer AT ALL, which was a
        proxy for "nothing is invented" back when the only alternative to null
        was a placeholder. Both are derived now, so the invariant is asserted
        where it actually lives: the values come from `_declared`, never from a
        literal in the loop, and `_declared` reads declarations rather than
        guessing (see TestPlainReposDescribeThemselves)."""
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        block = source[source.index("for repo_dir in _plain_repo_dirs():"):
                       source.index("# ---- pass 1")]
        assert "_declared(repo_dir)" in block
        assert "description=description" in block
        assert "layer=layer" in block
        # No hardcoded prose or category reaching the catalog from here.
        assert 'description="' not in block and "description='" not in block
        assert 'layer="' not in block and "layer='" not in block

    def test_plain_repo_detection_requires_a_git_checkout(self):
        """`repos/` also holds scratch directories; a folder is not a repo."""
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        fn = source[source.index("def _plain_repo_dirs("):source.index("#: extension -> technology")]
        assert '".git"' in fn

    def test_tech_detection_does_not_walk_the_whole_tree(self):
        """A 40k-file repo must not make the nightly scan expensive."""
        source = open(os.path.join(REPO, "architecture_app", "scan.py")).read()
        fn = source[source.index("def _detect_tech("):source.index("def _plain_test_paths(")]
        assert "os.walk" not in fn


class TestDeclaresWhatItTouches:
    def _manifest(self):
        with open(os.path.join(REPO, "aw-app.json")) as f:
            return json.load(f)

    def test_declares_fs_workspace_read(self):
        """scan.py walks repos/, discovery walks every test_base_path and
        md_export writes docs/architecture/ — none of it under this app's own
        data dir, so the manifest was not a description of what the app
        touches.

        Declaring it is only safe once BOTH validators ship the capability:
        the running workspace (>= v0.1.64) and aw-backend's mirror, which the
        cloud registry grants from. Declaring it early once took the app
        offline — `marketplace --update` is uninstall+install, so a refused
        install leaves nothing running. Both shipped 2026-08-16."""
        assert "fs:workspace-read" in self._manifest()["permissions"]

    def test_declares_the_core_version_it_needs(self):
        """store.bind() hand-rolls this check because the manifest had no way
        to say it. It does now — the guard stays as the runtime backstop, the
        manifest stops install on an old workspace in the first place."""
        assert self._manifest()["runtime"]["requires_workspace"]


class TestScanDoesNotBlankWhatItDoesNotDerive:
    """Setting `test_cmd` by hand used to survive until 05:00. upsert_component
    wrote EVERY column from its arguments, so the nightly scan — which has no
    opinion about test_cmd — blanked it, silently, every night. Reproduced
    live before fixing: PROBE-123 in, None out after one scan."""

    def test_omitted_columns_are_not_in_the_update(self):
        source = open(os.path.join(REPO, "architecture_app", "store.py")).read()
        fn = source[source.index("def upsert_component("):source.index("_COMPONENT_FIELDS")]
        # the update set is built from what was supplied, not a fixed list
        assert "updates = {k: getattr(stmt.excluded, k) for k in values" in fn
        assert "is not _UNSET" in fn

    def test_sentinel_distinguishes_none_from_omitted(self):
        from architecture_app import store
        import inspect
        sig = inspect.signature(store.upsert_component)
        for name in ("repo", "layer", "description", "test_cmd", "test_base_path"):
            assert sig.parameters[name].default is store._UNSET, name

    def test_mcp_create_component_forwards_only_what_was_sent(self):
        """`a.get(field)` for every field turned "I didn't mention layer" into
        "set layer to NULL", making create_component destructive on an
        existing slug."""
        source = open(os.path.join(REPO, "architecture_app", "mcp_tools.py")).read()
        branch = source[source.index('if tool == "create_component":'):
                        source.index('if tool == "update_component":')]
        assert "for k in optional if k in a" in branch


class TestTestCommandFallback:
    """Discovery finds hundreds of files; nobody registers a run_command on
    each. `Component.test_cmd` existed in the schema from the monolith and was
    never read — one fact per repo instead of one per file."""

    def test_component_test_cmd_is_used(self):
        from architecture_app.test_runner import _component_command
        tc = {"component_test_cmd": "pytest", "component_repo": "aw-backend"}
        assert _component_command(tc, "repos/aw-backend/src/tests/x.py") == \
            "pytest repos/aw-backend/src/tests/x.py"

    def test_file_placeholder(self):
        from architecture_app.test_runner import _component_command
        tc = {"component_test_cmd": "uv run pytest {file} -q", "component_repo": "x"}
        assert _component_command(tc, "repos/x/t.py") == "uv run pytest repos/x/t.py -q"

    def test_rel_placeholder_is_relative_to_the_repo(self):
        """What a command that cd's into the repo needs."""
        from architecture_app.test_runner import _component_command
        tc = {"component_test_cmd": "cd repos/aw-backend && pytest {rel}",
              "component_repo": "aw-backend"}
        assert _component_command(tc, "repos/aw-backend/src/tests/x.py") == \
            "cd repos/aw-backend && pytest src/tests/x.py"

    def test_no_template_is_no_command(self):
        from architecture_app.test_runner import _component_command
        assert _component_command({"component_test_cmd": "  "}, "x.py") is None
        assert _component_command({}, "x.py") is None

    def test_explicit_run_command_still_wins(self):
        source = open(os.path.join(REPO, "architecture_app", "test_runner.py")).read()
        assert "run_command = explicit or _component_command(" in source


class TestDocsLiveWithTheirRepo:
    """An app's architecture doc in repos/<app>/docs/ is committed with that
    app and survives an uninstall/reinstall. The same file in the workspace's
    tree is orphaned the moment the app is removed, and then describes
    something that no longer exists."""

    # A fake workspace tree, not this machine's. The first cut of these asserted
    # against the real repos/ dir and passed locally while failing in CI, where
    # nothing is checked out — a test that only passes where it was written.

    @pytest.fixture()
    def fake_ws(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AW_WORKSPACE_CONTAINER_DIR", str(tmp_path))
        (tmp_path / "repos" / "aw-app-something").mkdir(parents=True)
        return tmp_path

    def test_app_component_routes_to_its_own_repo(self, fake_ws):
        from architecture_app import md_export
        d = md_export.dir_for_component({"repo": "aw-app-something"})
        assert d == str(fake_ws / "repos" / "aw-app-something" / "docs" / "architecture")

    def test_generic_component_stays_in_the_workspace(self, fake_ws):
        from architecture_app import md_export
        for comp in ({"repo": None}, {"repo": "aw-workspace"}, {}, None):
            assert md_export.dir_for_component(comp) == md_export.arch_dir()

    def test_unchecked_out_repo_falls_back_rather_than_failing(self, fake_ws):
        """A doc in a slightly odd place beats no doc — and beats a crash in
        the nightly regeneration."""
        from architecture_app import md_export
        assert md_export.dir_for_component(
            {"repo": "definitely-not-cloned-here"}) == md_export.arch_dir()

    def test_prune_only_removes_generated_files(self):
        """Docs now land in repos that also hold hand-written ADRs. Deleting
        one of those would be unrecoverable from here."""
        source = open(os.path.join(REPO, "architecture_app", "md_export.py")).read()
        fn = source[source.index("def regenerate_all("):]
        assert '"source: generated" not in head' in fn


class TestUnknownPathIsNotAServerError:
    """POSTing a file_path with no testcase row returned a bare 500: the runner
    called update_testcase_result, which raises for a row that isn't there.
    "You asked for something I don't know about" is a client error — a 500
    sends whoever hit it hunting for a crash that doesn't exist."""

    def test_route_translates_valueerror_to_404(self):
        source = open(os.path.join(REPO, "architecture_app", "routes.py")).read()
        branch = source[source.index("async def run_testcase_route("):
                        source.index("async def run_discovery_route(")]
        assert "except ValueError" in branch
        assert "status_code=404" in branch

    def test_runner_does_not_record_against_a_missing_row(self):
        source = open(os.path.join(REPO, "architecture_app", "test_runner.py")).read()
        assert "if testcase:\n                db.update_testcase_result" in source

    def test_prune_also_removes_a_doc_left_in_the_wrong_repo(self):
        """A doc goes stale two ways now: its component vanished, or its
        component moved repos and this copy is a leftover. Checking only the
        first left every pre-move copy sitting in the workspace tree — two
        files for one component, one of them wrong, and no error anywhere."""
        source = open(os.path.join(REPO, "architecture_app", "md_export.py")).read()
        fn = source[source.index("def regenerate_all("):]
        assert "dir_for_component(components.get(slug)) == d" in fn


class TestExitCodeClassification:
    """pytest exit 4 (usage) and 5 (nothing collected) mean the suite never
    ran. Recording those as `fail` states something false about code that may
    be perfectly fine — and the nuance used to apply only to the built-in
    fallback, so any component with its own test_cmd got a red mark instead.
    Seen live on aw-app-mini-browser ("ERROR collecting test session") and
    aw-app-crispal ("1 skipped")."""

    def test_zero_is_passing(self):
        from architecture_app.test_runner import _classify
        assert _classify(0, "anything") == "passing"

    def test_pytest_one_is_a_real_failure(self):
        from architecture_app.test_runner import _classify
        assert _classify(1, "python -m pytest x.py") == "fail"

    def test_pytest_collection_errors_are_unknown_whatever_supplied_the_command(self):
        """2 is what a test module's ImportError actually exits with (measured
        on aw-app-mini-browser, which needs an `mcp` package this container
        doesn't have). Marking that "fail" is a false negative on a suite that
        is probably green wherever its deps exist."""
        from architecture_app.test_runner import _classify
        for rc in (2, 4, 5):
            assert _classify(rc, "cd repos/x && python3 -m pytest y.py -q") == "unknown"
            assert _classify(rc, "python -m pytest y.py") == "unknown"

    def test_a_non_pytest_runner_keeps_plain_semantics(self):
        """No claim is made about another runner's exit codes — anything
        non-zero is a failure until someone documents otherwise."""
        from architecture_app.test_runner import _classify
        assert _classify(5, "xcodebuild test -scheme Watch") == "fail"

    def test_list_components_projects_test_cmd(self):
        source = open(os.path.join(REPO, "architecture_app", "store.py")).read()
        listing = source[source.index("def list_components("):source.index("def create_requirement(")]
        assert "Component.test_cmd" in listing


class TestNotRunnableIsRecordedNotHidden:
    """The wrong answer to "this environment can't run that test", tried once
    on 2026-08-17: narrow the component's test_base_path until the row
    disappears. That deletes a real test from the catalog to make a dashboard
    green, throws away any curated run_command / is_flaky / requirement link on
    it, and turns the coverage count into a lie. 48 rows went that way and had
    to be restored.

    `SKIP: <reason>` keeps the row, keeps the reason, and survives rescans
    because upsert_testcase never clobbers run_command."""

    def test_skip_prefix_yields_not_runnable(self):
        from architecture_app import test_runner
        assert test_runner.SKIP_PREFIX == "SKIP:"
        source = open(os.path.join(REPO, "architecture_app", "test_runner.py")).read()
        assert 'explicit.startswith(SKIP_PREFIX)' in source
        assert '"status": "not_runnable"' in source

    def test_a_skipped_test_does_not_overwrite_its_last_result(self):
        """Choosing not to run something says nothing about whether it passes.
        Recording `unknown` would erase a real verdict from when it last ran
        somewhere that could."""
        source = open(os.path.join(REPO, "architecture_app", "test_runner.py")).read()
        skip_branch = source[source.index("if explicit.startswith(SKIP_PREFIX):"):
                             source.index("run_command = explicit or")]
        assert "update_testcase_result" not in skip_branch


class TestComponentHealthRollsUp:
    """A parent read `planned` while a child sat `broken`. The tree exists so a
    glance at the root tells you whether anything underneath is on fire; the
    un-rolled view made the root the least informative row in it."""

    def _view(self):
        return store._VIEWS[store._VIEWS.index("v_component_health"):]

    def test_the_view_walks_the_subtree(self):
        v = self._view()
        assert "WITH RECURSIVE subtree" in v
        assert "c.parent_id = s.node_id" in v
        assert "GROUP BY s.root_id" in v

    def test_requirements_are_joined_on_the_subtree_not_the_component(self):
        """Joining on c.id again would walk the tree and then ignore it."""
        v = self._view()
        assert "r.component_id = s.node_id" in v

    def test_there_is_a_cycle_guard(self):
        """parent_id is a self-referencing FK with nothing preventing
        a -> b -> a, and WITH RECURSIVE over a cycle does not terminate. One
        bad row would hang every query touching component health, including
        the window's first paint."""
        v = self._view()
        assert re.search(r"WHERE\s+s\.depth\s*<\s*\d+", v), "no depth bound on the recursion"

    def test_broken_still_wins_over_implemented(self):
        """Order matters: a subtree with one broken and many implemented
        requirements must read broken, not partial."""
        v = self._view()
        broken = v.index("'broken'")
        implemented = v.index("bool_and(h.health = 'implemented')")
        assert broken < implemented


class TestRunsDoNotHoldTheRequest:
    """`POST /testcases/run` blocked until pytest finished. The tunnel edge
    cuts at ~30s, so a slow pass came back to the browser as "502 workspace
    offline" — indistinguishable from a dead workspace — while a Starlette
    threadpool worker, shared with every other route in the workspace, sat
    occupied for the whole run."""

    def test_async_is_the_default(self):
        source = open(os.path.join(REPO, "architecture_app", "routes.py")).read()
        assert "wait: bool = False" in source
        assert "if not body.wait:" in source
        assert "jobs.start(" in source

    def test_the_cli_still_blocks(self):
        """Loopback has no edge timeout, and a script that must poll for its
        own exit code is worse than one that waits."""
        cli = open(os.path.join(REPO, "commands", "architecture.py")).read()
        assert '"wait": True' in cli

    def test_concurrency_is_bounded(self):
        """run_component_tests loops over every test linked to a component. A
        component with 77 of them would otherwise fork 77 pytest processes back
        to back with nothing bounding it."""
        from architecture_app import jobs
        assert jobs.MAX_CONCURRENT >= 1
        source = open(os.path.join(REPO, "architecture_app", "jobs.py")).read()
        assert "_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT)" in source
        assert "with _SEMAPHORE:" in source

    def test_the_job_id_comes_back_before_a_slot_is_taken(self):
        """Acquiring the semaphore in the caller would make `start` block
        exactly when both slots are busy — the one case the caller most needs
        an id back."""
        source = open(os.path.join(REPO, "architecture_app", "jobs.py")).read()
        work = source[source.index("def _work()"):]
        start = source[source.index("def start("):source.index("def _work()")]
        assert "with _SEMAPHORE:" in work and "with _SEMAPHORE:" not in start

    def test_finished_jobs_are_reaped(self):
        """In-process dict in a process that runs for weeks."""
        source = open(os.path.join(REPO, "architecture_app", "jobs.py")).read()
        assert "_reap(now)" in source

    def test_a_real_run_reports_through_a_job(self):
        from architecture_app import jobs
        import time
        # The run is held open so "start returned before the work finished" is
        # asserted rather than raced on: a trivial callable can complete between
        # start() returning and the next line, which would make the assertion
        # pass or fail on timing.
        release = threading.Event()
        def held(fp):
            release.wait(10)
            return {"file_path": fp, "status": "passing"}
        job = jobs.start("x/y.py", held)
        assert job["id"].startswith("run-")
        assert job["status"] in ("queued", "running")
        assert jobs.get(job["id"])["result"] is None
        release.set()
        for _ in range(50):
            j = jobs.get(job["id"])
            if j["status"] == "done":
                break
            time.sleep(0.05)
        assert jobs.get(job["id"])["result"]["status"] == "passing"

    def test_a_raising_run_becomes_an_error_not_a_lost_job(self):
        from architecture_app import jobs
        import time
        def boom(_fp):
            raise ValueError("no such testcase")
        job = jobs.start("nope.py", boom)
        for _ in range(50):
            if jobs.get(job["id"])["status"] == "done":
                break
            time.sleep(0.05)
        j = jobs.get(job["id"])
        assert j["status"] == "done"
        assert "no such testcase" in j["error"]
        assert j["result"] is None


class TestPlainReposDescribeThemselves:
    """A checked-out repo with no aw-app.json used to land in the catalog with
    a null description and a null layer — 13 of 54 components, showing as
    blanks in the tree with nothing to say why."""

    _n = 0

    def _decl(self, tmp_path, files):
        TestPlainReposDescribeThemselves._n += 1
        repo = tmp_path / f"some-repo-{self._n}"
        repo.mkdir()
        for name, body in files.items():
            (repo / name).write_text(body)
        from architecture_app import scan
        return scan._declared(str(repo))

    def test_a_declaration_file_wins(self, tmp_path):
        desc, layer = self._decl(tmp_path, {
            ".aw-component.json": '{"layer": "backend", "description": "Declared."}',
            "package.json": '{"description": "From npm."}',
        })
        assert (desc, layer) == ("Declared.", "backend")

    def test_package_json_then_pyproject_then_readme(self, tmp_path):
        assert self._decl(tmp_path, {
            "package.json": '{"description": "The node one."}'})[0] == "The node one."
        assert self._decl(tmp_path, {
            "pyproject.toml": '[project]\ndescription = "The python one."\n'})[0] == "The python one."
        assert self._decl(tmp_path, {
            "README.md": "# repo\n\nThe readme one, long enough to count.\n"})[0] \
            == "The readme one, long enough to count."

    def test_the_readme_paragraph_skips_badges_and_headings(self, tmp_path):
        desc, _ = self._decl(tmp_path, {"README.md":
            "# resume\n\n"
            "[![Deploy](https://img.shields.io/x.svg)](https://example.test/a)\n\n"
            "Professional academic resume with an interactive HTML version.\n\n"
            "## Usage\n"})
        assert desc == "Professional academic resume with an interactive HTML version."

    def test_inline_links_collapse_to_their_text(self, tmp_path):
        desc, _ = self._decl(tmp_path, {"README.md":
            "# x\n\nThe BYOD client for [Agentic Workspace](https://aw.example.test) "
            "you run yourself.\n"})
        assert "https://" not in desc
        assert "Agentic Workspace" in desc

    def test_layer_is_never_guessed(self, tmp_path):
        """description has three honest sources; layer has exactly one. A repo
        that hasn't said keeps a null layer rather than being sorted into a
        category by whatever files happen to be lying around."""
        _, layer = self._decl(tmp_path, {
            "package.json": '{"description": "A react app."}',
            "README.md": "# x\n\nA frontend, obviously.\n"})
        assert layer is None

    def test_an_unknown_layer_is_refused_not_stored(self, tmp_path):
        """A typo would otherwise create a fourteenth category containing one
        component, which reads as a real distinction."""
        _, layer = self._decl(tmp_path, {
            ".aw-component.json": '{"layer": "backendd"}'})
        assert layer is None

    def test_an_essay_is_not_a_description(self, tmp_path):
        desc, _ = self._decl(tmp_path, {"README.md": "# x\n\n" + "word " * 400})
        assert len(desc) <= 400

    def test_nothing_to_read_stays_null(self, tmp_path):
        assert self._decl(tmp_path, {}) == (None, None)

    def test_broken_json_does_not_stop_the_scan(self, tmp_path):
        desc, layer = self._decl(tmp_path, {
            ".aw-component.json": "{not json",
            "README.md": "# x\n\nStill describes itself just fine.\n"})
        assert desc == "Still describes itself just fine."
        assert layer is None

    def test_the_real_repos_now_resolve(self):
        """The point of the exercise — these were the null ones."""
        from architecture_app import scan
        root = os.path.join(scan.workspace_root(), "repos")
        for repo, layer in [("aw-backend", "backend"), ("aw-workspace-ui", "frontend"),
                            ("aw-mobile", "mobile"), ("aw-remote-host", "cli")]:
            path = os.path.join(root, repo)
            if not os.path.isdir(path):
                continue                      # not every checkout has every repo
            desc, got = scan._declared(path)
            assert got == layer, f"{repo}: {got!r}"
            assert desc, f"{repo} has no description"
