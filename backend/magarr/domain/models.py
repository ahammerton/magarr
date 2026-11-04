"""Domain tables (§3 of the design brief)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from magarr.core.db import ModelBase
from magarr.domain.enums import DownloadStatus, Frequency, IndexerSource, IssueStatus


class RootFolder(ModelBase):
    __tablename__ = "root_folders"

    path: Mapped[str] = mapped_column(String(1024), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class QualityProfile(ModelBase):
    __tablename__ = "quality_profiles"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Decision rules applied to search results (Phase 3).
    protocols: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["usenet", "torrent"])
    # Terms: case-insensitive text, or /regex/. Releases need at least one "must contain" term
    # (when any are set) and none of the "must not contain" terms.
    must_contain: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_not_contain: Mapped[list[str]] = mapped_column(JSON, default=list)
    items: Mapped[list[QualityProfileItem]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="QualityProfileItem.position",
        lazy="selectin",
    )


class QualityProfileItem(ModelBase):
    __tablename__ = "quality_profile_items"
    __table_args__ = (UniqueConstraint("profile_id", "quality"),)

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("quality_profiles.id", ondelete="CASCADE"), index=True
    )
    quality: Mapped[str] = mapped_column(String(32))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    max_size_mb: Mapped[int | None] = mapped_column(Integer)
    upgrade_until: Mapped[bool] = mapped_column(Boolean, default=False)
    # Lower position = more preferred.
    position: Mapped[int] = mapped_column(Integer)

    profile: Mapped[QualityProfile] = relationship(back_populates="items")


class NamingConfig(ModelBase):
    """Single-row table holding the global naming scheme."""

    __tablename__ = "naming_config"

    magazine_folder_pattern: Mapped[str] = mapped_column(String(255))
    year_folder_pattern: Mapped[str] = mapped_column(String(255))
    issue_file_pattern: Mapped[str] = mapped_column(String(255))
    replace_illegal_characters: Mapped[bool] = mapped_column(Boolean, default=True)
    colon_replacement: Mapped[str] = mapped_column(String(8), default=" -")


class Magazine(ModelBase):
    __tablename__ = "magazines"
    __table_args__ = (UniqueConstraint("root_folder_id", "folder"),)

    title: Mapped[str] = mapped_column(String(255), index=True)
    sort_title: Mapped[str] = mapped_column(String(255), index=True)
    alternate_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    publisher: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), default="en")
    category: Mapped[str | None] = mapped_column(String(100))
    frequency: Mapped[str] = mapped_column(String(16), default=Frequency.MONTHLY.value)
    first_issue_year: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    quality_profile_id: Mapped[int] = mapped_column(
        ForeignKey("quality_profiles.id", ondelete="RESTRICT"), index=True
    )
    root_folder_id: Mapped[int] = mapped_column(
        ForeignKey("root_folders.id", ondelete="RESTRICT"), index=True
    )
    # Directory name under the root folder, fixed at creation so renaming the title doesn't
    # orphan files on disk.
    folder: Mapped[str] = mapped_column(String(255))
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    poster_url: Mapped[str | None] = mapped_column(String(2048))
    # Automatic searches skip issues published before this ("only issues newer than 2010").
    search_cutoff: Mapped[date | None] = mapped_column(Date)
    # RSS sync adds (and grabs) specials it sees for this magazine, e.g. "Christmas Special 2026".
    grab_new_specials: Mapped[bool] = mapped_column(Boolean, default=False)
    issue_naming_template: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    root_folder: Mapped[RootFolder] = relationship(lazy="joined")
    quality_profile: Mapped[QualityProfile] = relationship()
    issues: Mapped[list[Issue]] = relationship(
        back_populates="magazine",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Issue.sort_index",
    )

    @property
    def path(self) -> Path:
        return Path(self.root_folder.path) / self.folder


class Issue(ModelBase):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("magazine_id", "issue_number"),
        Index("ix_issues_magazine_id_sort_index", "magazine_id", "sort_index"),
        # The backlog's order, and the Wanted list's.
        Index("ix_issues_status_last_searched_at", "status", "last_searched_at"),
        Index("ix_issues_status_publish_date", "status", "publish_date"),
    )

    # Indexed by the (magazine_id, sort_index) index below.
    magazine_id: Mapped[int] = mapped_column(ForeignKey("magazines.id", ondelete="CASCADE"))
    # A string: numbering is inconsistent (128, 2024-05, Vol 12 No 3, Special Edition...).
    issue_number: Mapped[str] = mapped_column(String(100))
    sort_index: Mapped[float] = mapped_column(Float, default=0.0)
    title: Mapped[str | None] = mapped_column(String(255))
    publish_date: Mapped[date | None] = mapped_column(Date, index=True)
    cover_url: Mapped[str | None] = mapped_column(String(2048))
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    # Indexed by the (status, ...) indexes below.
    status: Mapped[str] = mapped_column(String(16), default=IssueStatus.MISSING.value)
    # Last automatic (backlog or wanted-page) search; the backlog resumes from the oldest.
    last_searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    magazine: Mapped[Magazine] = relationship(back_populates="issues")
    file: Mapped[IssueFile | None] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )


class IssueFile(ModelBase):
    __tablename__ = "files"

    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), unique=True)
    # Relative to the magazine folder, POSIX separators.
    relative_path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    format: Mapped[str] = mapped_column(String(16))
    quality: Mapped[str] = mapped_column(String(32))
    edition: Mapped[str | None] = mapped_column(String(100))
    date_added: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    issue: Mapped[Issue] = relationship(back_populates="file")


class UnmappedFile(ModelBase):
    """A file found by the last library scan that could not be matched to an issue."""

    __tablename__ = "unmapped_files"

    root_folder_id: Mapped[int] = mapped_column(
        ForeignKey("root_folders.id", ondelete="CASCADE"), index=True
    )
    # Relative to the root folder, POSIX separators.
    relative_path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    reason: Mapped[str] = mapped_column(String(255))

    root_folder: Mapped[RootFolder] = relationship(lazy="joined")


class Indexer(ModelBase):
    """A Newznab (Usenet) or Torznab (BitTorrent) search endpoint."""

    __tablename__ = "indexers"
    __table_args__ = (UniqueConstraint("prowlarr_id"),)

    name: Mapped[str] = mapped_column(String(100), unique=True)
    implementation: Mapped[str] = mapped_column(String(16))
    # e.g. https://indexer.example/ ; requests go to <base_url><api_path>
    base_url: Mapped[str] = mapped_column(String(1024))
    api_path: Mapped[str] = mapped_column(String(255), default="/api")
    api_key: Mapped[str] = mapped_column(String(255), default="")
    categories: Mapped[list[int]] = mapped_column(JSON, default=list)
    # 1 (highest) to 50; Sonarr's default is 25.
    priority: Mapped[int] = mapped_column(Integer, default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Minimum seconds between requests to this indexer.
    request_interval: Mapped[float] = mapped_column(Float, default=2.0)
    # Last t=caps response, parsed (see magarr.indexers.caps.Caps).
    caps: Mapped[dict | None] = mapped_column(JSON)

    source: Mapped[str] = mapped_column(String(16), default=IndexerSource.MANUAL.value)
    prowlarr_id: Mapped[int | None] = mapped_column(Integer)

    # Health: after repeated failures the indexer is skipped until disabled_until.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1024))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProwlarrConfig(ModelBase):
    """Single-row table: connection used to pull indexers from Prowlarr."""

    __tablename__ = "prowlarr_config"

    url: Mapped[str] = mapped_column(String(1024), default="")
    api_key: Mapped[str] = mapped_column(String(255), default="")
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DownloadClient(ModelBase):
    """A SABnzbd or qBittorrent instance. ``settings`` is validated per implementation."""

    __tablename__ = "download_clients"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    implementation: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 1 (highest) to 50; the first enabled client for a release's protocol is used.
    priority: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class DownloadSettings(ModelBase):
    """Single-row table: failed-download handling."""

    __tablename__ = "download_settings"

    # On failure: blocklist the release and grab the next-best approved one.
    redownload_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    # Automatic retries per issue; after this many failed downloads it waits for the user.
    max_retries: Mapped[int] = mapped_column(Integer, default=3)


class AutomationSettings(ModelBase):
    """Single-row table: RSS sync, backlog search and expected-issue generation (Phase 5)."""

    __tablename__ = "automation_settings"

    # Global switch: off pauses RSS grabs, backlog search and expected-issue generation.
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rss_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)  # 0 = off
    backlog_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)  # 0 = off
    backlog_batch_size: Mapped[int] = mapped_column(Integer, default=10)
    # Expected issues are created up to this many days ahead, so early releases have a home.
    expected_lookahead_days: Mapped[int] = mapped_column(Integer, default=45)


class Download(ModelBase):
    """A grabbed release being tracked in a download client."""

    __tablename__ = "downloads"
    __table_args__ = (Index("ix_downloads_status", "status"),)

    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), index=True
    )
    download_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("download_clients.id", ondelete="SET NULL"), index=True
    )
    # The client's id for the item: SABnzbd nzo_id or torrent info hash.
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(1024))
    protocol: Mapped[str] = mapped_column(String(16))
    # Snapshot of the release at grab time (never includes the download URL: it embeds keys).
    release: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=DownloadStatus.QUEUED.value)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    size_left: Mapped[int] = mapped_column(BigInteger, default=0)
    output_path: Mapped[str | None] = mapped_column(String(2048))
    message: Mapped[str | None] = mapped_column(String(1024))
    # Polls in a row the item was missing from the client.
    missing_polls: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    issue: Mapped[Issue | None] = relationship()
    download_client: Mapped[DownloadClient | None] = relationship()


class HistoryEvent(ModelBase):
    """Immutable event log: grabs, completions, failures (imports come in Phase 4)."""

    __tablename__ = "history"
    __table_args__ = (Index("ix_history_created_at", "created_at"),)

    event_type: Mapped[str] = mapped_column(String(32), index=True)
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), index=True
    )
    magazine_id: Mapped[int | None] = mapped_column(
        ForeignKey("magazines.id", ondelete="SET NULL"), index=True
    )
    download_id: Mapped[int | None] = mapped_column(Integer)
    source_title: Mapped[str] = mapped_column(String(1024))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class BlocklistItem(ModelBase):
    """A release that failed; it is rejected in future searches for the same issue."""

    __tablename__ = "blocklist"

    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    magazine_id: Mapped[int | None] = mapped_column(
        ForeignKey("magazines.id", ondelete="CASCADE"), index=True
    )
    guid: Mapped[str] = mapped_column(String(1024))
    indexer_id: Mapped[int | None] = mapped_column(Integer)
    source_title: Mapped[str] = mapped_column(String(1024))
    protocol: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(1024))


class RemotePathMapping(ModelBase):
    """Translate a download client's path into the path Magarr sees, e.g. SABnzbd's
    /data/usenet/complete -> /mnt/data/usenet/complete inside Magarr's container."""

    __tablename__ = "remote_path_mappings"
    __table_args__ = (UniqueConstraint("host", "remote_path"),)

    # The download client's host as configured in Magarr (matches its "host" setting).
    host: Mapped[str] = mapped_column(String(255))
    remote_path: Mapped[str] = mapped_column(String(1024))
    local_path: Mapped[str] = mapped_column(String(1024))


