from enum import StrEnum


class Frequency(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    AD_HOC = "ad-hoc"


class IssueStatus(StrEnum):
    MISSING = "missing"  # no file, not monitored
    WANTED = "wanted"  # no file, monitored
    DOWNLOADED = "downloaded"  # has a file
    IGNORED = "ignored"  # no file, explicitly excluded


class FileFormat(StrEnum):
    PDF = "pdf"
    EPUB = "epub"
    CBZ = "cbz"
    CBR = "cbr"
    CB7 = "cb7"
    MOBI = "mobi"
    AZW3 = "azw3"
    DJVU = "djvu"


EXTENSION_FORMATS: dict[str, FileFormat] = {f".{fmt.value}": fmt for fmt in FileFormat}


class Protocol(StrEnum):
    USENET = "usenet"
    TORRENT = "torrent"


class IndexerImplementation(StrEnum):
    NEWZNAB = "newznab"  # Usenet
    TORZNAB = "torznab"  # BitTorrent; same API plus seeders/peers attributes

    @property
    def protocol(self) -> Protocol:
        return Protocol.USENET if self is IndexerImplementation.NEWZNAB else Protocol.TORRENT


class IndexerSource(StrEnum):
    MANUAL = "manual"
    PROWLARR = "prowlarr"


class DownloadClientImplementation(StrEnum):
    SABNZBD = "sabnzbd"
    NZBGET = "nzbget"
    QBITTORRENT = "qbittorrent"
    DELUGE = "deluge"
    TRANSMISSION = "transmission"
    RTORRENT = "rtorrent"

    @property
    def protocol(self) -> Protocol:
        usenet = (DownloadClientImplementation.SABNZBD, DownloadClientImplementation.NZBGET)
        return Protocol.USENET if self in usenet else Protocol.TORRENT


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    WARNING = "warning"  # e.g. no longer visible in the client
    PENDING_IMPORT = "pending_import"  # finished in the client, waiting for import
    IMPORT_BLOCKED = "import_blocked"  # import needs attention (see message / manual import)
    IMPORTED = "imported"
    FAILED = "failed"

    @property
    def active(self) -> bool:
        return self in ACTIVE_DOWNLOAD_STATUSES


ACTIVE_DOWNLOAD_STATUSES = frozenset(
    {
        DownloadStatus.QUEUED,
        DownloadStatus.DOWNLOADING,
        DownloadStatus.PAUSED,
        DownloadStatus.WARNING,
    }
)


class HistoryEventType(StrEnum):
    GRABBED = "grabbed"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    IMPORTED = "imported"
    UPGRADED = "upgraded"  # imported over a worse file
    IMPORT_FAILED = "import_failed"
    FILE_DELETED = "file_deleted"  # a replaced file was deleted or moved to the recycle bin


class ImportMode(StrEnum):
    MOVE = "move"
    COPY = "copy"
    HARDLINK = "hardlink"  # falls back to copy across filesystems


class NotificationImplementation(StrEnum):
    DISCORD = "discord"
    SLACK = "slack"
    WEBHOOK = "webhook"
    NTFY = "ntfy"
    PUSHOVER = "pushover"
