from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from magarr.domain.enums import HistoryEventType
from magarr.domain.models import HistoryEvent, Issue
from magarr.notifications.dispatch import notify_on_commit
from magarr.notifications.events import FROM_HISTORY


def record(
    session: Session,
    event: HistoryEventType,
    source_title: str,
    issue: Issue | None,
    download_id: int | None = None,
    **data: Any,
) -> HistoryEvent:
    entry = HistoryEvent(
        event_type=event.value,
        issue_id=issue.id if issue else None,
        magazine_id=issue.magazine_id if issue else None,
        download_id=download_id,
        source_title=source_title,
        data=data,
    )
    session.add(entry)
    if kind := FROM_HISTORY.get(event):
        notify_on_commit(
            session,
            kind,
            magazine=issue.magazine.title if issue is not None and issue.magazine else None,
            issue=issue.issue_number if issue is not None else None,
            release=source_title,
            quality=data.get("quality"),
            client=data.get("client"),
            source=data.get("source"),
            path=data.get("imported_path"),
            message=data.get("message"),
        )
    return entry
