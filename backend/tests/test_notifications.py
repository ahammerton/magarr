"""Phase 6: notifications (Discord, Slack, webhook, ntfy, Pushover), templates and delivery."""

import asyncio
import json
import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from magarr.domain.enums import HistoryEventType
from magarr.domain.history import record
from magarr.domain.models import Issue
from magarr.notifications.base import Message
from magarr.notifications.events import render
from magarr.notifications.providers import (
    Discord,
    DiscordSettings,
    Ntfy,
    NtfySettings,
    Pushover,
    PushoverSettings,
    Slack,
    SlackSettings,
    Webhook,
    WebhookSettings,
)

DISCORD = "https://discord.com/api/webhooks/123/abc"
MESSAGE = Message(
    "grab", "Grabbed Wired 2026-10", "Wired.2026.10.PDF\nSent to SAB", {"issue": "2026-10"}
)


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the notification")
        time.sleep(0.02)


# --- Templates ---------------------------------------------------------------------------------


def test_render_splits_title_and_body_and_fills_tokens() -> None:
    title, body = render(
        "Grabbed {magazine} {issue}\n{release}\n\nfrom {nonsense}",
        {"magazine": "Wired", "issue": "2026-10", "release": "Wired.2026.10.PDF"},
    )
    assert title == "Grabbed Wired 2026-10"
    assert body == "Wired.2026.10.PDF\nfrom {nonsense}"  # unknown tokens stay, to spot typos


def test_render_drops_lines_left_empty_by_missing_values() -> None:
    assert render("Failed {issue}\n{message}", {"issue": "7"}) == ("Failed 7", "")


# --- Services ----------------------------------------------------------------------------------


def _send(notifier_cls, settings, route_url: str, **route) -> httpx.Request:
    async def go() -> httpx.Request:
        with respx.mock() as mock:
            target = mock.post(route_url).mock(return_value=httpx.Response(200, **route))
            async with httpx.AsyncClient() as http:
                await notifier_cls(settings, http).send(MESSAGE)
            return target.calls.last.request

    return asyncio.run(go())


def test_discord_sends_an_embed() -> None:
    request = _send(Discord, DiscordSettings(webhook_url=DISCORD), DISCORD)
    body = json.loads(request.content)
    assert body["username"] == "Magarr"
    [embed] = body["embeds"]
    assert embed["title"] == "Grabbed Wired 2026-10"
    assert embed["description"].startswith("Wired.2026.10.PDF")


def test_slack_sends_text() -> None:
    url = "https://hooks.slack.com/services/T/B/X"
    request = _send(Slack, SlackSettings(webhook_url=url), url)
    assert json.loads(request.content)["text"].startswith("*Grabbed Wired 2026-10*\n")


def test_webhook_sends_json_with_basic_auth() -> None:
    url = "https://example.test/hook"
    settings = WebhookSettings(url=url, username="u", password="p")
    request = _send(Webhook, settings, url)
    payload = json.loads(request.content)
    assert (payload["event"], payload["issue"], payload["app"]) == ("grab", "2026-10", "Magarr")
    assert request.headers["authorization"].startswith("Basic ")


def test_ntfy_posts_to_the_topic() -> None:
    settings = NtfySettings(topic="mags", access_token="tok", priority="high")
    request = _send(Ntfy, settings, "https://ntfy.sh/mags")
    assert request.headers["title"] == "Grabbed Wired 2026-10"
    assert request.headers["priority"] == "high"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.content.decode().startswith("Wired.2026.10.PDF")


def test_pushover_sends_a_form_and_checks_the_status() -> None:
    url = "https://api.pushover.net/1/messages.json"
    settings = PushoverSettings(user_key="U", api_token="T")
    request = _send(Pushover, settings, url, json={"status": 1})
    form = dict(httpx.QueryParams(request.content.decode()))
    assert (form["user"], form["token"], form["priority"]) == ("U", "T", "0")


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (DiscordSettings, {"webhook_url": "https://discord.com/channels/1/2"}),  # not a webhook
        (SlackSettings, {"webhook_url": "http://hooks.slack.com/x"}),
        (NtfySettings, {"topic": "bad topic!"}),
    ],
)
def test_settings_are_validated(model, values) -> None:
    with pytest.raises(ValueError):
        model(**values)


# --- API ---------------------------------------------------------------------------------------


