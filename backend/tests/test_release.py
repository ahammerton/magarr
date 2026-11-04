"""Release consistency: one version everywhere, a changelog entry, a current API description."""

import json
import re
import runpy
from pathlib import Path

from magarr import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_frontend_has_the_same_version() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text())
    assert package["version"] == __version__


def test_the_changelog_describes_this_version() -> None:
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text()


def test_the_published_api_description_is_current() -> None:
    script = runpy.run_path(str(ROOT / "scripts" / "export-openapi.py"))
    current = (ROOT / "docs" / "api" / "openapi.json").read_text()
    assert current == script["render"](), "run scripts/export-openapi.py"
