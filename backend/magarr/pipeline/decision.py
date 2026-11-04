"""Decision engine: profile rules on top of the parse/match checks, then ranking (brief §5 Phase 3).

Order of checks for an issue's search results:
  parse/match (magazine, edition, language, issue, pack)  -> magarr.pipeline.search.evaluate
  quality allowed by the profile, size within the quality's cap, protocol allowed,
  must contain / must not contain, blocklist, already downloading, upgrade/cutoff  -> here
Approved releases are ranked by profile quality order, then seeders, then age, then indexer
priority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from magarr.domain.enums import ACTIVE_DOWNLOAD_STATUSES
from magarr.domain.models import BlocklistItem, Download, Issue, QualityProfile
from magarr.domain.qualities import QUALITIES
from magarr.domain.terms import term_matches
from magarr.indexers.client import IndexerRelease

_QUALITY_NAMES = {q.id: q.name for q in QUALITIES}


@dataclass
class DecisionContext:
    profile: QualityProfile
    issue: Issue
    blocked_guids: set[tuple[int | None, str]] = field(default_factory=set)
    blocked_titles: set[str] = field(default_factory=set)
    has_active_download: bool = False

    @property
    def positions(self) -> dict[str, int]:
        return {item.quality: item.position for item in self.profile.items}

    @property
    def cutoff_position(self) -> int | None:
        return next((i.position for i in self.profile.items if i.upgrade_until), None)


def load_context(session: Session, issue: Issue) -> DecisionContext:
    profile = issue.magazine.quality_profile
    blocked = list(session.scalars(select(BlocklistItem).where(BlocklistItem.issue_id == issue.id)))
    active = session.scalar(
        select(Download.id).where(
            Download.issue_id == issue.id,
            Download.status.in_([s.value for s in ACTIVE_DOWNLOAD_STATUSES]),
        )
    )
    return DecisionContext(
        profile=profile,
        issue=issue,
        blocked_guids={(b.indexer_id, b.guid) for b in blocked},
        blocked_titles={b.source_title.casefold() for b in blocked},
        has_active_download=active is not None,
    )


def profile_rejections(release: IndexerRelease, quality: str, ctx: DecisionContext) -> list[str]:
    reasons: list[str] = []
    item = next((i for i in ctx.profile.items if i.quality == quality), None)
    name = _QUALITY_NAMES.get(quality, quality)
    if item is None or not item.allowed:
        reasons.append(f"Quality {name} is not allowed by profile '{ctx.profile.name}'")
    elif item.max_size_mb and release.size > item.max_size_mb * 1024 * 1024:
        size_mb = release.size // (1024 * 1024)
        reasons.append(f"Size {size_mb} MB is over the {item.max_size_mb} MB limit for {name}")

    if release.protocol.value not in (ctx.profile.protocols or []):
        reasons.append(f"Protocol {release.protocol.value} is not allowed by the profile")

    title = release.title
    if ctx.profile.must_contain and not any(
        term_matches(t, title) for t in ctx.profile.must_contain
    ):
        reasons.append(f"Does not contain any of: {', '.join(ctx.profile.must_contain)}")
    if hits := [t for t in ctx.profile.must_not_contain or [] if term_matches(t, title)]:
        reasons.append(f"Contains a forbidden term: {', '.join(hits)}")

    if (
        release.indexer_id,
        release.guid,
    ) in ctx.blocked_guids or title.casefold() in ctx.blocked_titles:
        reasons.append("Blocklisted after an earlier failed download")
    if ctx.has_active_download:
        reasons.append("This issue already has a download in progress")

    existing = ctx.issue.file
    if existing is not None:
        positions = ctx.positions
        have = positions.get(existing.quality)
        want = positions.get(quality)
        cutoff = ctx.cutoff_position
        have_name = _QUALITY_NAMES.get(existing.quality, existing.quality)
        if have is not None and cutoff is not None and have <= cutoff:
            reasons.append(f"Existing file ({have_name}) meets the upgrade cutoff")
        elif have is not None and want is not None and want >= have:
            reasons.append(f"Not an upgrade over the existing {have_name} file")
    return reasons


def rank_key(
    release: IndexerRelease, quality: str, ctx: DecisionContext, indexer_priority: int
) -> tuple:
    """Smaller sorts first: preferred quality, more seeders, newer, higher-priority indexer."""
    position = ctx.positions.get(quality, len(ctx.positions))
    age = release.age_days if release.age_days is not None else 1_000_000
    return (position, -(release.seeders or 0), age, indexer_priority)