def _create(api: TestClient, **extra) -> dict:
    body = {"name": "Discord", "implementation": "discord", "settings": {"webhookUrl": DISCORD}}
    response = api.post("/api/v1/notification", json={**body, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def test_schema_lists_services_events_and_tokens(api: TestClient) -> None:
    schema = api.get("/api/v1/notification/schema").json()
    assert [i["implementation"] for i in schema["implementations"]] == [
        "discord", "slack", "webhook", "ntfy", "pushover",
    ]  # fmt: skip
    assert schema["events"] == ["grab", "import", "upgrade", "failure", "health"]
    assert schema["defaultTemplates"]["grab"].startswith("Grabbed {magazine} {issue}")
    discord = schema["implementations"][0]["fields"]
    assert discord[0]["name"] == "webhookUrl" and discord[0]["type"] == "password"


def test_crud_masks_secrets_and_keeps_them(api: TestClient) -> None:
    created = _create(api)
    assert created["settings"]["webhookUrl"] == "********"
    assert created["events"] == ["grab", "import", "upgrade", "failure", "health"]

    patched = api.patch(
        f"/api/v1/notification/{created['id']}",
        json={"settings": {"webhookUrl": "********", "username": "Mags"}, "events": ["grab"]},
    ).json()
    assert (patched["settings"]["username"], patched["events"]) == ("Mags", ["grab"])
    with api.app.state.session_factory() as session:
        from magarr.domain.models import Notification

        assert session.get(Notification, created["id"]).settings["webhook_url"] == DISCORD

    assert api.delete(f"/api/v1/notification/{created['id']}").status_code == 204
    assert api.get("/api/v1/notification").json() == []


def test_bad_settings_and_templates_are_rejected(api: TestClient) -> None:
    bad = api.post(
        "/api/v1/notification",
        json={"name": "D", "implementation": "discord", "settings": {"webhookUrl": "nope"}},
    )
    assert bad.status_code == 400 and "webhookUrl" in bad.json()["message"]
    created = _create(api)
    unknown = api.patch(f"/api/v1/notification/{created['id']}", json={"templates": {"party": "x"}})
    assert unknown.status_code == 400
    blank = api.patch(
        f"/api/v1/notification/{created['id']}",
        json={"templates": {"grab": "  ", "import": "Got {issue}"}},
    )
    assert blank.json()["templates"] == {"import": "Got {issue}"}  # blank = default


def test_preview_renders_with_example_values(api: TestClient) -> None:
    result = api.post("/api/v1/notification/preview", json={"template": "Got {magazine}\n{path}"})
    assert result.json()["title"] == "Got National Geographic"


def test_test_button_sends_and_reports_errors(api: TestClient) -> None:
    created = _create(api)
    with respx.mock(assert_all_called=False) as mock:
        hook = mock.post(DISCORD).mock(return_value=httpx.Response(204))
        ok = api.post(f"/api/v1/notification/{created['id']}/test").json()
        assert ok["ok"] is True
        assert (
            json.loads(hook.calls.last.request.content)["embeds"][0]["title"] == "Test from Magarr"
        )

        hook.mock(return_value=httpx.Response(404, json={"message": "Unknown Webhook"}))
        failed = api.post(
            "/api/v1/notification/test",
            json={
                "implementation": "discord",
                "settings": {"webhookUrl": "********"},
                "id": created["id"],
            },
        ).json()
        assert failed["ok"] is False and "HTTP 404" in failed["message"]
        saved_failure = api.post(f"/api/v1/notification/{created['id']}/test").json()
        assert saved_failure["ok"] is False
    assert (
        api.get(f"/api/v1/notification/{created['id']}").json()["lastError"].startswith("Discord")
    )


# --- Delivery ----------------------------------------------------------------------------------


@pytest.fixture
def issue(api: TestClient, magazine: dict) -> dict:
    return api.post(
        "/api/v1/issue",
        json={"magazineId": magazine["id"], "issueNumber": "2026-10", "publishDate": "2026-10-01"},
    ).json()


def test_events_are_sent_after_commit_to_subscribed_connections(
    api: TestClient, issue: dict
) -> None:
    _create(api, events=["grab"])
    _create(api, name="Imports only", events=["import"])
    with respx.mock(assert_all_called=False) as mock:
        hook = mock.post(DISCORD).mock(return_value=httpx.Response(204))
        with api.app.state.session_factory() as session:
            row = session.get(Issue, issue["id"])
            record(
                session,
                HistoryEventType.GRABBED,
                "NG.2026.10.PDF",
                row,
                client="SAB",
                source="RSS sync",
            )
            time.sleep(0.2)
            assert hook.call_count == 0  # not before the commit
            session.commit()
        _wait_for(lambda: hook.call_count == 1)
        embed = json.loads(hook.calls.last.request.content)["embeds"][0]
        assert embed["title"] == "Grabbed National Geographic 2026-10"
        assert "Sent to SAB (RSS sync)" in embed["description"]


def test_rolled_back_events_are_not_sent(api: TestClient, issue: dict) -> None:
    _create(api)
    with respx.mock(assert_all_called=False) as mock:
        hook = mock.post(DISCORD).mock(return_value=httpx.Response(204))
        with api.app.state.session_factory() as session:
            row = session.get(Issue, issue["id"])
            record(session, HistoryEventType.DOWNLOAD_FAILED, "NG.PDF", row, message="CRC")
            session.rollback()
            session.commit()
        time.sleep(0.3)
        assert hook.call_count == 0


def test_custom_templates_and_disabled_connections(api: TestClient, issue: dict) -> None:
    _create(api, templates={"failure": "Oops {issue}\n{message}"})
    _create(api, name="Off", enabled=False)
    with respx.mock(assert_all_called=False) as mock:
        hook = mock.post(DISCORD).mock(return_value=httpx.Response(204))
        with api.app.state.session_factory() as session:
            record(
                session,
                HistoryEventType.DOWNLOAD_FAILED,
                "NG.PDF",
                session.get(Issue, issue["id"]),
                message="CRC error",
            )
            session.commit()
        _wait_for(lambda: hook.call_count == 1)
        time.sleep(0.2)
        assert hook.call_count == 1  # the disabled one stayed quiet
        embed = json.loads(hook.calls.last.request.content)["embeds"][0]
        assert (embed["title"], embed["description"]) == ("Oops 2026-10", "CRC error")
