#!/bin/sh
# Phase 7: backlog search against 20 rate-limited indexers (a stand-in Prowlarr), with a slow
# and a failing indexer and interactive searches running at the same time.
set -eu
cd "$(dirname "$0")/../backend"
MAGARR_LOAD=1 .venv/bin/pytest -q -s -m load tests/load "$@"
