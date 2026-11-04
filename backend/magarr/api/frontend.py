"""Serve the built React app with an SPA fallback to index.html."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

_REPO_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

_NOT_BUILT = """<!doctype html><html><head><title>Magarr</title></head>
<body style="background:#1a1b1e;color:#c1c2c5;font-family:sans-serif;padding:2rem">
<h1>Magarr</h1><p>The UI has not been built. Run <code>npm run build</code> in
<code>frontend/</code>, or use the Vite dev server.</p></body></html>"""


def frontend_dir() -> Path:
    return Path(os.environ.get("MAGARR_FRONTEND_DIR", _REPO_DIST)).resolve()


def build_router(dist: Path) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/{path:path}")
    def spa(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(_NOT_BUILT, status_code=503)
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            # Missing hashed assets should 404, not silently return HTML.
            if path.startswith("assets/"):
                raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return router
