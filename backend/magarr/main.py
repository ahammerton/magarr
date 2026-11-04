from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from magarr import APP_NAME, __version__
from magarr.api import (
    activity,
    automation,
    downloadclients,
    frontend,
    indexers,
    issues,
    library,
    magazines,
    manualimport,
    media,
    naming,
    notifications,
    qualityprofiles,
    rootfolders,
    system,
    systempages,
)
from magarr.api.errors import install_error_handlers
from magarr.core.auth import make_auth_middleware
from magarr.core.config import Settings, load_settings
from magarr.core.db import (
    create_db_engine,
    create_session_factory,
    current_revision,
    run_migrations,
    sqlite_path,
)
from magarr.core.events import EventBus
from magarr.core.headers import SecurityHeaders
from magarr.core.limits import BodySizeLimit
from magarr.core.logging import setup_logging
from magarr.domain.backups import apply_staged_restore
from magarr.domain.seed import seed_defaults
from magarr.indexers.runtime import IndexerRuntime
from magarr.notifications import dispatch
from magarr.pipeline.automation import Automation, BackupTarget
from magarr.pipeline.tracking import run_poller

logger = logging.getLogger("magarr")


API_DESCRIPTION = """Self-hosted magazine PVR. Everything the web UI does goes through this API.

**Authentication**: send the API key (`auth.api_key` in config.yaml) as an `X-Api-Key` header,
or as `?apikey=` in the URL. With basic auth on, basic credentials are accepted too.

**Conventions**: JSON with camelCase names; errors are `{"message": "..."}`. Lists that can grow
take optional `page` and `pageSize` (at most 1000) and report the total in `X-Total-Count`.
Request bodies are limited to 1 MiB (CSV import 6 MiB; backup upload 2 GiB).
"""


def create_app(settings: Settings | None = None, frontend_dist: Path | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings)

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting %s %s", APP_NAME, __version__, extra={"config_dir": str(settings.config_dir)}
        )
        run_migrations(engine)
        app.state.db_revision = current_revision(engine)
        with session_factory() as session:
            seed_defaults(session)
        database = sqlite_path(settings.database_url)
        automation = app.state.automation = Automation(
            session_factory,
            app.state.indexer_runtime,
            app.state.events,
            minute_seconds=settings.automation.minute_seconds,
            health_checks=True,
            backups=BackupTarget(settings.config_dir, database) if database else None,
            poll_seconds=settings.downloads.poll_interval,
        )
        poller = asyncio.create_task(
            run_poller(
                session_factory,
                app.state.indexer_runtime,
                settings.downloads.poll_interval,
                app.state.events,
                on_poll=automation.record_poll,
            ),
            name="download-poller",
        )
        scheduler = asyncio.create_task(
            automation.run(settings.automation.tick_seconds), name="automation"
        )
        notifier = app.state.notifications = dispatch.Dispatcher(
            session_factory, app.state.indexer_runtime.http
        )
        dispatch.install(notifier)
        sender = asyncio.create_task(notifier.run(), name="notifications")
        yield
        dispatch.install(None)
        for task in (poller, scheduler, sender):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await automation.aclose()
        await app.state.indexer_runtime.aclose()
        engine.dispose()
        logger.info("%s stopped", APP_NAME)

    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        description=API_DESCRIPTION,
        license_info={"name": "GPL-3.0-only", "identifier": "GPL-3.0-only"},
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.indexer_runtime = IndexerRuntime()
    app.state.events = EventBus()
    app.state.start_time = datetime.now(UTC)

    app.middleware("http")(make_auth_middleware(settings.auth))
    # Added last = outermost: oversized bodies are refused before anything else runs, and every
    # response (413s included) gets the security headers.
    app.add_middleware(BodySizeLimit)
    app.add_middleware(SecurityHeaders)
    install_error_handlers(app)
    app.include_router(system.router)
    for module in (
        magazines,
        issues,
        rootfolders,
        qualityprofiles,
        naming,
        library,
        indexers,
        downloadclients,
        activity,
        automation,
        media,
        manualimport,
        notifications,
        systempages,
    ):
        app.include_router(module.router)
    # Must be last: it catches every remaining GET path.
    app.include_router(frontend.build_router(frontend_dist or frontend.frontend_dir()))
    return app


def run() -> None:
    settings = load_settings()
    if (database := sqlite_path(settings.database_url)) and apply_staged_restore(
        settings.config_dir, database
    ):
        settings = load_settings(settings.config_dir)  # the restored config.yaml
    uvicorn.run(
        create_app(settings),
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
