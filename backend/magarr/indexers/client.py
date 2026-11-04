"""Async Newznab/Torznab client: caps and paginated search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree.ElementTree import Element

import httpx

from magarr.domain.enums import IndexerImplementation, Protocol
from magarr.indexers.caps import Caps, parse_caps
from magarr.indexers.runtime import IndexerRuntime
from magarr.indexers.xml import IndexerResponseError, local_name, parse_xml, raise_for_error

MAX_PAGES = 3
MAX_LIMIT = 100


class IndexerRequestError(Exception):
    """Network failure, timeout, HTTP error or unusable response."""


@dataclass(frozen=True)
class IndexerEndpoint:
    """What the client needs to talk to one indexer (decoupled from the ORM row)."""

    id: int | None
    name: str
    implementation: IndexerImplementation
    base_url: str
    api_path: str
    api_key: str
    categories: tuple[int, ...]
    request_interval: float = 2.0

    @property
    def protocol(self) -> Protocol:
        return self.implementation.protocol

    @property
    def api_url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.api_path.lstrip("/")


@dataclass(frozen=True)
class IndexerRelease:
    guid: str
    title: str
    download_url: str
    info_url: str | None
    size: int
    publish_date: datetime | None
    categories: tuple[int, ...]
    seeders: int | None
    leechers: int | None
    grabs: int | None
    indexer_id: int | None
    indexer: str
    protocol: Protocol

    @property
    def age_days(self) -> int | None:
        if self.publish_date is None:
            return None
        return max((datetime.now(UTC) - self.publish_date).days, 0)


@dataclass(frozen=True)
class SearchPage:
    releases: list[IndexerRelease]
    total: int | None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_item(item: Element, endpoint: IndexerEndpoint) -> IndexerRelease | None:
    fields: dict[str, str] = {}
    attrs: dict[str, list[str]] = {}
    enclosure: Element | None = None
    for child in item:
        name = local_name(child.tag)
        if name == "attr":
            attrs.setdefault(child.get("name", "").lower(), []).append(child.get("value", ""))
        elif name == "enclosure":
            enclosure = child
        elif child.text is not None:
            fields[name] = child.text.strip()

    title = fields.get("title")
    download_url = (enclosure.get("url") if enclosure is not None else None) or fields.get("link")
    if not title or not download_url:
        return None

    def attr(name: str) -> str | None:
        return attrs.get(name, [None])[0]

    size = _int(attr("size")) or _int(enclosure.get("length") if enclosure is not None else None)
    size = size or _int(fields.get("size")) or 0
    seeders = _int(attr("seeders"))
    peers = _int(attr("peers"))
    leechers = _int(attr("leechers"))
    if leechers is None and peers is not None and seeders is not None:
        leechers = max(peers - seeders, 0)
    categories = tuple(c for c in (_int(v) for v in attrs.get("category", [])) if c is not None)
    if not categories and fields.get("category", "").isdigit():
        categories = (int(fields["category"]),)

    return IndexerRelease(
        guid=fields.get("guid") or download_url,
        title=title,
        download_url=download_url,
        info_url=fields.get("comments") or fields.get("link"),
        size=size,
        publish_date=_date(fields.get("pubDate") or attr("usenetdate")),
        categories=categories,
        seeders=seeders,
        leechers=leechers,
        grabs=_int(attr("grabs")),
        indexer_id=endpoint.id,
        indexer=endpoint.name,
        protocol=endpoint.protocol,
    )


def parse_search(content: bytes, endpoint: IndexerEndpoint) -> SearchPage:
    root = parse_xml(content)
    raise_for_error(root)
    channel = next((c for c in root if local_name(c.tag) == "channel"), None)
    if channel is None:
        raise IndexerResponseError(
            "Indexer response has no <channel>; is this a Newznab/Torznab API?"
        )
    total: int | None = None
    releases: list[IndexerRelease] = []
    for child in channel:
        name = local_name(child.tag)
        if name == "response":
            total = _int(child.get("total"))
        elif name == "item" and (release := _parse_item(child, endpoint)):
            releases.append(release)
    return SearchPage(releases=releases, total=total)


class NewznabClient:
    def __init__(self, endpoint: IndexerEndpoint, runtime: IndexerRuntime) -> None:
        self.endpoint = endpoint
        self.runtime = runtime

    async def _get(self, params: dict[str, str], use_cache: bool = True) -> bytes:
        public = urlencode(sorted(params.items()))
        cache_key = f"{self.endpoint.api_url}?{public}"
        if use_cache and (cached := self.runtime.cache.get(cache_key)) is not None:
            return cached

        query = {**params, "apikey": self.endpoint.api_key} if self.endpoint.api_key else params
        async with self.runtime.limiter.slot(self.endpoint.api_url, self.endpoint.request_interval):
            try:
                response = await self.runtime.http.get(self.endpoint.api_url, params=query)
            except httpx.TimeoutException as exc:
                raise IndexerRequestError("Timed out waiting for the indexer") from exc
            except httpx.HTTPError as exc:
                raise IndexerRequestError(f"Could not reach the indexer: {exc}") from exc
        if response.status_code in (401, 403):
            raise IndexerRequestError(f"Indexer rejected the API key (HTTP {response.status_code})")
        if response.status_code == 429:
            raise IndexerRequestError("Indexer rate limit reached (HTTP 429)")
        if response.status_code >= 400:
            raise IndexerRequestError(f"Indexer returned HTTP {response.status_code}")
        if use_cache:
            self.runtime.cache.set(cache_key, response.content)
        return response.content

    async def caps(self) -> Caps:
        content = await self._get({"t": "caps"}, use_cache=False)
        try:
            root = parse_xml(content)
            raise_for_error(root)
        except IndexerResponseError as exc:
            raise IndexerRequestError(str(exc)) from exc
        if local_name(root.tag) != "caps":
            raise IndexerRequestError("Response to t=caps is not a capabilities document")
        return parse_caps(root)

    async def recent(self, limit: int = MAX_LIMIT) -> list[IndexerRelease]:
        """The newest releases in the indexer's categories: a search with no term, which is how
        Newznab/Torznab indexers (and Prowlarr) serve their RSS feed. Never cached."""
        params = {"t": "search", "extended": "1", "limit": str(min(limit, MAX_LIMIT))}
        if self.endpoint.categories:
            params["cat"] = ",".join(str(c) for c in self.endpoint.categories)
        content = await self._get({**params, "offset": "0"}, use_cache=False)
        try:
            return parse_search(content, self.endpoint).releases
        except IndexerResponseError as exc:
            raise IndexerRequestError(str(exc)) from exc

    async def search(
        self, query: str, limit: int = MAX_LIMIT, max_pages: int = MAX_PAGES
    ) -> list[IndexerRelease]:
        """All results for ``query`` across up to ``max_pages`` pages."""
        params = {"t": "search", "q": query, "extended": "1", "limit": str(min(limit, MAX_LIMIT))}
        if self.endpoint.categories:
            params["cat"] = ",".join(str(c) for c in self.endpoint.categories)

        releases: list[IndexerRelease] = []
        offset = 0
        for _ in range(max_pages):
            content = await self._get({**params, "offset": str(offset)})
            try:
                page = parse_search(content, self.endpoint)
            except IndexerResponseError as exc:
                raise IndexerRequestError(str(exc)) from exc
            releases.extend(page.releases)
            offset += len(page.releases)
            if not page.releases:
                break
            # Indexers may cap page size below our limit, so trust "total" when it's reported.
            if page.total is not None:
                if offset >= page.total:
                    break
            elif len(page.releases) < int(params["limit"]):
                break
        return releases
