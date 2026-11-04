import errno
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from magarr.domain.enums import ImportMode
from magarr.domain.media_settings import add_mapping, map_path
from magarr.importers import fileops
from magarr.importers.fileops import (
    ImportFileError,
    dispose,
    ensure_inside,
    transfer,
    unique_destination,
)


def _write(path: Path, data: bytes = b"pdf") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_unique_destination(tmp_path: Path) -> None:
    dest = tmp_path / "Wired - 2024-05.pdf"
    assert unique_destination(dest) == dest
    _write(dest)
    assert unique_destination(dest, current=dest) == dest  # it is the issue's own file
    assert unique_destination(dest).name == "Wired - 2024-05 - copy.pdf"
    _write(tmp_path / "Wired - 2024-05 - copy.pdf")
    assert unique_destination(dest).name == "Wired - 2024-05 - copy 2.pdf"


def test_move_copy_and_hardlink(tmp_path: Path) -> None:
    src = _write(tmp_path / "in" / "a.pdf", b"one")
    assert transfer(src, tmp_path / "lib" / "a.pdf", ImportMode.MOVE) is ImportMode.MOVE
    assert not src.exists() and (tmp_path / "lib" / "a.pdf").read_bytes() == b"one"

    src = _write(tmp_path / "in" / "b.pdf", b"two")
    assert transfer(src, tmp_path / "lib" / "b.pdf", ImportMode.COPY) is ImportMode.COPY
    assert src.exists() and (tmp_path / "lib" / "b.pdf").read_bytes() == b"two"

    src = _write(tmp_path / "in" / "c.pdf", b"three")
    assert transfer(src, tmp_path / "lib" / "c.pdf", ImportMode.HARDLINK) is ImportMode.HARDLINK
    assert os.stat(src).st_ino == os.stat(tmp_path / "lib" / "c.pdf").st_ino


def test_move_across_filesystems_copies_then_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = os.replace

    def cross_device(a, b):
        if not str(a).endswith(".partial"):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_replace(a, b)

    monkeypatch.setattr(fileops.os, "replace", cross_device)
    src = _write(tmp_path / "in" / "a.pdf", b"x" * 100)
    assert transfer(src, tmp_path / "lib" / "a.pdf", ImportMode.MOVE) is ImportMode.MOVE
    assert not src.exists() and (tmp_path / "lib" / "a.pdf").stat().st_size == 100
    assert not list((tmp_path / "lib").glob(".*.partial"))


def test_hardlink_falls_back_to_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(fileops.os, "link", no_links)
    src = _write(tmp_path / "in" / "a.pdf")
    assert transfer(src, tmp_path / "lib" / "a.pdf", ImportMode.HARDLINK) is ImportMode.COPY
    assert src.exists() and (tmp_path / "lib" / "a.pdf").exists()


def test_failed_copy_leaves_no_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_copy(a, b):
        Path(b).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(fileops.shutil, "copy2", broken_copy)
    src = _write(tmp_path / "in" / "a.pdf")
    with pytest.raises(OSError, match="disk full"):
        transfer(src, tmp_path / "lib" / "a.pdf", ImportMode.COPY)
    assert list((tmp_path / "lib").iterdir()) == []


