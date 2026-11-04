"""Phase 6: tasks (history, run now), health checks, backup/restore and logs."""

import io
import json
import logging
import sqlite3
import time
import zipfile
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.core.config import Settings
from magarr.domain import backups
from magarr.domain.models import TaskRun
from magarr.pipeline.automation import Automation, BackupTarget
from tests.download_fakes import SAB_KEY, SAB_URL, FakeSab

DISCORD = "https://discord.com/api/webhooks/1/x"


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


# --- Tasks -------------------------------------------------------------------------------------


def test_tasks_lists_every_job_with_its_interval(api: TestClient) -> None:
    tasks = {t["name"]: t for t in api.get("/api/v1/system/task").json()}
    assert list(tasks) == ["downloads", "expected", "rss", "backlog", "health", "backup"]
    assert tasks["rss"]["intervalMinutes"] == 15
    assert tasks["backup"]["intervalMinutes"] == 7 * 24 * 60
    assert tasks["downloads"]["intervalMinutes"] == pytest.approx(0.5)
    assert tasks["health"]["label"] == "Health check"


def test_run_now_records_a_manual_run(api: TestClient, root_folder: dict) -> None:
    assert api.post("/api/v1/system/task/health/run").status_code == 202
    _wait_for(lambda: api.get("/api/v1/system/task/health/history").json())
    [run] = api.get("/api/v1/system/task/health/history").json()
    assert run["manual"] is True and run["ok"] is True
    health = next(t for t in api.get("/api/v1/system/task").json() if t["name"] == "health")
    assert health["lastResult"] == run["result"]
    assert api.post("/api/v1/system/task/nope/run").status_code == 404


def test_run_now_backs_up(api: TestClient, settings: Settings) -> None:
    api.post("/api/v1/system/task/backup/run")
    _wait_for(lambda: backups.list_backups(settings.config_dir))
    [backup] = backups.list_backups(settings.config_dir)
    assert backup.kind == "scheduled"


def test_history_survives_a_restart_so_backups_dont_run_on_every_start(
    api: TestClient, settings: Settings
) -> None:
    target = BackupTarget(settings.config_dir, settings.config_dir / "magarr.db")
    first = Automation(api.app.state.session_factory, api.app.state.indexer_runtime, backups=target)
    api.portal.call(first.tick)
    assert len(backups.list_backups(settings.config_dir)) == 1

    again = Automation(api.app.state.session_factory, api.app.state.indexer_runtime, backups=target)
    api.portal.call(again.tick)
    assert len(backups.list_backups(settings.config_dir)) == 1  # not due: ran moments ago
    assert again.status["backup"].last_result.startswith("Saved magarr_backup_scheduled_")


def test_a_failing_task_is_recorded_and_the_rest_still_run(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    automation = Automation(api.app.state.session_factory, api.app.state.indexer_runtime)

    async def broken(session, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(automation, "_expected", broken)
    api.portal.call(automation.tick)
    assert automation.status["expected"].ok is False
    assert automation.status["expected"].last_result == "Failed: boom"
    assert "rss" in automation.status  # carried on
    with api.app.state.session_factory() as session:
        assert session.query(TaskRun).filter_by(name="expected", ok=False).count() == 1


# --- Health ------------------------------------------------------------------------------------


def test_health_reports_problems(api: TestClient, tmp_path: Path) -> None:
    gone = tmp_path / "unplugged"
    gone.mkdir()
    api.post("/api/v1/rootfolder", json={"path": str(gone)})
    gone.rmdir()
    settings = api.get("/api/v1/config/automation").json()
    settings.pop("jobs")
    api.put("/api/v1/config/automation", json={**settings, "monitoringEnabled": False})
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=SAB_URL).mock(side_effect=httpx.ConnectError("refused"))
        api.post(
            "/api/v1/downloadclient",
            json={"name": "SAB", "implementation": "sabnzbd", "settings": {"host": "sab.local", "apiKey": SAB_KEY}},
        )  # fmt: skip
        report = api.get("/api/v1/system/health?refresh=true").json()
    items = {(i["source"], i["level"]): i["message"] for i in report["items"]}
    assert items[("root_folder", "error")] == f"Root folder {gone} is missing (not mounted?)"
    assert items[("download_client", "error")].startswith("SAB: Could not reach SABnzbd")
    assert items[("indexer", "warning")].startswith("No enabled indexer")
    assert items[("automation", "notice")].startswith("Automatic searching is paused")
    assert report["items"][0]["level"] == "error"  # worst first


def test_health_is_clean_when_all_is_well(api: TestClient, root_folder: dict) -> None:
    sab = FakeSab()
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__startswith=SAB_URL).mock(side_effect=sab)
        mock.get("https://nzb.example/api").mock(
            return_value=httpx.Response(
                200, text="<caps><searching><search available='yes'/></searching></caps>"
            )
        )
        api.post(
            "/api/v1/downloadclient",
            json={"name": "SAB", "implementation": "sabnzbd", "settings": {"host": "sab.local", "apiKey": SAB_KEY}},
        )  # fmt: skip
        api.post(
            "/api/v1/indexer",
            json={"name": "Usenet", "baseUrl": "https://nzb.example", "apiKey": "K"},
        )
        report = api.get("/api/v1/system/health?refresh=true").json()
    assert report["items"] == []


