"""Write the API's OpenAPI description to docs/api/openapi.json (CI checks it's current).

Usage: backend/.venv/bin/python scripts/export-openapi.py [--check]
"""

import json
import sys
import tempfile
from pathlib import Path

from magarr.core.config import load_settings
from magarr.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"


def render() -> str:
    with tempfile.TemporaryDirectory() as config_dir:
        spec = create_app(load_settings(config_dir)).openapi()
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            sys.exit("docs/api/openapi.json is out of date: run scripts/export-openapi.py")
        print("docs/api/openapi.json is current")
    else:
        TARGET.write_text(text)
        print(f"Wrote {TARGET}")
