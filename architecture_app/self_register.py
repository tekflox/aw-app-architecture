"""Write this app's own ``mcp.json`` so aw-mcp-gateway's app-scan
(``scan_app_mcp_servers()``, reading ``<installed-app-dir>/mcp.json``)
discovers the ``/mcp`` endpoint in ``routes.py`` without any manual wiring.

Mirrors ``aw-app-whiteboard``'s ``whiteboard_app/mcp/self_register.py`` and
``aw-app-kb``'s ``kb_app/self_register.py``.

**This is not optional plumbing.** Declaring ``contributes.mcp.provides`` in
the manifest is what the marketplace shows a user under "what you get"; it does
NOT register an upstream. Without this file the app installs clean, `doctor`
reports no degradation, the ``/mcp`` route answers correctly if you call it by
hand — and the gateway serves none of the 40 tools, so every agent that would
curate the namespace has nothing to call. That gap is invisible from every
surface except the gateway's own upstream list, which is how it went unnoticed
here until the tool list was checked directly.

Tier-1 vs Tier-2: a Tier-2 app is its own container and needs
``AW_APP_SELF_HOST`` to tell siblings its network alias. This app is Tier-1 —
it IS the aw-workspace process, so ``socket.gethostname()`` returns exactly the
value ``ContainerSupervisor`` injects into sibling containers as
``AW_WORKSPACE_HOST``. No extra env var.

Tier-1 routes are IdentityGuard-gated, so the registered entry carries
``X-Api-Key`` for the gateway's ``HttpUpstream`` to authenticate with.
"""

from __future__ import annotations

import json
import logging
import os
import socket

log = logging.getLogger("aw_apps.architecture")

MCP_SERVER_NAME = "architecture"


def _mcp_json_path(package_dir: str) -> str:
    return os.path.join(package_dir, "mcp.json")


def register_self(package_dir: str, port: int) -> None:
    """Best-effort; a bare dev run with no package_dir on a scanned root
    simply no-ops (nothing to write into, nothing breaks)."""
    if not os.path.isdir(package_dir):
        return

    host = socket.gethostname()
    api_key = os.environ.get("AW_WORKSPACE_API_KEY")
    entry: dict = {
        "type": "http",
        "url": f"http://{host}:{port}/api/apps/architecture/mcp",
        "enabled": True,
    }
    if api_key:
        entry["headers"] = {"X-Api-Key": api_key}

    path = _mcp_json_path(package_dir)
    data: dict = {"mcpServers": {}}
    try:
        with open(path) as f:
            existing = json.load(f)
        if isinstance(existing, dict) and isinstance(existing.get("mcpServers"), dict):
            data = existing
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Rewriting an identical entry would churn the file's mtime on every boot,
    # and the gateway reloads on change — a no-op write becomes a reload loop.
    if data["mcpServers"].get(MCP_SERVER_NAME) == entry:
        return
    data["mcpServers"][MCP_SERVER_NAME] = entry
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        log.info("registered self as %r in %s (%s)", MCP_SERVER_NAME, path, entry["url"])
    except OSError as e:
        log.warning("could not write %s: %s", path, e)
