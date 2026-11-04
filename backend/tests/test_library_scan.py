from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SCAN = "/api/v1/library/scan"


def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def ng_dir(library_dir: Path, magazine: dict) -> Path:
    return library_dir / magazine["folder"]


def _issues(api: TestClient, magazine: dict) -> dict[str, dict]:
    return {
        i["issueNumber"]: i for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    }


def test_scan_imports_files_and_creates_issues(
    api: TestClient, magazine: dict, root_folder: dict, ng_dir: Path
) -> None:
    api.post(
        "/api/v1/issue",
        json={
            "magazineId": magazine["id"],
            "issueNumber": "2014-07",
            "publishDate": "2014-07-01",
            "monitored": True,
        },
    )
    _touch(ng_dir / "Season 2014" / "National Geographic - 2014-07 - Issue 2014-07.pdf", 1234)
    _touch(ng_dir / "Season 2014" / "National.Geographic.2014.08.epub")
    _touch(ng_dir / "notes.txt")  # not a magazine format: ignored
    _touch(ng_dir / ".hidden.pdf")

    [result] = api.post(SCAN, json={}).json()
    assert result == {
        "rootFolderId": root_folder["id"],
        "path": root_folder["path"],
        "filesFound": 2,
        "filesAdded": 2,
        "filesRemoved": 0,
        "issuesCreated": 1,
        "magazinesCreated": 0,
        "unmapped": 0,
    }
    issues = _issues(api, magazine)
    july = issues["2014-07"]
    assert july["status"] == "downloaded"
    assert (
        july["file"]["relativePath"]
        == "Season 2014/National Geographic - 2014-07 - Issue 2014-07.pdf"
    )
    assert july["file"]["size"] == 1234
    assert july["file"]["quality"] == "pdf"
    august = issues["2014-08"]
    assert august["publishDate"] == "2014-08-01"
    assert august["file"]["format"] == "epub"
    assert august["monitored"] is False

    stats = api.get(f"/api/v1/magazine/{magazine['id']}").json()["statistics"]
    assert stats["downloadedCount"] == 2
    assert stats["sizeOnDisk"] == 1244


def test_rescan_is_idempotent(api: TestClient, magazine: dict, ng_dir: Path) -> None:
    _touch(ng_dir / "NG 2014-07.pdf")
    api.post(SCAN, json={})
    [again] = api.post(SCAN, json={}).json()
    assert (again["filesAdded"], again["issuesCreated"], again["filesFound"]) == (0, 0, 1)


