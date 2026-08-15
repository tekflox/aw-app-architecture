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
        task = manifest["contributes"]["tasks"][0]
        assert task["name"] == "Architecture Test Discovery"
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
            return json.load(f)["contributes"]["tasks"][0]

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