def test_new_health_problems_are_notified_once(api: TestClient, tmp_path: Path) -> None:
    api.post(
        "/api/v1/notification",
        json={"name": "D", "implementation": "discord", "events": ["health"], "settings": {"webhookUrl": DISCORD}},
    )  # fmt: skip
    automation = Automation(
        api.app.state.session_factory, api.app.state.indexer_runtime, health_checks=True
    )
    with respx.mock(assert_all_called=False) as mock:
        hook = mock.post(DISCORD).mock(return_value=httpx.Response(204))
        api.portal.call(
            automation._run, automation._spec("health"), api.app.state.session_factory()
        )
        _wait_for(lambda: hook.call_count >= 2)  # no root folder, no indexer, no client
        sent = hook.call_count
        api.portal.call(
            automation._run, automation._spec("health"), api.app.state.session_factory()
        )
        time.sleep(0.3)
        assert hook.call_count == sent  # same problems: not sent again
    titles = {json.loads(c.request.content)["embeds"][0]["description"] for c in hook.calls}
    assert any("No enabled indexer" in t for t in titles)


# --- Backups -----------------------------------------------------------------------------------


@pytest.fixture
def restarts(api: TestClient) -> list[int]:
    calls: list[int] = []
    api.app.state.restart = lambda: calls.append(1)
    return calls


def test_backup_holds_the_database_and_config(api: TestClient, magazine: dict) -> None:
    created = api.post("/api/v1/system/backup")
    assert created.status_code == 201
    name = created.json()["name"]
    assert [b["name"] for b in api.get("/api/v1/system/backup").json()] == [name]
    download = api.get(f"/api/v1/system/backup/{name}")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert set(archive.namelist()) == {"magarr.db", "config.yaml"}
        db = Path(api.app.state.settings.config_dir) / "check.db"
        db.write_bytes(archive.read("magarr.db"))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT title FROM magazines").fetchall() == [("National Geographic",)]
    assert api.delete(f"/api/v1/system/backup/{name}").status_code == 204
    assert api.get(f"/api/v1/system/backup/{name}").status_code == 404
    assert api.get("/api/v1/system/backup/..%2Fconfig.yaml").status_code == 404


def test_restore_is_staged_then_applied_at_the_next_start(
    api: TestClient, magazine: dict, settings: Settings, restarts: list[int]
) -> None:
    name = api.post("/api/v1/system/backup").json()["name"]
    api.post("/api/v1/magazine", json={"title": "Wired"})  # made after the backup

    result = api.post(f"/api/v1/system/backup/{name}/restore")
    assert result.status_code == 200 and restarts == [1]
    database = settings.config_dir / "magarr.db"
    api.app.state.engine.dispose()
    assert backups.apply_staged_restore(settings.config_dir, database) is True
    with sqlite3.connect(database) as conn:
        titles = [r[0] for r in conn.execute("SELECT title FROM magazines")]
    assert titles == ["National Geographic"]  # Wired is gone: back to the backup
    kinds = {b.kind for b in backups.list_backups(settings.config_dir)}
    assert "pre_restore" in kinds  # the state before the restore was kept
    assert backups.apply_staged_restore(settings.config_dir, database) is False  # applied once


def test_uploaded_restore_is_checked(api: TestClient, restarts: list[int], tmp_path: Path) -> None:
    not_zip = api.post("/api/v1/system/backup/upload", content=b"hello")
    assert not_zip.status_code == 400 and "not a zip" in not_zip.json()["message"]

    junk = io.BytesIO()
    with zipfile.ZipFile(junk, "w") as archive:
        archive.writestr("magarr.db", b"not sqlite")
    bad_db = api.post("/api/v1/system/backup/upload", content=junk.getvalue())
    assert bad_db.status_code == 400

    future = tmp_path / "future.db"
    with sqlite3.connect(future) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        conn.execute("INSERT INTO alembic_version VALUES ('9999')")
    newer = io.BytesIO()
    with zipfile.ZipFile(newer, "w") as archive:
        archive.write(future, "magarr.db")
    too_new = api.post("/api/v1/system/backup/upload", content=newer.getvalue())
    assert too_new.status_code == 400 and "newer version" in too_new.json()["message"]

    good = api.get(f"/api/v1/system/backup/{api.post('/api/v1/system/backup').json()['name']}")
    assert api.post("/api/v1/system/backup/upload", content=good.content).status_code == 200
    assert restarts == [1]


def test_scheduled_backups_keep_the_newest_seven(settings: Settings, api: TestClient) -> None:
    database = settings.config_dir / "magarr.db"
    for _ in range(9):
        backups.create_backup(settings.config_dir, database, "scheduled")
        time.sleep(0.002)  # names are per millisecond
    assert len([b for b in backups.list_backups(settings.config_dir) if b.kind == "scheduled"]) == 7


# --- Logs --------------------------------------------------------------------------------------


def test_logs_tail_and_filter(api: TestClient) -> None:
    log = logging.getLogger("magarr.test.page")
    log.info("hello from the test", extra={"apikey": "secret-value"})
    log.warning("careful now")
    page = api.get("/api/v1/system/logs?limit=2000").json()
    mine = [e for e in page["entries"] if e["logger"] == "magarr.test.page"]
    assert [e["message"] for e in mine] == ["hello from the test", "careful now"]
    assert mine[0]["data"]["apikey"] == "***"  # redacted
    newer = api.get(f"/api/v1/system/logs?after={mine[0]['id']}").json()["entries"]
    assert "hello from the test" not in [e["message"] for e in newer]
    warnings = api.get("/api/v1/system/logs?level=WARNING").json()["entries"]
    assert all(e["level"] in ("WARNING", "ERROR", "CRITICAL") for e in warnings)