class MediaSettings(ModelBase):
    """Single-row table: how completed downloads are imported."""

    __tablename__ = "media_settings"

    auto_import: Mapped[bool] = mapped_column(Boolean, default=True)
    usenet_import_mode: Mapped[str] = mapped_column(String(16), default="move")
    torrent_import_mode: Mapped[str] = mapped_column(String(16), default="hardlink")
    # After a successful Usenet move: remove the item from the client and delete the leftover
    # folder if only junk (.nfo, .diz, .sfv, ...) is left in it.
    remove_completed_downloads: Mapped[bool] = mapped_column(Boolean, default=True)
    # Replaced files go here instead of being deleted, when set.
    recycle_bin: Mapped[str] = mapped_column(String(1024), default="")
    # Octal strings such as "664"; empty leaves permissions alone.
    file_chmod: Mapped[str] = mapped_column(String(4), default="")
    folder_chmod: Mapped[str] = mapped_column(String(4), default="")
    # Numeric owner/group for imported files; None leaves ownership alone.
    chown_user: Mapped[int | None] = mapped_column(Integer)
    chown_group: Mapped[int | None] = mapped_column(Integer)


class Notification(ModelBase):
    """A connection to Discord, Slack, a webhook, ntfy or Pushover."""

    __tablename__ = "notifications"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    implementation: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # NotificationEvent values this connection is sent.
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # Per-event template overrides; events without one use the default.
    templates: Mapped[dict] = mapped_column(JSON, default=dict)
    last_sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1024))


class TaskRun(ModelBase):
    """One run of a scheduled task (RSS sync, backlog search, health check, backup...)."""

    __tablename__ = "task_runs"
    __table_args__ = (Index("ix_task_runs_name_started_at", "name", "started_at"),)

    name: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[str] = mapped_column(String(1024), default="")
    manual: Mapped[bool] = mapped_column(Boolean, default=False)  # "Run now"
