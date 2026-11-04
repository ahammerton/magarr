import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx

from magarr.domain.enums import IndexerImplementation, Protocol
from magarr.indexers.caps import Caps, parse_caps
from magarr.indexers.client import IndexerEndpoint, IndexerRequestError, NewznabClient
from magarr.indexers.runtime import IndexerRuntime, RateLimiter, TtlCache
from magarr.indexers.xml import parse_xml
from tests.indexer_fakes import NZB_URL, TORZNAB_URL, fixture, newznab_router, torznab_router, xml


def _endpoint(
    url: str = NZB_URL, impl: IndexerImplementation = IndexerImplementation.NEWZNAB
) -> IndexerEndpoint:
    base, path = url.rsplit("/", 1)
    return IndexerEndpoint(
        id=1,
        name="Test",
        implementation=impl,
        base_url=base + "/",
        api_path=path,
        api_key="SECRET",
        categories=(7010,),
        request_interval=0,
    )


def run(coro):
    async def wrapper():
        runtime = IndexerRuntime()
        try:
            return await coro(runtime)
        finally:
            await runtime.aclose()

    return asyncio.run(wrapper())


def test_parse_caps() -> None:
    caps = parse_caps(parse_xml(fixture("newznab_caps.xml")))
    assert caps.search_available is True
    assert caps.search_params == ["q"]
    assert (caps.limit_max, caps.limit_default) == (100, 50)
    assert {7000, 7010, 7020, 7030, 5000, 5040} == caps.category_ids()
    assert Caps.from_json(caps.to_json()) == caps


@respx.mock
def test_newznab_search_paginates_and_parses() -> None:
    route = respx.get(NZB_URL).mock(side_effect=newznab_router)
    releases = run(lambda rt: NewznabClient(_endpoint(), rt).search("National Geographic", limit=2))

    assert [r.title for r in releases] == [
        "National.Geographic.UK.2025.01.True.PDF",
        "National Geographic - February 2025",
        "National.Geographic.USA.2025.01.HYBRID.MAGAZiNE.eBook-PDF",
    ]
    first = releases[0]
    assert first.guid == "https://nzb.example/details/aaa111"
    assert first.download_url == "https://nzb.example/getnzb/aaa111.nzb&i=1&r=KEY"
    assert first.size == 48234567
    assert first.grabs == 17
    assert first.categories == (7000, 7010)
    assert first.publish_date == datetime(2025, 1, 8, 10, 15, tzinfo=UTC)
    assert first.protocol is Protocol.USENET
    assert first.seeders is None
    assert releases[1].size == 51000000  # from enclosure length

    # Two pages were requested with the right parameters, API key included.
    assert route.call_count == 2
    params = [dict(c.request.url.params) for c in route.calls]
    assert params[0] == {
        "t": "search",
        "q": "National Geographic",
        "extended": "1",
        "limit": "2",
        "cat": "7010",
        "offset": "0",
        "apikey": "SECRET",
    }
    assert params[1]["offset"] == "2"


@respx.mock
def test_torznab_seeders_and_leechers() -> None:
    respx.get(TORZNAB_URL).mock(side_effect=torznab_router)
    endpoint = _endpoint(TORZNAB_URL, IndexerImplementation.TORZNAB)
    releases = run(lambda rt: NewznabClient(endpoint, rt).search("National Geographic"))
    assert len(releases) == 3  # item without a link is skipped
    first = releases[0]
    assert (first.seeders, first.leechers) == (42, 8)
    assert first.size == 88123456  # from <size>
    assert first.protocol is Protocol.TORRENT
    assert first.info_url == "https://tracker.example/torrent/9001"


@respx.mock
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (xml("newznab_error.xml"), "Indexer error 100: Incorrect user credentials"),
        (httpx.Response(401), "rejected the API key"),
        (httpx.Response(429), "rate limit"),
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, content=b"<html>not xml"), "invalid XML"),
        (httpx.Response(200, content=b"<html><body/></html>"), "no <channel>"),
        (xml("xxe.xml"), "invalid XML"),
    ],
)
def test_search_errors(response: httpx.Response, message: str) -> None:
    respx.get(NZB_URL).mock(return_value=response)
    with pytest.raises(IndexerRequestError, match=message):
        run(lambda rt: NewznabClient(_endpoint(), rt).search("x"))


@respx.mock
def test_network_errors() -> None:
    respx.get(NZB_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(IndexerRequestError, match="Timed out"):
        run(lambda rt: NewznabClient(_endpoint(), rt).search("x"))
    respx.get(NZB_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(IndexerRequestError, match="Could not reach"):
        run(lambda rt: NewznabClient(_endpoint(), rt).search("x"))


@respx.mock
def test_caps_rejects_non_caps_document() -> None:
    respx.get(NZB_URL).mock(return_value=xml("torznab_search.xml"))
    with pytest.raises(IndexerRequestError, match="not a capabilities document"):
        run(lambda rt: NewznabClient(_endpoint(), rt).caps())


@respx.mock
def test_repeated_search_is_served_from_cache() -> None:
    route = respx.get(TORZNAB_URL).mock(side_effect=torznab_router)
    endpoint = _endpoint(TORZNAB_URL, IndexerImplementation.TORZNAB)

    async def twice(rt: IndexerRuntime) -> list[str]:
        client = NewznabClient(endpoint, rt)
        await client.search("Wired")
        await client.search("Wired")
        await client.search("Edge")
        return list(rt.cache._data)

    keys = run(twice)
    assert route.call_count == 2
    assert len(keys) == 2
    assert all("SECRET" not in key and "apikey" not in key for key in keys)


def test_ttl_cache_expiry_and_eviction() -> None:
    now = [0.0]
    cache = TtlCache(ttl=10, max_entries=2, clock=lambda: now[0])
    cache.set("a", b"1")
    cache.set("b", b"2")
    cache.set("c", b"3")  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") == b"2"
    now[0] = 11
    assert cache.get("b") is None


def test_rate_limiter_spaces_requests() -> None:
    now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(clock=lambda: now[0], sleep=fake_sleep)

    async def go() -> None:
        for _ in range(3):
            async with limiter.slot("idx", 2.0):
                now[0] += 0.5  # request takes half a second
        async with limiter.slot("other", 2.0):
            pass

    asyncio.run(go())
    assert sleeps == [2.0, 2.0]  # first request free, other key independent


@respx.mock
def test_pagination_follows_total_when_pages_are_capped() -> None:
    """The indexer returns 2 per page despite limit=100; total=3 means fetch page two."""
    route = respx.get(NZB_URL).mock(side_effect=newznab_router)
    releases = run(lambda rt: NewznabClient(_endpoint(), rt).search("x"))
    assert len(releases) == 3
    assert route.call_count == 2


@respx.mock
def test_pagination_without_total_stops_on_short_page() -> None:
    # The Torznab fixture has no newznab:response element.
    route = respx.get(TORZNAB_URL).mock(side_effect=torznab_router)
    releases = run(
        lambda rt: NewznabClient(_endpoint(TORZNAB_URL, IndexerImplementation.TORZNAB), rt).search(
            "x"
        )
    )
    assert len(releases) == 3
    assert route.call_count == 1