def test_scan_matches_issue_by_date(api: TestClient, magazine: dict, ng_dir: Path) -> None:
    api.post(
        "/api/v1/issue",
        json={
            "magazineId": magazine["id"],
            "issueNumber": "Summer Special",
            "publishDate": "2014-07-15",
        },
    )
    _touch(ng_dir / "National Geographic July 2014.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["issuesCreated"] == 0
    assert _issues(api, magazine)["Summer Special"]["status"] == "downloaded"


def test_removed_files_are_detected(api: TestClient, magazine: dict, ng_dir: Path) -> None:
    api.post(
        "/api/v1/issue",
        json={"magazineId": magazine["id"], "issueNumber": "128", "monitored": True},
    )
    keep = _touch(ng_dir / "NG Issue 129.pdf")
    gone = _touch(ng_dir / "NG Issue 128.pdf")
    api.post(SCAN, json={})
    gone.unlink()
    [result] = api.post(SCAN, json={}).json()
    assert result["filesRemoved"] == 1
    issues = _issues(api, magazine)
    assert issues["128"]["status"] == "wanted"  # monitored, so wanted again
    assert issues["128"]["file"] is None
    assert keep.exists()


def test_moved_file_is_followed(api: TestClient, magazine: dict, ng_dir: Path) -> None:
    old = _touch(ng_dir / "NG Issue 5.pdf")
    api.post(SCAN, json={})
    (ng_dir / "Season 2014").mkdir()
    old.rename(ng_dir / "Season 2014" / "NG Issue 5.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["filesAdded"] == 1
    assert result["filesRemoved"] == 0
    assert _issues(api, magazine)["5"]["file"]["relativePath"] == "Season 2014/NG Issue 5.pdf"


def test_unmapped_files(api: TestClient, magazine: dict, library_dir: Path, ng_dir: Path) -> None:
    _touch(library_dir / "loose 2024-01.pdf")
    _touch(ng_dir / "cover.pdf")
    _touch(ng_dir / "NG Issue 7.pdf")
    _touch(ng_dir / "Season 2024" / "National Geographic No 7.pdf")  # same issue again

    [result] = api.post(SCAN, json={}).json()
    assert result["unmapped"] == 3
    reasons = {u["relativePath"]: u["reason"] for u in api.get("/api/v1/library/unmapped").json()}
    assert reasons == {
        "loose 2024-01.pdf": "Not inside a magazine folder",
        "National Geographic (1888)/cover.pdf": "Could not determine the issue from the file name",
        "National Geographic (1888)/Season 2024/National Geographic No 7.pdf": (
            "Issue 7 already has a file"
        ),
    }

    # Unmapped list is replaced, not appended, on the next scan.
    (library_dir / "loose 2024-01.pdf").unlink()
    api.post(SCAN, json={})
    assert len(api.get("/api/v1/library/unmapped").json()) == 2


def test_fuzzy_folder_match_adopts_folder(
    api: TestClient, magazine: dict, library_dir: Path
) -> None:
    _touch(library_dir / "National Geographics" / "NG 2024-03.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["filesAdded"] == 1
    assert api.get(f"/api/v1/magazine/{magazine['id']}").json()["folder"] == "National Geographics"


def test_alternate_title_folder_match(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    mag = api.post(
        "/api/v1/magazine", json={"title": "National Geographic", "alternateTitles": ["Nat Geo"]}
    ).json()
    _touch(library_dir / "Nat Geo" / "Nat Geo 2024-03.pdf")
    api.post(SCAN, json={})
    assert _issues(api, mag)["2024-03"]["status"] == "downloaded"


def test_lookalike_folder_is_not_adopted_when_real_folder_exists(
    api: TestClient, magazine: dict, library_dir: Path, ng_dir: Path
) -> None:
    _touch(ng_dir / "NG 2024-01.pdf")
    _touch(library_dir / "National Geographics" / "NG 2024-02.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["unmapped"] == 1
    assert api.get(f"/api/v1/magazine/{magazine['id']}").json()["folder"] == magazine["folder"]


def test_folder_differing_only_in_case_is_adopted(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    """An existing "ACE" folder for a magazine named "Ace". On a case-insensitive share
    "Ace" opens "ACE", which must not make the folder a look-alike of itself."""
    mag = api.post("/api/v1/magazine", json={"title": "Ace"}).json()
    _touch(library_dir / "ACE" / "Ace 2024-03.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["unmapped"] == 0
    assert api.get(f"/api/v1/magazine/{mag['id']}").json()["folder"] == "ACE"
    assert _issues(api, mag)["2024-03"]["status"] == "downloaded"


def test_empty_root_with_known_files_is_refused(
    api: TestClient, magazine: dict, library_dir: Path, ng_dir: Path
) -> None:
    """An unmounted drive must not wipe the library."""
    pdf = _touch(ng_dir / "NG 2024-01.pdf")
    api.post(SCAN, json={})
    pdf.unlink()
    ng_dir.rmdir()
    response = api.post(SCAN, json={})
    assert response.status_code == 400
    assert "mounted" in response.json()["message"]
    assert _issues(api, magazine)["2024-01"]["status"] == "downloaded"


def test_missing_root_folder_is_an_error(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    library_dir.rmdir()
    response = api.post(SCAN, json={"rootFolderId": root_folder["id"]})
    assert response.status_code == 400
    assert "not accessible" in response.json()["message"]
    assert api.get("/api/v1/rootfolder").json()[0]["accessible"] is False


def test_unknown_folders_become_unmonitored_magazines(
    api: TestClient, magazine: dict, root_folder: dict, library_dir: Path
) -> None:
    for month in ("01", "02", "03", "04"):
        _touch(library_dir / "Viz (1982)" / f"Viz {month} 2024.pdf")
    _touch(library_dir / "Hackspace" / "HackSpace 2024-06-01.pdf")
    (library_dir / "Empty Folder").mkdir()
    _touch(library_dir / "Notes Only" / "readme.txt")

    [result] = api.post(SCAN, json={}).json()
    assert result["magazinesCreated"] == 2
    assert result["filesAdded"] == 5
    assert result["unmapped"] == 0
    created = {m["title"]: m for m in api.get("/api/v1/magazine").json()}
    assert set(created) == {"National Geographic", "Viz", "Hackspace"}  # no empty/junk ones

    viz = created["Viz"]
    assert viz["folder"] == "Viz (1982)"  # the existing folder, as it is
    assert viz["firstIssueYear"] == 1982
    assert viz["rootFolderId"] == root_folder["id"]
    assert viz["monitored"] is False
    assert viz["frequency"] == "monthly"
    assert viz["statistics"]["downloadedCount"] == 4
    assert created["Hackspace"]["frequency"] == "ad-hoc"  # one issue: can't tell

    # Next scan maps the folders to the magazines it made instead of adding more.
    [again] = api.post(SCAN, json={}).json()
    assert again["magazinesCreated"] == 0 and again["filesAdded"] == 0


def test_folder_for_a_magazine_in_another_root_stays_unmapped(
    api: TestClient, magazine: dict, tmp_path: Path
) -> None:
    other = tmp_path / "other-root"
    _touch(other / "National Geographic" / "NG 2024-01.pdf")
    root = api.post("/api/v1/rootfolder", json={"path": str(other)}).json()
    [result] = api.post(SCAN, json={"rootFolderId": root["id"]}).json()
    assert result["magazinesCreated"] == 0
    [unmapped] = api.get("/api/v1/library/unmapped").json()
    assert unmapped["reason"].startswith("Could not add a magazine for this folder:")
    assert "already exists" in unmapped["reason"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Viz (1982)", ("Viz", 1982)),
        ("ACE", ("ACE", None)),
        ("National Geographic ", ("National Geographic", None)),
        ("Wired (UK) (1993)", ("Wired (UK)", 1993)),
        ("2000 AD", ("2000 AD", None)),
    ],
)
def test_title_from_folder(name: str, expected: tuple[str, int | None]) -> None:
    from magarr.importers.library_scan import title_from_folder

    assert title_from_folder(name) == expected


def test_one_off_books_in_an_ad_hoc_magazine_are_issues_named_by_title(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    books = api.post(
        "/api/v1/magazine", json={"title": "Fusion Retro Books", "frequency": "ad-hoc"}
    ).json()
    _touch(library_dir / books["folder"] / "The History of Ocean Software.pdf")
    _touch(library_dir / books["folder"] / "The Story of the Commodore Amiga in Pixels.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["unmapped"] == 0
    assert set(_issues(api, books)) == {
        "The History of Ocean Software",
        "The Story of the Commodore Amiga in Pixels",
    }
    [again] = api.post(SCAN, json={}).json()  # stable on rescan
    assert (again["filesAdded"], again["issuesCreated"]) == (0, 0)


def test_titles_are_not_issues_in_a_regular_magazine(
    api: TestClient, magazine: dict, ng_dir: Path
) -> None:
    _touch(ng_dir / "The Best of National Geographic.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert result["unmapped"] == 1


def test_a_new_folder_of_books_becomes_an_ad_hoc_collection(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    _touch(library_dir / "Retro Gamer Collection" / "Ultimate Retro Hardware Guide.pdf")
    _touch(library_dir / "Retro Gamer Collection" / "Retro Gamer Book of Arcade Classics.pdf")
    [result] = api.post(SCAN, json={}).json()
    assert (result["magazinesCreated"], result["unmapped"]) == (1, 0)
    [mag] = [
        m for m in api.get("/api/v1/magazine").json() if m["title"] == "Retro Gamer Collection"
    ]
    assert mag["frequency"] == "ad-hoc"
    assert len(_issues(api, mag)) == 2


def test_month_13_specials_are_scanned_with_their_names(
    api: TestClient, root_folder: dict, library_dir: Path
) -> None:
    fsm = api.post("/api/v1/magazine", json={"title": "Fine Scale Modeler"}).json()
    folder = library_dir / fsm["folder"]
    _touch(folder / "2412 Fine Scale Modeler.pdf")
    _touch(folder / "2413 Fine Scale Modeler.pdf")
    _touch(folder / "2513 Fine Scale Modeler Ship Handbook.pdf")
    api.post(SCAN, json={})
    issues = _issues(api, fsm)
    assert set(issues) == {"2024-12", "Special 2024", "Ship Handbook 2025"}
    assert issues["Special 2024"]["publishDate"] == "2024-12-01"
    # Sorted after the December issue.
    assert issues["Special 2024"]["sortIndex"] > issues["2024-12"]["sortIndex"]
