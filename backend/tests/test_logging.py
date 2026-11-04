import json
import logging

import pytest

from magarr.core.config import load_settings
from magarr.core.logging import JsonFormatter, LogBuffer, TextFormatter, redact, setup_logging


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "magarr.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.__dict__.update(extra)
    return record


def test_json_formatter_includes_extras() -> None:
    entry = json.loads(JsonFormatter().format(_record(issue_id=42)))
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "magarr.test"
    assert entry["issue_id"] == 42
    assert "time" in entry


def test_text_formatter_appends_extras() -> None:
    line = TextFormatter().format(_record(issue_id=42, color_message="\x1b[1mhello"))
    assert "hello world" in line
    assert "issue_id=42" in line
    assert "color_message" not in line


def test_setup_logging_level_and_file(config_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGARR_LOGGING__LEVEL", "DEBUG")
    settings = load_settings(config_dir)
    setup_logging(settings)
    setup_logging(settings)  # re-running must not duplicate handlers

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    ours = [h for h in root.handlers if getattr(h, "_magarr_handler", False)]
    assert len(ours) == 3  # console, file, and the in-memory buffer behind the Logs page
    assert any(isinstance(h, LogBuffer) for h in ours)

    logging.getLogger("magarr.test").info("written", extra={"k": "v"})
    for handler in ours:
        handler.flush()
    line = (settings.log_dir / "magarr.log").read_text().strip().splitlines()[-1]
    assert json.loads(line)["k"] == "v"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "GET https://x/api?t=search&apikey=SECRET123&q=a",
            "GET https://x/api?t=search&apikey=***&q=a",
        ),
        ("headers {'X-Api-Key': 'SECRET123'}", "headers {'X-Api-Key': '***'}"),
        ('{"api_key": "SECRET123"}', '{"api_key": "***"}'),
        ("password=hunter2 rest", "password=*** rest"),
        ("nothing secret here", "nothing secret here"),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_secrets_never_reach_log_files(config_dir) -> None:
    """Regression: httpx logged indexer URLs, API key included, at INFO."""
    settings = load_settings(config_dir)
    setup_logging(settings)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING

    logging.getLogger("httpx").warning("HTTP Request: GET https://idx/api?apikey=SECRET123 200")
    logging.getLogger("magarr.test").error(
        "failed %s",
        "https://idx/api?apikey=SECRET123",
        extra={"url": "https://idx/api?apikey=SECRET123"},
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = (settings.log_dir / "magarr.log").read_text()
    assert "SECRET123" not in content
    assert content.count("apikey=***") >= 3


def test_log_buffer_numbers_entries_and_returns_the_newest(settings) -> None:
    buffer = LogBuffer(capacity=3)
    log = logging.getLogger("magarr.test.buffer")
    log.addHandler(buffer)
    log.setLevel(logging.INFO)
    try:
        for n in range(5):
            log.info("line %d", n, extra={"apikey": "x"})
    finally:
        log.removeHandler(buffer)
    entries = buffer.since(0, 10)
    assert [e["message"] for e in entries] == ["line 2", "line 3", "line 4"]  # capacity 3
    assert [e["message"] for e in buffer.since(entries[0]["id"], 10)] == ["line 3", "line 4"]
    assert [e["message"] for e in buffer.since(0, 1)] == ["line 4"]


def test_extras_named_like_secrets_are_masked(settings) -> None:
    from magarr.core.logging import RedactingFilter

    record = logging.makeLogRecord(
        {"msg": "x", "api_key": "k1", "password": "p", "token": "t", "path": "/a"}
    )
    RedactingFilter().filter(record)
    assert (record.api_key, record.password, record.token, record.path) == (
        "***",
        "***",
        "***",
        "/a",
    )
