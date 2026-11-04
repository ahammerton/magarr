import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from magarr.core.config import Settings
from magarr.domain.covers import CoverError, render_cover

SCAN = "/api/v1/library/scan"
RED, BLUE, GREEN = (220, 30, 30), (30, 30, 220), (30, 200, 30)


def _image(colour: tuple[int, int, int], fmt: str = "PNG", size=(400, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


def _pdf(path: Path, *colours: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pages = [Image.new("RGB", (400, 600), c) for c in colours]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:])
    return path


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _colour(jpeg: bytes) -> tuple[int, int, int]:
    image = Image.open(io.BytesIO(jpeg))
    assert image.format == "JPEG"
    return image.convert("RGB").getpixel((image.width // 2, image.height // 2))


def _close(actual: tuple[int, int, int], expected: tuple[int, int, int]) -> bool:
    return all(abs(a - e) < 25 for a, e in zip(actual, expected, strict=True))


def test_pdf_cover_is_the_first_page(tmp_path: Path) -> None:
    jpeg = render_cover(_pdf(tmp_path / "issue.pdf", RED, BLUE))
    assert _close(_colour(jpeg), RED)
    image = Image.open(io.BytesIO(jpeg))
    assert max(image.size) == 900 and image.height > image.width


def test_epub_cover_uses_the_declared_cover(tmp_path: Path) -> None:
    opf = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata><meta name="cover" content="cov"/></metadata>
  <manifest>
    <item id="a" href="images/a-first.png" media-type="image/png"/>
    <item id="cov" href="images/z-cover.jpg" media-type="image/jpeg"/>
  </manifest>
</package>"""
    container = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>"""
    epub = _zip(
        tmp_path / "issue.epub",
        {
            "META-INF/container.xml": container.encode(),
            "OEBPS/content.opf": opf.encode(),
            "OEBPS/images/a-first.png": _image(GREEN),
            "OEBPS/images/z-cover.jpg": _image(BLUE, "JPEG"),
        },
    )
    assert _close(_colour(render_cover(epub)), BLUE)


def test_cbz_cover_is_the_first_image_in_natural_order(tmp_path: Path) -> None:
    cbz = _zip(
        tmp_path / "issue.cbz",
        {"page10.png": _image(GREEN), "page2.png": _image(BLUE), ".hidden.png": _image(RED)},
    )
    assert _close(_colour(render_cover(cbz)), BLUE)


def test_unreadable_files_raise(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(Exception):  # noqa: B017 - pdfium's own error type
        render_cover(broken)
    with pytest.raises(CoverError):
        render_cover(_zip(tmp_path / "empty.cbz", {"readme.txt": b"hi"}))


def test_magazine_cover_comes_from_the_earliest_issue(
    api: TestClient, magazine: dict, library_dir: Path, settings: Settings
) -> None:
    folder = library_dir / magazine["folder"]
    assert api.get(f"/api/v1/magazine/{magazine['id']}").json()["coverUrl"] is None

    _pdf(folder / "NG 2024-05.pdf", BLUE)
    _pdf(folder / "NG 2024-01.pdf", RED, GREEN)
    api.post(SCAN, json={})
    cover_url = api.get(f"/api/v1/magazine/{magazine['id']}").json()["coverUrl"]
    assert cover_url.startswith(f"/api/v1/magazine/{magazine['id']}/cover")

    response = api.get(cover_url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert _close(_colour(response.content), RED)  # January, not May
    assert list((settings.cover_cache_dir / str(magazine["id"])).glob("*.jpg"))

    again = api.get(cover_url, headers={"If-None-Match": response.headers["etag"]})
    assert again.status_code == 304


def test_broken_first_issue_falls_back_to_the_next(
    api: TestClient, magazine: dict, library_dir: Path
) -> None:
    folder = library_dir / magazine["folder"]
    (folder / "NG 2024-01.pdf").parent.mkdir(parents=True, exist_ok=True)
    (folder / "NG 2024-01.pdf").write_bytes(b"truncated download")
    _pdf(folder / "NG 2024-02.pdf", BLUE)
    api.post(SCAN, json={})
    for _ in range(2):  # the second request uses the cached failure
        response = api.get(f"/api/v1/magazine/{magazine['id']}/cover")
        assert _close(_colour(response.content), BLUE)


def test_cover_is_404_without_a_readable_file(api: TestClient, magazine: dict) -> None:
    assert api.get(f"/api/v1/magazine/{magazine['id']}/cover").status_code == 404


def test_cover_requires_the_api_key(api: TestClient, magazine: dict) -> None:
    url = f"/api/v1/magazine/{magazine['id']}/cover"
    assert api.get(url, headers={"X-Api-Key": ""}).status_code == 401
