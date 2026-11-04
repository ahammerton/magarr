"""System pages: tasks, health, backups and logs (brief §5 Phase 6)."""

import asyncio
import logging
import os
import signal
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import FileResponse

from magarr.api.schemas import ApiModel
from magarr.core.db import sqlite_path
from magarr.core.logging import LOG_BUFFER
from magarr.domain import backups
from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.pipeline.automation import Automation
from magarr.pipeline.health import check_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["System"])

MAX_UPLOAD_BYTES = backups.MAX_RESTORE_BYTES
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _automation(request: Request) -> Automation:
    return request.app.state.automation


# --- Tasks -------------------------------------------------------------------------------------


class TaskResource(ApiModel):
    name: str
    label: str
    interval_minutes: float
    paused: bool
    running: bool
    last_run: datetime | None
    last_result: str | None
    last_ok: bool
    last_duration_ms: int
    next_run: datetime | None


class TaskRunResource(ApiModel):
    id: int
    started_at: datetime
    duration_ms: int
    ok: bool
    result: str
    manual: bool


@router.get("/task", response_model=list[TaskResource])
def tasks(request: Request) -> list[TaskResource]:
    return [TaskResource(**vars(t)) for t in _automation(request).tasks()]


@router.get("/task/{name}/history", response_model=list[TaskRunResource])
def task_history(name: str, request: Request) -> list[TaskRunResource]:
    return [
        TaskRunResource(
            id=r.id,
            started_at=r.started_at,
            duration_ms=r.duration_ms,
            ok=r.ok,
            result=r.result,
            manual=r.manual,
        )
        for r in _automation(request).history(name)
    ]


@router.post("/task/{name}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_task(name: str, request: Request) -> dict[str, str]:
    automation = _automation(request)
    if name != "downloads" and automation._spec(name) is None:
        raise NotFoundError(f"No task named {name}")
    if not automation.run_now(name):
        raise ConflictError(f"{name} is already running")
    return {"message": f"Started {name}"}


# --- Health ------------------------------------------------------------------------------------


class HealthItemResource(ApiModel):
    source: str
    level: Literal["error", "warning", "notice"]
    message: str


class HealthResource(ApiModel):
    checked_at: datetime | None
    items: list[HealthItemResource]


@router.get("/health", response_model=HealthResource)
async def health(request: Request, refresh: bool = False) -> HealthResource:
    """The last health check (run every 15 minutes); ``refresh=true`` checks now."""
    automation = _automation(request)
    if refresh or automation.health is None:
        with request.app.state.session_factory() as session:
            automation.health = await check_health(session, automation.runtime)
    report = automation.health
    return HealthResource(
        checked_at=report.checked_at,
        items=[HealthItemResource(**vars(i)) for i in report.items],
    )


# --- Backups -----------------------------------------------------------------------------------


class BackupResource(ApiModel):
    name: str
    kind: str
    size: int
    created: datetime


def _paths(request: Request) -> tuple[Path, Path]:
    settings = request.app.state.settings
    database = sqlite_path(settings.database_url)
    if database is None:
        raise DomainError("Backups need the built-in SQLite database")
    return settings.config_dir, database


def _resource(info: backups.BackupInfo) -> BackupResource:
    return BackupResource(name=info.name, kind=info.kind, size=info.size, created=info.created)


@router.get("/backup", response_model=list[BackupResource])
def list_backups(request: Request) -> list[BackupResource]:
    config_dir, _ = _paths(request)
    return [_resource(b) for b in backups.list_backups(config_dir)]


@router.post("/backup", response_model=BackupResource, status_code=status.HTTP_201_CREATED)
async def create_backup(request: Request) -> BackupResource:
    config_dir, database = _paths(request)
    return _resource(await asyncio.to_thread(backups.create_backup, config_dir, database))


@router.get("/backup/{name}", response_class=FileResponse)
def download_backup(name: str, request: Request) -> FileResponse:
    config_dir, _ = _paths(request)
    path = backups.backup_path(config_dir, name)
    return FileResponse(path, media_type="application/zip", filename=name)


@router.delete("/backup/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(name: str, request: Request) -> None:
    config_dir, _ = _paths(request)
    backups.delete_backup(config_dir, name)


def _restart(request: Request) -> None:
    """Shut down cleanly; Docker's restart policy starts Magarr again and applies the restore."""
    restart = getattr(request.app.state, "restart", None)
    if restart is not None:
        restart()
        return
    loop = asyncio.get_running_loop()
    loop.call_later(1.0, os.kill, os.getpid(), signal.SIGTERM)


class RestoreResult(ApiModel):
    message: str


@router.post("/backup/{name}/restore", response_model=RestoreResult)
async def restore_backup(name: str, request: Request) -> RestoreResult:
    config_dir, _ = _paths(request)
    path = backups.backup_path(config_dir, name)
    await asyncio.to_thread(backups.stage_restore, config_dir, path)
    _restart(request)
    return RestoreResult(message="Restoring: Magarr is restarting to apply the backup")


@router.post(
    "/backup/upload",
    response_model=RestoreResult,
    openapi_extra={"requestBody": {"content": {"application/zip": {}}, "required": True}},
)
async def upload_and_restore(request: Request) -> RestoreResult:
    """Restore from a backup zip sent as the request body."""
    config_dir, _ = _paths(request)
    config_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=config_dir, suffix=".zip", delete=False) as tmp:
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise DomainError("The backup is too large")
                tmp.write(chunk)
            tmp.close()
            await asyncio.to_thread(backups.stage_restore, config_dir, Path(tmp.name))
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    _restart(request)
    return RestoreResult(message="Restoring: Magarr is restarting to apply the backup")


# --- Logs --------------------------------------------------------------------------------------


class LogEntry(ApiModel):
    id: int
    time: str
    level: str
    logger: str
    message: str
    data: dict[str, Any]


class LogPage(ApiModel):
    entries: list[LogEntry]
    last_id: int


@router.get("/logs", response_model=LogPage)
def logs(
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO",
) -> LogPage:
    """Recent log entries, oldest first. Poll with ``after`` set to ``lastId`` to tail."""
    minimum = _LEVELS[level]
    fixed = {"id", "time", "level", "logger", "message"}
    entries = [
        LogEntry(
            id=e["id"],
            time=e["time"],
            level=e["level"],
            logger=e["logger"],
            message=e["message"],
            data={k: v for k, v in e.items() if k not in fixed},
        )
        for e in LOG_BUFFER.since(after, 100_000)
        if _LEVELS.get(e["level"], 0) >= minimum
    ][-limit:]
    last = LOG_BUFFER.since(0, 1)
    return LogPage(entries=entries, last_id=last[-1]["id"] if last else after)


@router.get("/logs/file", response_class=FileResponse)
def log_file(request: Request) -> FileResponse:
    path = request.app.state.settings.log_dir / "magarr.log"
    if not path.is_file():
        raise NotFoundError("File logging is off (logging.file_enabled)")
    return FileResponse(path, media_type="text/plain", filename="magarr.log")
