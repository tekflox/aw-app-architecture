"""Test dependencies — declared in the repo, installed into a venv of its own.

The problem this closes: a suite that needs one extra package reports as a
*collection error*, pytest exits 2, the runner correctly refuses to call that a
failure, and the test sits at `unknown` forever. Nothing says which package,
nothing installs it, and the fix — `pip install <thing>` into the workspace
venv by hand — dies with the next container recreation. On 2026-08-17 that was
76 aw-backend testcases blocked on `watchfiles` and 3 aw-console ones blocked
on `pytest-playwright`, both of which the repos **already declare**. Nothing
read the declarations.

Two decisions worth stating, because the obvious alternatives are worse.

**Declared in the repo, not in the database.** A component row can hold a
`test_cmd`, so it could hold a dependency list too — and it would vanish with
the next workspace rebuild, exactly like the manual pip install it replaces.
`.aw-component.json` (the same file that carries `layer`) names requirements
files, which live in the repo and are already maintained by whoever maintains
the tests. Conventional locations are found without any declaration at all.

**A venv per component, never the workspace's own.** aw-backend's requirements
file pins 152 packages. Installing that into the venv this workspace *runs on*
would let pip resolve upgrades of packages the workspace itself depends on, to
satisfy a test suite — trading a broken test for a broken workspace. Each
component instead gets `.aw-workspace/test-venvs/<slug>/`, which is under
``AW_WORKSPACE_HOME`` and therefore host-mounted, so it survives container
recreation; and `--check` can answer "what is missing" without installing
anything at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from . import store as db
from .discovery import workspace_root

#: Where a component may declare the requirements files its tests need:
#: ``{"test_requires": ["src/setup/requirements/aw.requirements.txt"]}``.
#: Same file that carries ``layer`` — a repo describing itself in one place.
DECL_FILE = ".aw-component.json"

#: Found without any declaration. Repo-relative, in priority order. Anything
#: else needs `test_requires`, deliberately: guessing which of a repo's twelve
#: requirements files is the test one produces installs nobody asked for.
CONVENTIONAL = ("requirements-dev.txt", "requirements-test.txt")

#: Per-component venvs live here. Under AW_WORKSPACE_HOME, which is
#: host-mounted, so they outlive the container that built them.
VENV_ROOT = os.path.join(".aw-workspace", "test-venvs")

#: How long a single pip install may take. A cold numpy build on ARM is
#: minutes, not seconds, and a provision that gets killed halfway leaves a venv
#: that looks present and isn't.
PIP_TIMEOUT_S = 900


def _repo_dir(repo: str) -> str:
    return os.path.join(workspace_root(), "repos", repo)


def requirement_files(repo: str) -> list[str]:
    """Requirements files this repo offers for its tests, repo-relative.

    Declared first, conventional second. A declared path that doesn't exist is
    reported by `check`, not silently dropped — a typo in a declaration should
    be visible, since its whole purpose is to be read by something other than
    a human.
    """
    root = _repo_dir(repo)
    decl_path = os.path.join(root, DECL_FILE)
    declared: list[str] = []
    try:
        with open(decl_path) as f:
            data = json.load(f)
        raw = data.get("test_requires") or []
        if isinstance(raw, str):
            raw = [raw]
        declared = [str(p) for p in raw]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    if declared:
        return declared
    return [name for name in CONVENTIONAL
            if os.path.isfile(os.path.join(root, name))]


def venv_dir(slug: str) -> str:
    return os.path.join(workspace_root(), VENV_ROOT, slug)


def venv_python(slug: str) -> str:
    return os.path.join(venv_dir(slug), "bin", "python")


def _components_with_requirements() -> list[dict[str, Any]]:
    """Components whose repo offers a requirements file. Only ones that have
    testcases: provisioning a venv for a component nothing will ever run is
    pure cost."""
    out = []
    for c in db.list_components():
        repo = c.get("repo")
        if not repo or not os.path.isdir(_repo_dir(repo)):
            continue
        files = requirement_files(repo)
        if files:
            out.append({**c, "requirement_files": files})
    return out


def check() -> dict[str, Any]:
    """What is declared, what is provisioned, what is missing — installs
    nothing. This is the shape `doctor` wants: this workspace's failure mode is
    silent degradation, and "a suite that cannot collect" is exactly that."""
    rows = []
    for c in _components_with_requirements():
        slug, repo = c["slug"], c["repo"]
        root = _repo_dir(repo)
        missing_files = [f for f in c["requirement_files"]
                         if not os.path.isfile(os.path.join(root, f))]
        rows.append({
            "component": slug,
            "repo": repo,
            "requirement_files": c["requirement_files"],
            "missing_requirement_files": missing_files,
            "venv": venv_dir(slug),
            "provisioned": os.path.isfile(venv_python(slug)),
        })
    pending = [r for r in rows if not r["provisioned"] or r["missing_requirement_files"]]
    return {"components": rows, "pending": [r["component"] for r in pending],
            "ok": not pending}


def provision(slug: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Build (or refresh) the per-component test venvs.

    Idempotent: an existing venv is reused and pip is asked to install again,
    which is a no-op when everything is already satisfied. `force` recreates
    from scratch, for the case a half-finished install left one wedged.
    """
    results = []
    for c in _components_with_requirements():
        if slug and c["slug"] != slug:
            continue
        results.append(_provision_one(c, force=force))
    return {"provisioned": results,
            "ok": all(r["ok"] for r in results) if results else True}


def _provision_one(component: dict, *, force: bool) -> dict[str, Any]:
    slug, repo = component["slug"], component["repo"]
    root = _repo_dir(repo)
    target = venv_dir(slug)
    python = venv_python(slug)

    files = [f for f in component["requirement_files"]
             if os.path.isfile(os.path.join(root, f))]
    if not files:
        return {"component": slug, "ok": False,
                "error": f"declared requirements file(s) not found in {repo}: "
                         f"{', '.join(component['requirement_files'])}"}

    if force and os.path.isdir(target):
        import shutil
        shutil.rmtree(target, ignore_errors=True)

    if not os.path.isfile(python):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # --system-site-packages so a component only pays for what it adds on
        # top of the workspace's interpreter. Without it every venv re-downloads
        # fastapi/pydantic/sqlalchemy, which is minutes and hundreds of MB per
        # component for packages that are already right there.
        rc, out = _run([sys.executable, "-m", "venv", "--system-site-packages", target])
        if rc != 0:
            return {"component": slug, "ok": False, "error": f"venv: {out[-600:]}"}

    cmd = [python, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    for f in files:
        cmd += ["-r", os.path.join(root, f)]
    rc, out = _run(cmd)
    if rc != 0:
        return {"component": slug, "ok": False, "files": files,
                "error": out[-1200:]}

    # Point the component at its own interpreter. The runner already renders
    # component.test_cmd per file, so this is all it takes for the play button
    # and run_component_tests to start using the venv.
    template = f"cd repos/{repo} && {python} -m pytest {{rel}}"
    db.upsert_component(slug=slug, name=component.get("name") or slug,
                        test_cmd=template)
    return {"component": slug, "ok": True, "files": files, "test_cmd": template}


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=PIP_TIMEOUT_S)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {PIP_TIMEOUT_S}s: {' '.join(cmd[:4])}…"
    except OSError as exc:
        return 1, str(exc)
