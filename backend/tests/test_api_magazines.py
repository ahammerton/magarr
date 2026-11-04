from fastapi.testclient import TestClient

# --- Magazines --------------------------------------------------------------------------------


def test_create_magazine_with_defaults(api: TestClient, magazine: dict, root_folder: dict) -> None:
    assert magazine["folder"] == "National Geographic (1888)"
    assert magazine["path"] == f"{root_folder['path']}/National Geographic (1888)"
    assert magazine["rootFolderId"] == root_folder["id"]
    assert magazine["qualityProfileId"] == api.get("/api/v1/qualityprofile").json()[0]["id"]
    assert magazine["monitored"] is True
    assert magazine["language"] == "en"
    assert magazine["statistics"] == {
        "issueCount": 0,
        "downloadedCount": 0,
        "wantedCount": 0,
        "sizeOnDisk": 0,
    }


def test_create_requires_root_folder(api: TestClient) -> None:
    response = api.post("/api/v1/magazine", json={"title": "Wired"})
    assert response.status_code == 400
    assert "root folder" in response.json()["message"]


def test_duplicate_titles_rejected_including_alternates(api: TestClient, root_folder: dict) -> None:
    api.post("/api/v1/magazine", json={"title": "Wired", "alternateTitles": ["Wired UK"]})
    assert api.post("/api/v1/magazine", json={"title": "wired"}).status_code == 409
    assert api.post("/api/v1/magazine", json={"title": "WIRED UK"}).status_code == 409


def test_list_is_sorted_ignoring_articles(api: TestClient, root_folder: dict) -> None:
    for title in ("Wired", "The Economist", "Byte"):
        api.post("/api/v1/magazine", json={"title": title})
    titles = [m["title"] for m in api.get("/api/v1/magazine").json()]
    assert titles == ["Byte", "The Economist", "Wired"]


