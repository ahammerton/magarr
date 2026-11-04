"""Interactive search for one issue: query indexers, parse and match every release."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.models import Indexer, Issue, Magazine
from magarr.importers.matching import match_issue, match_magazine, specialise
from magarr.importers.parsing import LANGUAGE_NAMES, ParsedRelease, detect_region, parse_release
from magarr.indexers import health
from magarr.indexers.client import IndexerRelease, IndexerRequestError, NewznabClient
from magarr.indexers.runtime import IndexerRuntime
from magarr.indexers.service import endpoint_for
from magarr.pipeline.decision import load_context, profile_rejections, rank_key

logger = logging.getLogger(__name__)

MAX_TITLES = 3  # title + up to two alternate titles


@dataclass
class EvaluatedRelease:
    release: IndexerRelease
    parsed: ParsedRelease
    rejections: list[str] = field(default_factory=list)
    rank: tuple = ()

    @property
    def approved(self) -> bool:
        return not self.rejections

    @property
    def quality(self) -> str:
        return self.parsed.quality


@dataclass
class IndexerOutcome:
    indexer_id: int
    name: str
    ok: bool
    release_count: int = 0
    error: str | None = None
    skipped_until: datetime | None = None


@dataclass
class IssueSearchResult:
    releases: list[EvaluatedRelease]
    indexers: list[IndexerOutcome]
    queries: list[str]


def build_queries(magazine: Magazine, issue: Issue) -> list[str]:
    """Broad queries (title + year or number); precise matching happens after parsing."""
    titles = [magazine.title, *(magazine.alternate_titles or [])][:MAX_TITLES]
    year = issue.publish_date.year if issue.publish_date else None
    number = issue.issue_number if issue.issue_number.isdigit() else None
    queries: list[str] = []
    for title in titles:
        candidates = [f"{title} {number}" if number else None, f"{title} {year}" if year else None]
        candidates = [c for c in candidates if c] or [title]
        for query in candidates:
            if query.casefold() not in (q.casefold() for q in queries):
                queries.append(query)
    return queries


def applies_to(indexer: Indexer, magazine: Magazine) -> bool:
    """Untagged indexers serve every magazine; tagged ones only magazines sharing a tag."""
    if not indexer.tags:
        return True
    wanted = {t.casefold() for t in magazine.tags or []}
    return any(t.casefold() in wanted for t in indexer.tags)


def _language_code(language: str | None) -> str:
    return (language or "en").strip().lower()[:2]


def evaluate(release: IndexerRelease, magazine: Magazine, issue: Issue) -> EvaluatedRelease:
    parsed = parse_release(release.title)
    result = EvaluatedRelease(release=release, parsed=parsed)
    reject = result.rejections.append
    if parsed.is_pack:
        reject("Multi-issue pack (grab it manually to import every issue in it)")
    if not parsed.title:
        reject("Could not find a magazine title in the release name")
        return result
    if match_magazine(parsed.title, [magazine]) is None:
        # Issue details of a different magazine are beside the point.
        reject(f"Different magazine: '{parsed.title}'")
        return result
    parsed = result.parsed = specialise(parsed, magazine)

    regions = {
        r for r in (detect_region(t) for t in [magazine.title, *magazine.alternate_titles]) if r
    }
    if regions and parsed.edition and parsed.edition not in regions:
        reject(f"Different edition: {parsed.edition}")
    wanted_language = _language_code(magazine.language)
    if parsed.language and parsed.language != wanted_language:
        name = LANGUAGE_NAMES.get(parsed.language, parsed.language)
        reject(f"Different language: {name} (magazine is '{wanted_language}')")
    if not parsed.is_pack:
        if parsed.issue_key is None:
            reject("Could not determine the issue from the release name")
        elif match_issue(parsed, [issue]) is None:
            reject(f"Wrong issue: release is {parsed.issue_key}")
    return result


async def _query_indexer(client: NewznabClient, queries: list[str]) -> list[IndexerRelease]:
    releases: dict[str, IndexerRelease] = {}
    for query in queries:
        for release in await client.search(query):
            releases.setdefault(release.guid, release)
    return list(releases.values())


def _sort_key(item: EvaluatedRelease) -> tuple:
    """Approved releases in decision-engine rank order, then rejected ones newest first."""
    if item.approved:
        return (0, item.rank)
    published = item.release.publish_date.timestamp() if item.release.publish_date else 0
    return (1, (-published, -(item.release.seeders or 0)))


async def search_issue(
    session: Session, runtime: IndexerRuntime, issue: Issue
) -> IssueSearchResult:
    magazine = issue.magazine
    queries = build_queries(magazine, issue)
    indexers = [
        i
        for i in session.scalars(
            select(Indexer)
            .where(Indexer.enabled.is_(True))
            .order_by(Indexer.priority, Indexer.name)
            # Fresh health: the backlog keeps one session for a whole batch, and other
            # sessions (RSS, searches from the UI) may have backed an indexer off meanwhile.
            .execution_options(populate_existing=True)
        )
        if applies_to(i, magazine)
    ]

    outcomes: list[IndexerOutcome] = []
    active: list[Indexer] = []
    for indexer in indexers:
        if until := health.disabled_until(indexer):
            outcomes.append(
                IndexerOutcome(
                    indexer.id,
                    indexer.name,
                    ok=False,
                    error=indexer.last_error,
                    skipped_until=until,
                )
            )
        else:
            active.append(indexer)

    context = load_context(session, issue)
    results = await asyncio.gather(
        *(_query_indexer(NewznabClient(endpoint_for(i), runtime), queries) for i in active),
        return_exceptions=True,
    )

    evaluated: list[EvaluatedRelease] = []
    for indexer, result in zip(active, results, strict=True):
        if isinstance(result, IndexerRequestError):
            health.record_failure(indexer, str(result))
            outcomes.append(IndexerOutcome(indexer.id, indexer.name, ok=False, error=str(result)))
            logger.warning(
                "Indexer search failed", extra={"indexer": indexer.name, "error": str(result)}
            )
            continue
        if isinstance(result, BaseException):
            raise result
        health.record_success(indexer)
        outcomes.append(
            IndexerOutcome(indexer.id, indexer.name, ok=True, release_count=len(result))
        )
        for release in result:
            item = evaluate(release, magazine, issue)
            if item.approved:
                # Profile rules only matter once the release is the right issue.
                item.rejections.extend(profile_rejections(release, item.quality, context))
                item.rank = rank_key(release, item.quality, context, indexer.priority)
            runtime.releases.put(release.indexer_id, release.guid, release)
            evaluated.append(item)

    session.flush()
    evaluated.sort(key=_sort_key)
    return IssueSearchResult(releases=evaluated, indexers=outcomes, queries=queries)
