#!/bin/sh
# Phase 6: grab -> real Transmission / Deluge / rTorrent -> complete -> imported.
# Usage: scripts/torrent-clients-integration.sh   (needs Docker; downloads the images once)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Inside the repo, not /tmp: Docker on macOS (Colima, Docker Desktop) only shares $HOME by default.
mkdir -p "$ROOT/.cache"
TC_WORK="$(mktemp -d "$ROOT/.cache/torrent-clients.XXXXXX")"
export TC_WORK TC_UID="$(id -u)" TC_GID="$(id -g)"
for client in transmission deluge rtorrent; do
  mkdir -p "$TC_WORK/$client/config" "$TC_WORK/$client/downloads" "$TC_WORK/$client/data"
done
COMPOSE="docker compose -f $ROOT/docker/docker-compose.torrent-clients-test.yml -p magarr-torrent-test"
cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; rm -rf "$TC_WORK"; }
trap cleanup EXIT
$COMPOSE up -d
wait_for() {  # url, expected HTTP codes (regex)
  for _ in $(seq 1 120); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$1" 2>/dev/null || true)"
    echo "$code" | grep -Eq "$2" && return 0
    sleep 1
  done
  echo "Timed out waiting for $1" >&2
  return 1
}
wait_for http://127.0.0.1:9191/transmission/rpc '401|409'
wait_for http://127.0.0.1:8212/json '200'
# rTorrent: nginx answers before rTorrent itself is up, so wait for a real XML-RPC reply.
for _ in $(seq 1 120); do
  curl -s -X POST -H 'Content-Type: text/xml' http://127.0.0.1:8100/RPC2 \
    --data '<?xml version="1.0"?><methodCall><methodName>system.client_version</methodName></methodCall>' \
    2>/dev/null | grep -q methodResponse && break
  sleep 1
done
cd "$ROOT/backend"
MAGARR_TC_WORK="$TC_WORK" .venv/bin/pytest -q -m integration tests/integration/test_torrent_clients_real.py "$@"
