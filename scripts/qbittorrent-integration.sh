#!/bin/sh
# Phase 3 definition of done: grab -> qBittorrent (real container) -> complete -> pending_import.
# Usage: scripts/qbittorrent-integration.sh   (needs Docker; downloads the qBittorrent image once)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Inside the repo, not /tmp: Docker on macOS (Colima, Docker Desktop) only shares $HOME by default.
mkdir -p "$ROOT/.cache"
WORK="$(mktemp -d "$ROOT/.cache/qbt-test.XXXXXX")"
export QBT_CONFIG_DIR="$WORK/config" QBT_DOWNLOADS_DIR="$WORK/downloads"
export QBT_UID="$(id -u)" QBT_GID="$(id -g)"
mkdir -p "$QBT_CONFIG_DIR/qBittorrent" "$QBT_DOWNLOADS_DIR"
"$ROOT/backend/.venv/bin/python" -I "$ROOT/backend/tests/integration/qbt_config.py" > "$QBT_CONFIG_DIR/qBittorrent/qBittorrent.conf"
COMPOSE="docker compose -f $ROOT/docker/docker-compose.qbittorrent-test.yml -p magarr-qbt-test"
cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
$COMPOSE up -d
for _ in $(seq 1 60); do
  curl -sf -o /dev/null http://127.0.0.1:8085/api/v2/app/version -H "Referer: http://127.0.0.1:8085" 2>/dev/null && break
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8085/ 2>/dev/null | grep -q 200 && break
  sleep 1
done
cd "$ROOT/backend"
MAGARR_QBT_URL=http://127.0.0.1:8085 MAGARR_QBT_DOWNLOADS="$QBT_DOWNLOADS_DIR" \
  .venv/bin/pytest -q -m integration tests/integration "$@"
