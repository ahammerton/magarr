"""Request body size limits: no client can make Magarr buffer an unbounded body."""

from __future__ import annotations

import contextlib
import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_LIMIT = 1024 * 1024  # 1 MiB: every JSON body fits easily
# Paths that legitimately send more. The backup upload streams to disk and checks its own limit.
LIMITS = {
    "/api/v1/magazine/import": 6 * 1024 * 1024,  # CSV import (the CSV itself is capped at 5 MB)
    "/api/v1/system/backup/upload": None,
}


class _TooLargeError(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = LIMITS.get(scope["path"], DEFAULT_LIMIT)
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send, limit)
            return

        received = 0
        started = rejected = False

        async def counting_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:  # a chunked body carries no Content-Length
                    if not started and not rejected:
                        rejected = True
                        await _reject(send, limit)
                    # The app may catch this while parsing the body; whatever it then tries
                    # to send is dropped below.
                    raise _TooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        with contextlib.suppress(_TooLargeError):  # already answered with 413
            await self.app(scope, counting_receive, guarded_send)


async def _reject(send: Send, limit: int) -> None:
    body = json.dumps({"message": f"Request body is larger than {limit // 1024} KB"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
