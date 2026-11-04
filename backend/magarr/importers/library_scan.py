"""Walk a root folder and reconcile what is on disk with the database.

* Each first-level directory is matched to a magazine in that root (folder name, then fuzzy title).
  A directory that matches no magazine but holds magazine files becomes a new, unmonitored
  magazine named after the folder ("Viz (1982)" -> Viz, first issue year 1982).
* In ad-hoc magazines (collections of one-offs), a file with no issue number or date becomes an
  issue named after its title ("The History of Ocean Software").
* Files inside are parsed and matched to issues; unknown issues are created (unmonitored).
* Anything that can't be placed is recorded as an unmapped file with a reason.
* File records whose file has disappeared are removed and the issue goes back to wanted/missing.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from magarr.domain.enums import EXTENSION_FORMATS, Frequency
from magarr.domain.errors import DomainError
from magarr.domain.issues import compute_sort_index, resolve_status
from magarr.domain.magazines import MagazineFields, create_magazine
from magarr.domain.models import Issue, IssueFile, Magazine, RootFolder, UnmappedFile
from magarr.domain.qualities import quality_for_format
from magarr.importers.matching import match_issue, match_magazine, specialise
from magarr.importers.parsing import parse_filename

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = (".", "@", "#")  # hidden, Synology @eaDir, #recycle


@dataclass
class ScanResult:
    root_folder_id: int
    path: str
    files_found: int = 0
    files_added: int = 0
    files_removed: int = 0
    issues_created: int = 0
    magazines_created: int = 0
    unmapped: int = 0


def _is_magazine_file(path: Path) -> bool:
    return path.suffix.lower() in EXTENSION_FORMATS and not path.name.startswith(_SKIP_PREFIXES)


def _walk_files(directory: Path) -> Iterator[Path]:
    for current, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith(_SKIP_PREFIXES))
        for name in sorted(files):
            path = Path(current, name)
            if _is_magazine_file(path):
                yield path


def _other_dir(path: Path, directory: Path) -> bool:
    """Whether ``path`` is an existing directory other than ``directory``.

    On case-insensitive file systems (SMB shares, macOS) "Ace" opens "ACE", so the name
    alone can't tell a magazine's own folder from a look-alike.
    """
    try:
        return path.is_dir() and not path.samefile(directory)
    except OSError:
        return False


_FOLDER_YEAR = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")


def title_from_folder(name: str) -> tuple[str, int | None]:
    """ "Viz (1982)" -> ("Viz", 1982); "Hackspace" -> ("Hackspace", None)."""
    name = name.strip()
    if (m := _FOLDER_YEAR.match(name)) and 1600 <= int(m["year"]) <= 2200:
        return m["title"].strip(), int(m["year"])
    return name, None


def guess_frequency(magazine: Magazine) -> Frequency:
    """From the typical gap between issue dates; ad-hoc when there's too little to go on."""
    dates = sorted({i.publish_date for i in magazine.issues if i.publish_date})
    if len(dates) < 3:
        return Frequency.AD_HOC
    gap = statistics.median((b - a).days for a, b in pairwise(dates))
    if gap <= 10:
        return Frequency.WEEKLY
    if gap <= 45:
        return Frequency.MONTHLY
    if gap <= 120:
        return Frequency.QUARTERLY
    return Frequency.AD_HOC


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class _Scanner:
    def __init__(self, session: Session, root: RootFolder) -> None:
        self.session = session
        self.root = root
        self.root_path = Path(root.path)
        self.result = ScanResult(root_folder_id=root.id, path=root.path)
        self.unmapped: list[UnmappedFile] = []

    def unmap(self, path: Path, reason: str) -> None:
        self.unmapped.append(
            UnmappedFile(
                root_folder_id=self.root.id,
                relative_path=path.relative_to(self.root_path).as_posix(),
                size=_size(path),
                reason=reason,
            )
        )

    def run(self) -> ScanResult:
        if not self.root_path.is_dir():
            raise DomainError(f"Root folder is not accessible: {self.root.path}")
        magazines = list(
            self.session.scalars(
                select(Magazine)
                .where(Magazine.root_folder_id == self.root.id)
                .options(selectinload(Magazine.issues).selectinload(Issue.file))
            )
        )
        entries = sorted(
            (e for e in self.root_path.iterdir() if not e.name.startswith(_SKIP_PREFIXES)),
            key=lambda e: e.name,
        )
        known_files = sum(1 for m in magazines for i in m.issues if i.file)
        if not entries and known_files:
            # An empty mount point looks exactly like this; never wipe the library because of it.
            raise DomainError(
                f"Root folder {self.root.path} is empty but {known_files} files are recorded. "
                "Is the drive mounted? Nothing was changed."
            )

        claimed: dict[int, str] = {}  # magazine id -> directory it was matched to
        for entry in entries:
            if entry.is_file():
                if _is_magazine_file(entry):
                    self.result.files_found += 1
                    self.unmap(entry, "Not inside a magazine folder")
                continue
            if not entry.is_dir():
                continue
            self.scan_directory(entry, magazines, claimed)

        for magazine in magazines:
            self.remove_missing(magazine)

        self.session.execute(
            delete(UnmappedFile).where(UnmappedFile.root_folder_id == self.root.id)
        )
        self.session.add_all(self.unmapped)
        self.result.unmapped = len(self.unmapped)
        self.session.flush()
        return self.result

    def scan_directory(
        self, directory: Path, magazines: list[Magazine], claimed: dict[int, str]
    ) -> None:
        files = list(_walk_files(directory))
        self.result.files_found += len(files)

        magazine = next((m for m in magazines if m.folder == directory.name), None)
        if magazine is None:
            magazine = match_magazine(directory.name, magazines)
            if magazine is not None and _other_dir(self.root_path / magazine.folder, directory):
                # Its real folder exists too; this one is a stray look-alike.
                reason = (
                    f"Folder looks like '{magazine.title}' "
                    f"but that magazine uses '{magazine.folder}'"
                )
                for path in files:
                    self.unmap(path, reason)
                return
            if magazine is not None:
                logger.info(
                    "Adopting folder for magazine",
                    extra={"magazine": magazine.title, "folder": directory.name},
                )
                magazine.folder = directory.name
        if magazine is None:
            if not files:
                return
            magazine = self.create_for(directory, files)
            if magazine is None:
                return
            magazines.append(magazine)
            new_magazine = True
        else:
            new_magazine = False
        if claimed.get(magazine.id, directory.name) != directory.name:
            for path in files:
                self.unmap(path, f"'{magazine.title}' is already mapped to another folder")
            return
        claimed[magazine.id] = directory.name

        by_path = {i.file.relative_path: i for i in magazine.issues if i.file}
        undetermined: list[Path] = []
        for path in files:
            if not self.import_file(magazine, directory, path, by_path):
                undetermined.append(path)
        if new_magazine:
            magazine.frequency = guess_frequency(magazine).value
        for path in undetermined:
            # Only after the frequency is known: a new folder of one-off books is ad-hoc.
            if magazine.frequency == Frequency.AD_HOC.value:
                self.import_file(magazine, directory, path, by_path, title_as_issue=True)
            else:
                self.unmap(path, "Could not determine the issue from the file name")

    def create_for(self, directory: Path, files: list[Path]) -> Magazine | None:
        """A new unmonitored magazine for a folder no magazine matches."""
        title, year = title_from_folder(directory.name)
        try:
            magazine = create_magazine(
                self.session,
                MagazineFields(
                    title=title,
                    first_issue_year=year,
                    root_folder_id=self.root.id,
                    folder=directory.name,
                    monitored=False,
                ),
            )
        except DomainError as exc:
            # e.g. a magazine with this title already lives in another root folder.
            for path in files:
                self.unmap(path, f"Could not add a magazine for this folder: {exc}")
            return None
        logger.info(
            "Added magazine from folder", extra={"magazine": title, "folder": directory.name}
        )
        self.result.magazines_created += 1
        return magazine

    def import_file(
        self,
        magazine: Magazine,
        directory: Path,
        path: Path,
        by_path: dict[str, Issue],
        title_as_issue: bool = False,
    ) -> bool:
        """Record the file against its issue. False when the name gives no issue at all."""
        relative = path.relative_to(directory).as_posix()
        if relative in by_path:
            by_path[relative].file.size = _size(path)
            return True

        parsed = specialise(parse_filename(path.name), magazine)
        if title_as_issue:
            title = (parsed.title or path.stem).strip()[:100]
            parsed = replace(parsed, special=title, year=None, month=None, day=None)
        issue = match_issue(parsed, magazine.issues)
        if issue is None:
            key = parsed.issue_key
            if key is None:
                return False
            issue = Issue(
                issue_number=key,
                publish_date=parsed.publish_date,
                sort_index=compute_sort_index(key, parsed.publish_date),
                monitored=False,
            )
            magazine.issues.append(issue)
            self.result.issues_created += 1

        if issue.file is not None:
            if (directory / issue.file.relative_path).exists():
                self.unmap(path, f"Issue {issue.issue_number} already has a file")
                return True
            # The recorded file is gone; this is probably it, moved or renamed.
            issue.file = None
            self.session.flush()

        fmt = parsed.format
        issue.file = IssueFile(
            relative_path=relative,
            size=_size(path),
            format=fmt.value if fmt else path.suffix.lstrip(".").lower(),
            quality=quality_for_format(fmt),
            date_added=datetime.now(UTC),
        )
        by_path[relative] = issue
        resolve_status(issue)
        self.result.files_added += 1
        return True

    def remove_missing(self, magazine: Magazine) -> None:
        folder = self.root_path / magazine.folder
        for issue in magazine.issues:
            if issue.file and not (folder / issue.file.relative_path).is_file():
                issue.file = None
                resolve_status(issue)
                self.result.files_removed += 1


def scan_root_folder(session: Session, root: RootFolder) -> ScanResult:
    result = _Scanner(session, root).run()
    logger.info("Library scan finished", extra=vars(result))
    return result