def test_update_magazine(api: TestClient, magazine: dict) -> None:
    response = api.patch(
        f"/api/v1/magazine/{magazine['id']}",
        json={
            "title": "Nat Geo",
            "alternateTitles": ["NatGeo", " natgeo ", ""],
            "tags": ["science", "Science"],
            "monitored": False,
            "frequency": "weekly",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["title"] == "Nat Geo"
    assert updated["alternateTitles"] == ["NatGeo"]
    assert updated["tags"] == ["science"]
    assert updated["monitored"] is False
    assert updated["frequency"] == "weekly"
    assert updated["folder"] == magazine["folder"]  # folder is fixed at creation


def test_update_validation(api: TestClient, magazine: dict) -> None:
    url = f"/api/v1/magazine/{magazine['id']}"
    assert api.patch(url, json={"qualityProfileId": 999}).status_code == 400
    assert api.patch(url, json={"monitored": None}).status_code == 400
    assert api.patch(url, json={"folder": "../escape"}).status_code == 400
    assert api.patch(url, json={"issueNamingTemplate": "{magazine_title}"}).status_code == 400
    assert api.patch(url, json={"frequency": "daily"}).status_code == 422
    assert api.patch(url, json={"issueNamingTemplate": "{issue_number}"}).status_code == 200
    assert api.patch(url, json={"issueNamingTemplate": ""}).json()["issueNamingTemplate"] is None


def test_delete_magazine_cascades_issues(api: TestClient, magazine: dict) -> None:
    created = api.post(
        "/api/v1/issue", json={"magazineId": magazine["id"], "issueNumber": "1"}
    ).json()
    assert api.delete(f"/api/v1/magazine/{magazine['id']}").status_code == 204
    assert api.get(f"/api/v1/magazine/{magazine['id']}").status_code == 404
    assert api.get(f"/api/v1/issue/{created['id']}").status_code == 404


def test_unknown_magazine_is_404_json(api: TestClient) -> None:
    response = api.get("/api/v1/magazine/999")
    assert response.status_code == 404
    assert response.json() == {"message": "Magazine 999 not found"}


# --- Issues -----------------------------------------------------------------------------------


def test_issue_crud(api: TestClient, magazine: dict) -> None:
    created = api.post(
        "/api/v1/issue",
        json={
            "magazineId": magazine["id"],
            "issueNumber": "128",
            "publishDate": "2024-05-01",
            "monitored": True,
        },
    )
    assert created.status_code == 201, created.text
    issue = created.json()
    assert issue["status"] == "wanted"
    assert issue["sortIndex"] == 128.0
    assert issue["file"] is None

    dup = api.post("/api/v1/issue", json={"magazineId": magazine["id"], "issueNumber": "128"})
    assert dup.status_code == 409

    patched = api.patch(
        f"/api/v1/issue/{issue['id']}", json={"issueNumber": "129", "title": "Ocean"}
    )
    assert patched.json()["sortIndex"] == 129.0
    assert patched.json()["title"] == "Ocean"

    ignored = api.patch(f"/api/v1/issue/{issue['id']}", json={"status": "ignored"}).json()
    assert (ignored["status"], ignored["monitored"]) == ("ignored", False)
    assert (
        api.patch(f"/api/v1/issue/{issue['id']}", json={"status": "downloaded"}).status_code == 400
    )

    assert api.delete(f"/api/v1/issue/{issue['id']}").status_code == 204
    assert api.get(f"/api/v1/issue?magazineId={magazine['id']}").json() == []


def test_issue_list_is_newest_first(api: TestClient, magazine: dict) -> None:
    for number in ("2", "10", "1"):
        api.post("/api/v1/issue", json={"magazineId": magazine["id"], "issueNumber": number})
    issues = api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    assert [i["issueNumber"] for i in issues] == ["10", "2", "1"]


def test_issue_list_requires_known_magazine(api: TestClient) -> None:
    assert api.get("/api/v1/issue?magazineId=999").status_code == 404


def test_bulk_update(api: TestClient, magazine: dict) -> None:
    ids = [
        api.post(
            "/api/v1/issue", json={"magazineId": magazine["id"], "issueNumber": str(n)}
        ).json()["id"]
        for n in range(3)
    ]
    wanted = api.post("/api/v1/issue/bulk", json={"ids": ids[:2], "monitored": True}).json()
    assert {i["status"] for i in wanted} == {"wanted"}
    assert api.post("/api/v1/issue/bulk", json={"ids": ids}).status_code == 400
    assert (
        api.post("/api/v1/issue/bulk", json={"ids": [*ids, 999], "monitored": True}).status_code
        == 404
    )
    ignored = api.post("/api/v1/issue/bulk", json={"ids": ids, "status": "ignored"}).json()
    assert {i["status"] for i in ignored} == {"ignored"}


# --- Generate expected issues -----------------------------------------------------------------


def test_generate_monthly_issues(api: TestClient, magazine: dict) -> None:
    url = f"/api/v1/magazine/{magazine['id']}/generate-issues"
    result = api.post(url, json={"start": "2024-01-01", "count": 24}).json()
    assert len(result["created"]) == 24
    assert result["skipped"] == 0
    numbers = [i["issueNumber"] for i in result["created"]]
    assert numbers[0] == "2024-01"
    assert numbers[-1] == "2025-12"
    assert {i["status"] for i in result["created"]} == {"missing"}

    again = api.post(url, json={"start": "2025-07-01", "count": 12, "monitored": True}).json()
    assert again["skipped"] == 6
    assert again["created"][0]["issueNumber"] == "2026-01"
    assert {i["status"] for i in again["created"]} == {"wanted"}


def test_generate_numbered_issues_with_dates(api: TestClient, magazine: dict) -> None:
    url = f"/api/v1/magazine/{magazine['id']}/generate-issues"
    result = api.post(url, json={"start": "2026-09-01", "count": 3, "firstNumber": 360}).json()
    assert [(i["issueNumber"], i["publishDate"], i["sortIndex"]) for i in result["created"]] == [
        ("360", "2026-09-01", 360.0),
        ("361", "2026-10-01", 361.0),
        ("362", "2026-11-01", 362.0),
    ]
    # Overlapping run: existing numbers are skipped.
    again = api.post(url, json={"start": "2026-11-01", "count": 3, "firstNumber": 362}).json()
    assert [i["issueNumber"] for i in again["created"]] == ["363", "364"]
    assert again["skipped"] == 1


def test_generate_numbered_without_dates(api: TestClient, magazine: dict) -> None:
    url = f"/api/v1/magazine/{magazine['id']}/generate-issues"
    result = api.post(url, json={"count": 2, "firstNumber": 1, "monitored": True}).json()
    assert [(i["issueNumber"], i["publishDate"], i["status"]) for i in result["created"]] == [
        ("1", None, "wanted"),
        ("2", None, "wanted"),
    ]


def test_generate_numbered_for_ad_hoc(api: TestClient, root_folder: dict) -> None:
    mag = api.post("/api/v1/magazine", json={"title": "Zine", "frequency": "ad-hoc"}).json()
    url = f"/api/v1/magazine/{mag['id']}/generate-issues"
    # A start date is ignored: ad-hoc has no schedule to space issues out.
    result = api.post(url, json={"start": "2026-01-01", "count": 3, "firstNumber": 40}).json()
    assert [(i["issueNumber"], i["publishDate"]) for i in result["created"]] == [
        ("40", None),
        ("41", None),
        ("42", None),
    ]


def test_generate_by_date_needs_a_start(api: TestClient, magazine: dict) -> None:
    response = api.post(f"/api/v1/magazine/{magazine['id']}/generate-issues", json={"count": 2})
    assert response.status_code == 400
    assert "first issue date" in response.json()["message"]
    negative = api.post(
        f"/api/v1/magazine/{magazine['id']}/generate-issues", json={"count": 2, "firstNumber": -1}
    )
    assert negative.status_code == 422


def test_generate_rejects_ad_hoc_and_bad_counts(api: TestClient, root_folder: dict) -> None:
    mag = api.post("/api/v1/magazine", json={"title": "Zine", "frequency": "ad-hoc"}).json()
    url = f"/api/v1/magazine/{mag['id']}/generate-issues"
    response = api.post(url, json={"start": "2024-01-01", "count": 3})
    assert response.status_code == 400
    assert "Ad-hoc magazines have no schedule" in response.json()["message"]
    assert "number them instead" in response.json()["message"]
    assert api.post(url, json={"start": "2024-01-01", "count": 0}).status_code == 422


# --- Phase 1 definition of done ---------------------------------------------------------------


def test_definition_of_done(api: TestClient, root_folder: dict) -> None:
    """User adds "National Geographic", generates 24 monthly issues, marks 6 wanted."""
    mag = api.post(
        "/api/v1/magazine", json={"title": "National Geographic", "frequency": "monthly"}
    ).json()
    created = api.post(
        f"/api/v1/magazine/{mag['id']}/generate-issues", json={"start": "2025-01-01", "count": 24}
    ).json()["created"]
    assert len(created) == 24

    api.post("/api/v1/issue/bulk", json={"ids": [i["id"] for i in created[:6]], "monitored": True})

    issues = api.get(f"/api/v1/issue?magazineId={mag['id']}").json()
    assert sum(i["status"] == "wanted" for i in issues) == 6
    stats = api.get(f"/api/v1/magazine/{mag['id']}").json()["statistics"]
    assert stats["issueCount"] == 24
    assert stats["wantedCount"] == 6


def test_bulk_edit_and_delete(api: TestClient, root_folder: dict) -> None:
    ids = [api.post("/api/v1/magazine", json={"title": t}).json()["id"] for t in ("A", "B", "C")]
    edited = api.put(
        "/api/v1/magazine/editor",
        json={"ids": ids[:2], "monitored": False, "grabNewSpecials": True},
    )
    assert edited.status_code == 200
    assert [(m["monitored"], m["grabNewSpecials"]) for m in edited.json()] == [(False, True)] * 2
    assert api.get(f"/api/v1/magazine/{ids[2]}").json()["monitored"] is True  # untouched

    bad = api.put("/api/v1/magazine/editor", json={"ids": ids, "qualityProfileId": 999})
    assert bad.status_code == 400
    assert api.get(f"/api/v1/magazine/{ids[0]}").json()["qualityProfileId"] != 999  # none saved

    missing = api.put("/api/v1/magazine/editor", json={"ids": [ids[0], 12345], "monitored": True})
    assert missing.status_code == 404
    assert api.get(f"/api/v1/magazine/{ids[0]}").json()["monitored"] is False  # rolled back

    assert api.post("/api/v1/magazine/editor/delete", json={"ids": ids[:2]}).status_code == 204
    assert [m["title"] for m in api.get("/api/v1/magazine").json()] == ["C"]