def test_dispose_deletes_or_recycles(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    old = _write(library / "Wired" / "old.pdf")
    assert dispose(old, "", library) == "deleted" and not old.exists()

    old = _write(library / "Wired" / "old.pdf", b"v1")
    bin_dir = tmp_path / "bin"
    assert dispose(old, str(bin_dir), library).startswith("moved to")
    assert (bin_dir / "Wired" / "old.pdf").read_bytes() == b"v1"
    old = _write(library / "Wired" / "old.pdf", b"v2")
    dispose(old, str(bin_dir), library)  # name taken in the bin: timestamped copy
    assert len(list((bin_dir / "Wired").iterdir())) == 2
    assert dispose(library / "nope.pdf", "", library) == "missing"


def test_ensure_inside(tmp_path: Path) -> None:
    ensure_inside(tmp_path / "lib" / "a.pdf", tmp_path / "lib")
    with pytest.raises(ImportFileError, match="outside the library"):
        ensure_inside(tmp_path / "lib" / ".." / "evil.pdf", tmp_path / "lib")


def test_permissions(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    f = _write(library / "Wired" / "Season 2024" / "a.pdf")
    fileops.apply_permissions(f, library, "640", "750", None, None)
    assert oct(f.stat().st_mode & 0o777) == "0o640"
    assert oct((library / "Wired" / "Season 2024").stat().st_mode & 0o777) == "0o750"
    assert oct((library / "Wired").stat().st_mode & 0o777) == "0o750"


# --- remote path mappings ---------------------------------------------------------------------


def test_map_path_longest_prefix_and_host(api: TestClient) -> None:
    with api.app.state.session_factory() as session:
        add_mapping(session, "192.168.1.20", "/data", "/mnt/nas/data")
        add_mapping(session, "192.168.1.20", "/data/usenet/complete", "/downloads")
        add_mapping(session, "other", "/data", "/elsewhere")
        session.commit()
        host = "192.168.1.20"
        assert map_path(session, host, "/data/usenet/complete/NG/ng.pdf") == "/downloads/NG/ng.pdf"
        assert map_path(session, host, "/data/usenet/complete") == "/downloads"
        assert map_path(session, host, "/data/torrents/x") == "/mnt/nas/data/torrents/x"
        assert (
            map_path(session, host, "/database/x") == "/database/x"
        )  # prefix must be a whole segment
        assert map_path(session, "unknown", "/data/x") == "/data/x"
        assert (
            map_path(session, host.upper(), "C:\\data\\x") == "C:/data/x"
        )  # windows separators normalized


def test_mapping_and_settings_api(api: TestClient) -> None:
    created = api.post(
        "/api/v1/remotepathmapping",
        json={"host": "sab", "remotePath": "/data/", "localPath": "/mnt/data/"},
    )
    assert created.status_code == 201
    assert (created.json()["remotePath"], created.json()["localPath"]) == ("/data", "/mnt/data")
    assert (
        api.post(
            "/api/v1/remotepathmapping",
            json={"host": "sab", "remotePath": "/data", "localPath": "/x"},
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/api/v1/remotepathmapping",
            json={"host": "sab", "remotePath": "data", "localPath": "/x"},
        ).status_code
        == 400
    )
    assert api.delete(f"/api/v1/remotepathmapping/{created.json()['id']}").status_code == 204

    settings = api.get("/api/v1/config/mediamanagement").json()
    assert settings == {
        "autoImport": True,
        "usenetImportMode": "move",
        "torrentImportMode": "hardlink",
        "removeCompletedDownloads": True,
        "recycleBin": "",
        "fileChmod": "",
        "folderChmod": "",
        "chownUser": None,
        "chownGroup": None,
    }
    saved = api.put(
        "/api/v1/config/mediamanagement",
        json={**settings, "fileChmod": "664", "recycleBin": "/recycle/"},
    ).json()
    assert (saved["fileChmod"], saved["recycleBin"]) == ("664", "/recycle")
    assert (
        api.put("/api/v1/config/mediamanagement", json={**settings, "fileChmod": "999"}).status_code
        == 400
    )
    assert (
        api.put(
            "/api/v1/config/mediamanagement", json={**settings, "recycleBin": "rel"}
        ).status_code
        == 400
    )
    assert (
        api.put(
            "/api/v1/config/mediamanagement", json={**settings, "usenetImportMode": "teleport"}
        ).status_code
        == 422
    )


def test_prune_empty_dirs_stops_at_the_magazine_folder(tmp_path: Path) -> None:
    magazine = tmp_path / "lib" / "Wired"
    (magazine / "2024" / "deep").mkdir(parents=True)
    fileops.prune_empty_dirs(magazine / "2024" / "deep", magazine)
    assert not (magazine / "2024").exists() and magazine.exists()
    (magazine / "2025").mkdir()
    _write(magazine / "2025" / "keep.pdf")
    fileops.prune_empty_dirs(magazine / "2025", magazine)
    assert (magazine / "2025" / "keep.pdf").exists()


def test_move_falls_back_to_a_copy_when_the_source_is_read_only_to_us(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SABnzbd on a NAS writes as its own user: Magarr may read but not move or delete."""
    src = _write(tmp_path / "downloads" / "job" / "issue.pdf")
    dest = tmp_path / "library" / "Mag" / "issue.pdf"
    real_replace, real_unlink = os.replace, Path.unlink

    def replace(a, b):
        if Path(a) == src:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_replace(a, b)

    def unlink(self, missing_ok=False):
        if self == src:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(fileops.os, "replace", replace)
    monkeypatch.setattr(Path, "unlink", unlink)
    assert fileops.transfer(src, dest, ImportMode.MOVE) is ImportMode.COPY
    assert dest.read_bytes() == src.read_bytes()
    assert src.exists()


def test_move_still_fails_when_the_source_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _write(tmp_path / "downloads" / "issue.pdf")
    dest = tmp_path / "library" / "issue.pdf"

    def refuse(*_):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(fileops.os, "replace", refuse)
    monkeypatch.setattr(fileops, "_copy_atomically", refuse)
    with pytest.raises(PermissionError):
        fileops.transfer(src, dest, ImportMode.MOVE)
