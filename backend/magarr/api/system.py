from __future__ import annotations

import logging
import os
import platform
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from magarr import APP_NAME, __version__
from magarr.api.schemas import ApiModel
from magarr.core.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter()


class SystemStatus(ApiModel):
    app_name: str
    version: str
    start_time: datetime
    uptime_seconds: int
    is_docker: bool
    os_name: str
    os_version: str
    python_version: str
    database_type: str
    database_version: str
    database_migration: str | None
    app_data_dir: str
    authentication: str


class Initialize(ApiModel):
    app_name: str
    version: str
    api_key: str


def _is_docker() -> bool:
    return os.environ.get("MAGARR_DOCKER") == "1" or Path("/.dockerenv").exists()


@router.get("/health", include_in_schema=False)
def health(request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unreachable")
        return JSONResponse({"status": "error", "database": "unreachable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/initialize.json", response_model=Initialize, response_model_by_alias=True)
def initialize(request: Request) -> Initialize:
    """Bootstrap data for the UI (same idea as the Arr apps' initialize.json)."""
    settings: Settings = request.app.state.settings
    return Initialize(app_name=APP_NAME, version=__version__, api_key=settings.auth.api_key)


@router.get("/api/v1/system/status", response_model=SystemStatus, response_model_by_alias=True)
def system_status(request: Request) -> SystemStatus:
    settings: Settings = request.app.state.settings
    engine = request.app.state.engine
    started: datetime = request.app.state.start_time
    if engine.dialect.name == "sqlite":
        db_version = sqlite3.sqlite_version
    else:
        db_version = str(engine.dialect.server_version_info)
    return SystemStatus(
        app_name=APP_NAME,
        version=__version__,
        start_time=started,
        uptime_seconds=int((datetime.now(UTC) - started).total_seconds()),
        is_docker=_is_docker(),
        os_name=platform.system(),
        os_version=platform.release(),
        python_version=sys.version.split()[0],
        database_type=engine.dialect.name,
        database_version=db_version,
        database_migration=request.app.state.db_revision,
        app_data_dir=str(settings.config_dir),
        authentication="basic" if settings.auth.basic_auth_enabled else "apiKey",
    )
