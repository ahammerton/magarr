"""Security headers on every response."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The UI has no inline scripts; Mantine needs inline styles. Posters may come from anywhere.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: http: https:",
        "font-src 'self' data:",
        "connect-src 'self' ws: wss:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
# Swagger UI loads its script and styles from a CDN.
NO_CSP = ("/api/docs",)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = list(HEADERS)
        if not scope["path"].startswith(NO_CSP):
            extra.append((b"content-security-policy", CSP.encode()))

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *((n, v) for n, v in extra if n not in present),
                ]
            await send(message)

        await self.app(scope, receive, add_headers)
