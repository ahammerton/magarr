#!/bin/sh
# Starts a throwaway Magarr backend for end-to-end tests, serving the built UI from dist/.
set -eu
: "${E2E_DIR:?E2E_DIR must be set}"
rm -rf "$E2E_DIR"
mkdir -p "$E2E_DIR/config" "$E2E_DIR/library"
HERE="$(cd "$(dirname "$0")" && pwd)"
export MAGARR_CONFIG_DIR="$E2E_DIR/config"
export MAGARR_FRONTEND_DIR="$HERE/../dist"
export MAGARR_SERVER__PORT="${E2E_PORT:-8383}"
export MAGARR_LOGGING__FILE_ENABLED=false
export MAGARR_DOWNLOADS__POLL_INTERVAL=1  # so the e2e test sees downloads progress quickly
# Automation in fast-forward: a "minute" is 0.2 s, so RSS sync (every 15) runs every 3 s.
# e2e/global-setup.ts switches automation off; only the Phase 5 test turns it on.
export MAGARR_AUTOMATION__TICK_SECONDS=1
export MAGARR_AUTOMATION__MINUTE_SECONDS=0.2
exec "${MAGARR_PYTHON:-$HERE/../../backend/.venv/bin/python}" -m magarr.main
