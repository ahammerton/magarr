from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.domain.errors import ConflictError, DomainError, NotFoundError
from magarr.domain.models import Magazine, QualityProfile, QualityProfileItem
from magarr.domain.qualities import DEFAULT_PROFILE_NAME, DEFAULT_UPGRADE_UNTIL, QUALITY_IDS
from magarr.domain.terms import validate_terms


@dataclass(frozen=True)
class ProfileItemSpec:
    quality: str
    allowed: bool = True
    max_size_mb: int | None = None
    upgrade_until: bool = False


def default_item_specs() -> list[ProfileItemSpec]:
    """Every quality allowed, best first, upgrading until PDF (Hi-Res)."""
    return [
        ProfileItemSpec(quality=q, upgrade_until=q == DEFAULT_UPGRADE_UNTIL)
        for q in reversed(QUALITY_IDS)
    ]


def _validated(specs: list[ProfileItemSpec]) -> list[ProfileItemSpec]:
    seen: set[str] = set()
    for spec in specs:
        if spec.quality not in QUALITY_IDS:
            raise DomainError(f"Unknown quality: {spec.quality}")
        if spec.quality in seen:
            raise DomainError(f"Quality listed twice: {spec.quality}")
        if spec.max_size_mb is not None and spec.max_size_mb <= 0:
            raise DomainError("Maximum size must be positive")
        seen.add(spec.quality)
    # Qualities left out are appended as not allowed, so every profile covers every quality.
    specs = specs + [ProfileItemSpec(q, allowed=False) for q in QUALITY_IDS if q not in seen]

    if not any(s.allowed for s in specs):
        raise DomainError("A profile must allow at least one quality")
    cutoffs = [s for s in specs if s.upgrade_until]
    if len(cutoffs) > 1:
        raise DomainError("Only one quality can be the upgrade cutoff")
    if cutoffs and not cutoffs[0].allowed:
        raise DomainError("The upgrade cutoff must be an allowed quality")
    return specs


def _check_name(session: Session, name: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise DomainError("Profile name cannot be empty")
    stmt = select(QualityProfile.id).where(func.lower(QualityProfile.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(QualityProfile.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A quality profile named '{name}' already exists")
    return name


@dataclass(frozen=True)
class ProfileRules:
    """Decision rules beyond quality: protocols and release-name terms."""

    protocols: tuple[str, ...] = ("usenet", "torrent")
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()


def _apply_rules(profile: QualityProfile, rules: ProfileRules) -> None:
    protocols = [p for p in ("usenet", "torrent") if p in rules.protocols]
    if unknown := set(rules.protocols) - {"usenet", "torrent"}:
        raise DomainError(f"Unknown protocol(s): {', '.join(sorted(unknown))}")
    if not protocols:
        raise DomainError("A profile must allow at least one protocol")
    try:
        must = validate_terms(list(rules.must_contain))
        must_not = validate_terms(list(rules.must_not_contain))
    except ValueError as exc:
        raise DomainError(str(exc)) from exc
    profile.protocols, profile.must_contain, profile.must_not_contain = protocols, must, must_not


def _set_items(profile: QualityProfile, specs: list[ProfileItemSpec]) -> None:
    profile.items.clear()
    profile.items.extend(
        QualityProfileItem(
            quality=s.quality,
            allowed=s.allowed,
            max_size_mb=s.max_size_mb,
            upgrade_until=s.upgrade_until,
            position=i,
        )
        for i, s in enumerate(_validated(specs))
    )


def create_profile(
    session: Session, name: str, specs: list[ProfileItemSpec], rules: ProfileRules | None = None
) -> QualityProfile:
    profile = QualityProfile(name=_check_name(session, name))
    _apply_rules(profile, rules or ProfileRules())
    _set_items(profile, specs)
    session.add(profile)
    session.flush()
    return profile


def get_profile(session: Session, profile_id: int) -> QualityProfile:
    profile = session.get(QualityProfile, profile_id)
    if profile is None:
        raise NotFoundError(f"Quality profile {profile_id} not found")
    return profile


def update_profile(
    session: Session,
    profile_id: int,
    name: str,
    specs: list[ProfileItemSpec],
    rules: ProfileRules | None = None,
) -> QualityProfile:
    profile = get_profile(session, profile_id)
    profile.name = _check_name(session, name, exclude_id=profile_id)
    _validated(specs)  # fail before touching anything
    if rules is not None:
        _apply_rules(profile, rules)
    # Old items must be deleted before new ones hit the (profile_id, quality) unique index.
    profile.items.clear()
    session.flush()
    _set_items(profile, specs)
    session.flush()
    return profile


def delete_profile(session: Session, profile_id: int) -> None:
    profile = get_profile(session, profile_id)
    in_use = session.scalar(
        select(func.count()).select_from(Magazine).where(Magazine.quality_profile_id == profile_id)
    )
    if in_use:
        raise ConflictError(f"Profile '{profile.name}' is used by {in_use} magazine(s)")
    if session.scalar(select(func.count()).select_from(QualityProfile)) == 1:
        raise ConflictError("Cannot delete the last quality profile")
    session.delete(profile)
    session.flush()


def ensure_default_profile(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(QualityProfile)) == 0:
        create_profile(session, DEFAULT_PROFILE_NAME, default_item_specs())


def default_profile_id(session: Session) -> int | None:
    return session.scalar(select(QualityProfile.id).order_by(QualityProfile.id).limit(1))
