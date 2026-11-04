"""Shared helpers for indexer tests (respx-mocked Newznab/Torznab/Prowlarr servers)."""

from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"

NZB_URL = "https://nzb.example/api"
TORZNAB_URL = "https://tracker.example/torznab/api"
PROWLARR_URL = "http://prowlarr.local:9696"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def xml(name: str) -> httpx.Response:
    return httpx.Response(200, content=fixture(name), headers={"Content-Type": "application/xml"})


def newznab_router(request: httpx.Request) -> httpx.Response:
    """A two-page Newznab search plus caps."""
    params = request.url.params
    if params.get("t") == "caps":
        return xml("newznab_caps.xml")
    if params.get("offset", "0") == "0":
        return xml("newznab_search_page1.xml")
    return xml("newznab_search_page2.xml")


def torznab_router(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("t") == "caps":
        return xml("newznab_caps.xml")
    return xml("torznab_search.xml")
