from pathlib import Path

from fastapi.testclient import TestClient

# --- Root folders -----------------------------------------------------------------------------


def test_root_folder_crud(api: TestClient, tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()

    a = api.post("/api/v1/rootfolder", json={"path": f"{first}/"}).json()
    assert a["path"] == str(first)  # trailing slash normalized
    assert a["isDefault"] is True
    assert a["accessible"] is True
    assert a["freeSpace"] > 0
    b = api.post("/api/v1/rootfolder", json={"path": str(second)}).json()
    assert b["isDefault"] is False

    api.patch(f"/api/v1/rootfolder/{b['id']}", json={"isDefault": True})
    defaults = {r["id"]: r["isDefault"] for r in api.get("/api/v1/rootfolder").json()}
    assert defaults == {a["id"]: False, b["id"]: True}

    assert api.delete(f"/api/v1/rootfolder/{b['id']}").status_code == 204
    remaining = api.get("/api/v1/rootfolder").json()
    assert [(r["id"], r["isDefault"]) for r in remaining] == [(a["id"], True)]


def test_root_folder_validation(api: TestClient, tmp_path: Path) -> None:
    missing = api.post("/api/v1/rootfolder", json={"path": str(tmp_path / "nope")})
    assert missing.status_code == 400
    assert "does not exist" in missing.json()["message"]
    assert api.post("/api/v1/rootfolder", json={"path": "relative/dir"}).status_code == 400
    api.post("/api/v1/rootfolder", json={"path": str(tmp_path)})
    assert api.post("/api/v1/rootfolder", json={"path": str(tmp_path)}).status_code == 409


def test_root_folder_in_use_cannot_be_deleted(
    api: TestClient, root_folder: dict, magazine: dict
) -> None:
    response = api.delete(f"/api/v1/rootfolder/{root_folder['id']}")
    assert response.status_code == 409
    assert "used by 1 magazine" in response.json()["message"]


# --- Quality profiles -------------------------------------------------------------------------


def test_default_profile_is_seeded(api: TestClient) -> None:
    profiles = api.get("/api/v1/qualityprofile").json()
    assert [p["name"] for p in profiles] == ["Any"]
    items = profiles[0]["items"]
    assert items[0]["quality"] == "pdf_hires"
    assert all(i["allowed"] for i in items)
    assert [i["quality"] for i in items if i["upgradeUntil"]] == ["pdf_hires"]
    assert len(items) == len(api.get("/api/v1/quality").json())


def test_profile_crud(api: TestClient) -> None:
    body = {
        "name": "PDF only",
        "items": [{"quality": "pdf", "allowed": True, "maxSizeMb": 200, "upgradeUntil": True}],
    }
    created = api.post("/api/v1/qualityprofile", json=body)
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["items"][0] == {
        "quality": "pdf",
        "allowed": True,
        "maxSizeMb": 200,
        "upgradeUntil": True,
    }
    # Omitted qualities are appended as not allowed.
    assert not any(i["allowed"] for i in profile["items"][1:])

    body["name"] = "PDF/EPUB"
    body["items"].append({"quality": "epub"})
    updated = api.put(f"/api/v1/qualityprofile/{profile['id']}", json=body).json()
    assert updated["name"] == "PDF/EPUB"
    assert [i["quality"] for i in updated["items"][:2]] == ["pdf", "epub"]

    assert api.delete(f"/api/v1/qualityprofile/{profile['id']}").status_code == 204


def test_profile_validation(api: TestClient) -> None:
    def post(items: list[dict], name: str = "X") -> int:
        return api.post("/api/v1/qualityprofile", json={"name": name, "items": items}).status_code

    assert post([{"quality": "bogus"}]) == 400
    assert post([{"quality": "pdf"}, {"quality": "pdf"}]) == 400
    assert post([{"quality": "pdf", "allowed": False}]) == 400
    assert (
        post([{"quality": "pdf", "upgradeUntil": True}, {"quality": "epub", "upgradeUntil": True}])
        == 400
    )
    assert (
        post([{"quality": "pdf"}, {"quality": "epub", "allowed": False, "upgradeUntil": True}])
        == 400
    )
    assert post([{"quality": "pdf", "maxSizeMb": 0}]) == 400
    assert post([{"quality": "pdf"}], name="any") == 409  # case-insensitive duplicate


def test_profile_delete_guards(api: TestClient, magazine: dict) -> None:
    profile_id = magazine["qualityProfileId"]
    assert api.delete(f"/api/v1/qualityprofile/{profile_id}").status_code == 409
    api.delete(f"/api/v1/magazine/{magazine['id']}")
    last = api.delete(f"/api/v1/qualityprofile/{profile_id}")
    assert last.status_code == 409
    assert "last" in last.json()["message"]


# --- Naming -----------------------------------------------------------------------------------


def test_naming_defaults_and_update(api: TestClient) -> None:
    naming = api.get("/api/v1/config/naming").json()
    assert naming["issueFilePattern"] == "{magazine_title} - {year}-{month} - Issue {issue_number}"
    assert naming["yearFolderPattern"] == ""  # flat by default
    naming["yearFolderPattern"] = "{year}"
    saved = api.put("/api/v1/config/naming", json=naming)
    assert saved.status_code == 200
    assert api.get("/api/v1/config/naming").json()["yearFolderPattern"] == "{year}"


def test_naming_rejects_invalid(api: TestClient) -> None:
    naming = api.get("/api/v1/config/naming").json()
    naming["issueFilePattern"] = "{magazine_title}"
    response = api.put("/api/v1/config/naming", json=naming)
    assert response.status_code == 400
    assert "{issue_number}" in response.json()["message"]


def test_issue_numbers_that_render_alike_collide(api: TestClient, magazine: dict) -> None:
    def add(number: str) -> int:
        body = {"magazineId": magazine["id"], "issueNumber": number}
        return api.post("/api/v1/issue", json=body).status_code

    assert add("1-2") == 201
    assert add("1/2") == 409  # "/" is replaced with "-", so both render "... Issue 1-2"


def test_naming_change_that_causes_collisions_is_rejected(api: TestClient, magazine: dict) -> None:
    for number in ("12", "1/2"):  # render "Issue 12" and "Issue 1-2"
        body = {"magazineId": magazine["id"], "issueNumber": number}
        assert api.post("/api/v1/issue", json=body).status_code == 201
    naming = api.get("/api/v1/config/naming").json()
    naming["replaceIllegalCharacters"] = False  # "1/2" would now render "12"
    response = api.put("/api/v1/config/naming", json=naming)
    assert response.status_code == 409
    assert "National Geographic" in response.json()["message"]
    assert api.get("/api/v1/config/naming").json()["replaceIllegalCharacters"] is True


def test_naming_preview(api: TestClient) -> None:
    naming = api.get("/api/v1/config/naming").json()
    preview = api.post("/api/v1/config/naming/preview", json=naming).json()
    assert preview["magazineFolder"] == "National Geographic (1888)"
    assert preview["issuePath"] == (
        "National Geographic (1888)/National Geographic - 2014-07 - Issue 045.pdf"
    )
    assert "issue_number" in preview["tokens"]["issueFile"]
