"""Structured logging: console (text or JSON) plus a rotating JSON log file in the config dir."""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from collections import deque
from datetime import UTC, datetime
from typing import Any

from magarr.core.config import Settings

# Attributes every LogRecord has; anything else was passed via ``extra=`` and is structured data.
# uvicorn's ``color_message`` duplicates ``message`` with ANSI codes.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "color_message",
}

_HANDLER_MARKER = "_magarr_handler"

# Secrets that show up in URLs and headers: Newznab puts the API key in the query string.
_SECRET = re.compile(
    r"(?i)\b(apikey|api_key|api-key|x-api-key|password|token)([\"']?\s*[=:]\s*[\"']?)([^&\s\"',}]+)"
)


_SECRET_NAME = re.compile(r"(?i)api[-_]?key|password|passwd|token|secret")


def redact(text: str) -> str:
    """Mask API keys and passwords in free text (log lines, stored error messages)."""
    return _SECRET.sub(lambda m: f"{m[1]}{m[2]}***", text)


class RedactingFilter(logging.Filter):
    """Applied to every Magarr handler so no logger, ours or a library's, can leak a key."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        for key, value in _extras(record).items():
            if _SECRET_NAME.search(key):  # extra={"api_key": ...}: mask whatever it holds
                setattr(record, key, "***")
            elif isinstance(value, str):
                setattr(record, key, redact(value))
        return True


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(_extras(record))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extras = _extras(record)
        if extras:
            text += " " + " ".join(f"{k}={v!r}" for k, v in extras.items())
        return text


class LogBuffer(logging.Handler):
    """The most recent log entries in memory, numbered, for the live log page."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self.next_id = 1
        self._formatter = JsonFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.loads(self._formatter.format(record))
        except Exception:  # never let logging break the app
            return
        with self.lock:
            entry["id"] = self.next_id
            self.next_id += 1
            self.entries.append(entry)

    def since(self, after: int, limit: int) -> list[dict[str, Any]]:
        with self.lock:
            return [e for e in self.entries if e["id"] > after][-limit:]


LOG_BUFFER = LogBuffer()


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter() if settings.logging.json_format else TextFormatter())
    handlers: list[logging.Handler] = [console, LOG_BUFFER]

    if settings.logging.file_enabled:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_dir / "magarr.log", maxBytes=5 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    for handler in handlers:
        setattr(handler, _HANDLER_MARKER, True)
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(settings.logging.level)

    # httpx logs every request URL at INFO, and indexer URLs carry the API key.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Route uvicorn's loggers through ours so everything shares one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
