"""Quality definitions.

A quality is a ranked bucket a file falls into. For now quality follows file format; "PDF (Hi-Res)"
exists so profiles can prefer it once release parsing can detect it (Phase 2+).
"""

from __future__ import annotations

from dataclasses import dataclass

from magarr.domain.enums import FileFormat


@dataclass(frozen=True)
class Quality:
    id: str
    name: str
    formats: tuple[FileFormat, ...]


# Ascending default preference.
QUALITIES: tuple[Quality, ...] = (
    Quality("unknown", "Unknown", ()),
    Quality("cbr", "CBR", (FileFormat.CBR,)),
    Quality("cb7", "CB7", (FileFormat.CB7,)),
    Quality("cbz", "CBZ", (FileFormat.CBZ,)),
    Quality("djvu", "DjVu", (FileFormat.DJVU,)),
    Quality("mobi", "MOBI", (FileFormat.MOBI,)),
    Quality("azw3", "AZW3", (FileFormat.AZW3,)),
    Quality("epub", "EPUB", (FileFormat.EPUB,)),
    Quality("pdf", "PDF", (FileFormat.PDF,)),
    Quality("pdf_hires", "PDF (Hi-Res)", (FileFormat.PDF,)),
)

QUALITY_IDS: tuple[str, ...] = tuple(q.id for q in QUALITIES)

DEFAULT_PROFILE_NAME = "Any"
DEFAULT_UPGRADE_UNTIL = "pdf_hires"


def quality_for_format(fmt: FileFormat | str | None) -> str:
    """Base quality of a file judged only by its format."""
    for quality in QUALITIES:
        if fmt in quality.formats:
            return quality.id
    return "unknown"
