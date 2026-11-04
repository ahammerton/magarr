# Developing Magarr

How to run Magarr from source, run the checks and make a release. For installing and using
Magarr, see the [README](README.md) and the [guide](docs/README.md).

## Running from source

Hot reload in containers (backend reload + Vite HMR on <http://localhost:5173>):

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Or natively (Python 3.12, Node 22+):

```sh
# backend: http://localhost:8282
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
MAGARR_CONFIG_DIR=../config .venv/bin/magarr

# frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install && npm run dev
```

## Checks

```sh
cd backend  && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd frontend && npm run e2e              # Playwright against a throwaway backend
scripts/qbittorrent-integration.sh      # grab -> real qBittorrent container -> imported (Docker)
scripts/torrent-clients-integration.sh  # the same against real Transmission, Deluge and rTorrent
scripts/load-test.sh                    # backlog search against 20 rate-limited indexers
backend/.venv/bin/python scripts/export-openapi.py   # refresh docs/api/openapi.json
scripts/magarr-api.py GET /api/v1/system/health   # call a running instance's API
```

## Releasing

1. Update `__version__` in `backend/magarr/__init__.py`, `version` in `frontend/package.json`, and
   add the version to `CHANGELOG.md`, then run `scripts/export-openapi.py` to refresh
   `docs/api/openapi.json` (a test checks they all agree).
2. Tag `vX.Y.Z` and push the tag. `.github/workflows/release.yml` runs the checks, builds the
   `linux/amd64` and `linux/arm64` image, pushes it as `X.Y.Z`, `X.Y`, `X` and `latest`, and
   creates a release with the changelog entry and the OpenAPI description.
