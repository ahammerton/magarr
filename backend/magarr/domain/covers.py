"""Magazine covers: the first page of the earliest downloaded issue, cached as a JPEG.

PDFs are rendered with pdfium; EPUBs use the image the package declares as its cover (else
the first image); CBZs use their first image. Results, and failures, are cached under
``<config>/cache/covers/<magazine id>/`` keyed by file id, size and mtime, so a replaced file
gets a new cover and a broken one isn't re-rendered on every page load.
"""

from __future__ import annotations

import io
import logging
import posixpath
import re
import threading
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from defusedxml import ElementTree
from PIL import Image

from magarr.domain.models import Magazine

logger = logging.getLogger(__name__)

COVER_SIZE = 900  # longest side, in pixels
_MAX_IMAGE_BYTES = 50 * 1024 * 1024  # an archive member bigger than this is not a cover
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# pdfium is not thread-safe, and FastAPI serves sync endpoints from a thread pool.
_PDFIUM_LOCK = threading.Lock()


class CoverError(Exception):
    pass


def _natural_key(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > _MAX_IMAGE_BYTES:
        raise CoverError(f"{name} is too large for a cover")
    return archive.read(info)


def _first_image(archive: zipfile.ZipFile) -> bytes:
    images = [
        n
        for n in archive.namelist()
        if n.lower().endswith(_IMAGE_EXTENSIONS) and not posixpath.basename(n).startswith(".")
    ]
    if not images:
        raise CoverError("No images in the archive")
    return _read_member(archive, min(images, key=_natural_key))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _epub_cover(archive: zipfile.ZipFile) -> bytes:
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(e for e in container.iter() if _local(e.tag) == "rootfile")
        opf_path = rootfile.attrib["full-path"]
        opf = ElementTree.fromstring(archive.read(opf_path))
    except (KeyError, StopIteration, ElementTree.ParseError):
        return _first_image(archive)

    items = [e for e in opf.iter() if _local(e.tag) == "item"]
    cover_id = next(
        (
            e.attrib.get("content")
            for e in opf.iter()
            if _local(e.tag) == "meta" and e.attrib.get("name") == "cover"
        ),
        None,
    )
    candidates = (
        # EPUB 3 marks the cover in the manifest; EPUB 2 points at it from <meta name="cover">.
        [i for i in items if "cover-image" in i.attrib.get("properties", "").split()]
        + [i for i in items if cover_id and i.attrib.get("id") == cover_id]
        + [i for i in items if i.attrib.get("media-type", "").startswith("image/")]
    )
    base = posixpath.dirname(opf_path)
    for item in candidates:
        href = item.attrib.get("href")
        if not href:
            continue
        try:
            return _read_member(archive, posixpath.normpath(posixpath.join(base, href)))
        except KeyError:
            continue
    return _first_image(archive)


def _pdf_cover(path: Path) -> Image.Image:
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(path)
        try:
            if len(document) == 0:
                raise CoverError("The PDF has no pages")
            page = document[0]
            scale = COVER_SIZE / max(page.get_width(), page.get_height(), 1)
            return page.render(scale=scale).to_pil()
        finally:
            document.close()


def render_cover(path: Path) -> bytes:
    """A JPEG of the file's cover, at most ``COVER_SIZE`` pixels on its longest side."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        image = _pdf_cover(path)
    elif suffix in (".epub", ".cbz"):
        with zipfile.ZipFile(path) as archive:
            data = _epub_cover(archive) if suffix == ".epub" else _first_image(archive)
        image = Image.open(io.BytesIO(data))
    else:
        raise CoverError(f"Can't read covers from {suffix or 'this'} files")
    image = image.convert("RGB")
    image.thumbnail((COVER_SIZE, COVER_SIZE))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def magazine_cover(magazine: Magazine, cache_dir: Path) -> Path | None:
    """The cached cover of the earliest downloaded issue whose cover can be read, if any."""
    folder = cache_dir / str(magazine.id)
    for issue in magazine.issues:  # ordered by sort_index
        if issue.file is None:
            continue
        source = magazine.path / issue.file.relative_path
        try:
            stat = source.stat()
        except OSError:
            continue
        key = f"{issue.file.id}-{stat.st_size}-{int(stat.st_mtime)}"
        cached, failed = folder / f"{key}.jpg", folder / f"{key}.failed"
        if cached.exists():
            return cached
        if failed.exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        try:
            data = render_cover(source)
        except Exception as exc:  # any malformed file: pdfium, zip, XML and Pillow all differ
            logger.warning("Could not read cover", extra={"file": str(source), "error": str(exc)})
            failed.touch()
            continue
        for old in folder.glob("*.jpg"):
            old.unlink(missing_ok=True)
        partial = cached.with_name(f"{cached.name}.{threading.get_ident()}.tmp")
        partial.write_bytes(data)
        partial.replace(cached)
        return cached
    return None
