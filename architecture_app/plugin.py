"""Entrypoint referenced by aw-app.json's runtime.entrypoint
("architecture_app.plugin:ArchitectureAppPlugin").

Three things happen on activate, in this order, and the order matters:

1. ``store.bind(ctx)`` — hands the store its ``ctx.db`` handle. Nothing below
   can touch a table before this; the store raises rather than falling back to
   some other engine, because a store that quietly wrote to the wrong database
   is precisely the silent-degradation failure this workspace keeps hitting.
2. ``store.ensure_schema()`` — idempotent create of the eight tables plus the
   two derived-health VIEWs. Safe to re-run: the reconciler calls activate on
   every boot and on every workspace recreation.
3. ``ctx.routes.register(...)`` — mounts the sub-app (REST + the in-process
   MCP endpoint) at ``/api/apps/architecture`` behind the runtime's
   IdentityGuard.

``ensure_schema`` failing is NOT fatal to activation. Postgres may still be
starting when apps reconcile; it already retries internally, and an app that
refuses to activate would also take its routes and its UI down, turning a
transient database delay into a missing window. The failure is logged loudly
and the first request surfaces it.
"""

from __future__ import annotations

import logging
import os

from . import routes as routes_mod
from . import self_register
from . import store

log = logging.getLogger("aw_apps.architecture")


class ArchitectureAppPlugin:
    async def activate(self, ctx) -> None:
        store.bind(ctx)

        try:
            store.ensure_schema()
            log.info("architecture: schema ensured (8 tables + 2 health views)")
        except Exception as exc:
            log.error(
                "architecture: schema bootstrap failed — the app is up but every "
                "data call will fail until this is resolved: %s", exc,
            )

        ctx.routes.register(routes_mod.build_routes())

        # Discoverable by aw-mcp-gateway's app-scan — see self_register.py for
        # why the manifest's contributes.mcp block is NOT what registers the
        # upstream (it's the marketplace's "what you get" list). Without this
        # the app is green everywhere and the 40 tools reach no agent.
        port = int(os.environ.get("AW_PORT", "9030"))
        self_register.register_self(ctx.package_dir, port)

        log.info("architecture activated: routes mounted at /api/apps/architecture")

    async def deactivate(self) -> None:
        # Tables are deliberately NOT dropped — the runtime stopped
        # auto-dropping app tables on unload (uninstall+install is the upgrade
        # path for a version bump, so dropping here wiped data on every routine
        # update). Nothing to undo.
        log.info("architecture deactivated")
