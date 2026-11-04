#!/usr/bin/env python3
"""Call a Magarr instance's API from the command line.

The API key comes from MAGARR_API_KEY, or else from the instance's /initialize.json (which is
open while basic auth is off). JSON responses are pretty-printed; X-Total-Count is shown.

Usage:
  scripts/magarr-api.py GET /api/v1/system/health
  scripts/magarr-api.py GET "/api/v1/magazine?page=1&pageSize=10"
  scripts/magarr-api.py POST /api/v1/system/task/rss/run
  scripts/magarr-api.py PATCH /api/v1/magazine/3 '{"monitored": true}'
  MAGARR_URL=http://nas:8282 scripts/magarr-api.py GET /api/v1/queue
"""

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("MAGARR_URL", "http://localhost:8282").rstrip("/")


def api_key() -> str:
    if key := os.environ.get("MAGARR_API_KEY"):
        return key
    with urllib.request.urlopen(f"{URL}/initialize.json", timeout=10) as response:
        return json.load(response)["apiKey"]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    method, path = sys.argv[1].upper(), sys.argv[2]
    body = sys.argv[3].encode() if len(sys.argv) > 3 else None
    if body is None and method in ("POST", "PUT", "PATCH"):
        body = b"{}"
    request = urllib.request.Request(
        URL + path,
        method=method,
        data=body,
        headers={"X-Api-Key": api_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            status, headers, raw = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, headers, raw = error.code, error.headers, error.read()
    total = headers.get("X-Total-Count")
    print(f"HTTP {status}" + (f"  (X-Total-Count: {total})" if total else ""), file=sys.stderr)
    try:
        print(json.dumps(json.loads(raw), indent=2))
    except ValueError:
        sys.stdout.write(raw.decode(errors="replace"))
    return 0 if status < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
