"""Authentication middleware.

* ``/api/*`` requires the API key (``X-Api-Key`` header or ``apikey`` query param, as in the
  Arr apps). When basic auth is enabled, valid basic credentials are accepted too.
* Everything else (the UI and ``/initialize.json``) is open unless basic auth is enabled.
* ``/health`` (container health checks) and the OpenAPI docs are always open.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from magarr import APP_NAME
from magarr.core.config import AuthSettings

OPEN_PATHS = frozenset({"/health", "/api/docs", "/api/v1/openapi.json"})


def _matches(supplied: str | None, expected: str) -> bool:
    return bool(supplied) and bool(expected) and secrets.compare_digest(supplied, expected)


def _valid_api_key(request: Request, auth: AuthSettings) -> bool:
    supplied = request.headers.get("x-api-key") or request.query_params.get("apikey")
    return _matches(supplied, auth.api_key)


def _valid_basic(request: Request, auth: AuthSettings) -> bool:
    if not auth.basic_auth_enabled:
        return False
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        username, _, password = base64.b64decode(encoded).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    # Evaluate both comparisons so timing doesn't reveal which part was wrong.
    user_ok = _matches(username, auth.username)
    pass_ok = _matches(password, auth.password)
    return user_ok and pass_ok


def make_auth_middleware(
    auth: AuthSettings,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)

        if path == "/api" or path.startswith("/api/"):
            if _valid_api_key(request, auth) or _valid_basic(request, auth):
                return await call_next(request)
            return JSONResponse({"message": "Unauthorized"}, status_code=401)

        if auth.basic_auth_enabled and not _valid_basic(request, auth):
            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{APP_NAME}"'},
            )
        return await call_next(request)

    return middleware
