from fastapi.testclient import TestClient

URL = "/api/v1/magazine/import"


def test_import_into_existing_magazine(api: TestClient, magazine: dict) -> None:
    csv = (
        "Magazine,Issue,Date,Issue Title\n"
        "National Geographic,128,2024-05-01,The Ocean\n"
        "national geographic,129,2024-06,\n"
        "National Geographic,130,,\n"
    )
    result = api.post(URL, json={"csv": csv, "monitored": True}).json()
    assert result == {
        "issuesCreated": 3,
        "issuesUpdated": 0,
        "issuesUnchanged": 0,
        "magazinesCreated": [],
        "errors": [],
    }
    issues = {
        i["issueNumber"]: i for i in api.get(f"/api/v1/issue?magazineId={magazine['id']}").json()
    }
    assert issues["128"]["title"] == "The Ocean"
    assert issues["129"]["publishDate"] == "2024-06-01"
    assert issues["130"]["publishDate"] is None
    assert {i["status"] for i in issues.values()} == {"wanted"}


def test_reimport_updates_and_reports_unchanged(api: TestClient, magazine: dict) -> None:
    api.post(URL, json={"csv": "magazine,issue,date\nNational Geographic,1,2024-01-01\n"})
    result = api.post(
        URL,
        json={
            "csv": "magazine,issue,date\nNational Geographic,1,2024-02-01\nNational Geographic,1,\n"
        },
    ).json()
    assert (result["issuesUpdated"], result["issuesUnchanged"], result["issuesCreated"]) == (
        1,
        1,
        0,
    )


def test_row_errors_do_not_abort_the_import(api: TestClient, magazine: dict) -> None:
    csv = (
        "title,number,published\n"
        "National Geographic,1,2024-01-01\n"
        "Unknown Mag,1,2024-01-01\n"
        "National Geographic,,2024-01-01\n"
        "National Geographic,2,01/02/2024\n"
        ",,\n"
    )
    result = api.post(URL, json={"csv": csv}).json()
    assert result["issuesCreated"] == 1
    assert [(e["row"], e["message"].split(" ")[0]) for e in result["errors"]] == [
        (3, "Unknown"),
        (4, "Magazine"),
        (5, "Invalid"),
    ]


def test_create_missing_magazines(api: TestClient, root_folder: dict) -> None:
    csv = "magazine,issue\nWired,1\nWired,2\nByte,1\n"
    result = api.post(URL, json={"csv": csv, "createMissing": True}).json()
    assert result["magazinesCreated"] == ["Wired", "Byte"]
    assert result["issuesCreated"] == 3
    titles = sorted(m["title"] for m in api.get("/api/v1/magazine").json())
    assert titles == ["Byte", "Wired"]


def test_bad_headers(api: TestClient) -> None:
    response = api.post(URL, json={"csv": "foo,bar\n1,2\n"})
    assert response.status_code == 400
    assert "'magazine' and 'issue'" in response.json()["message"]
    assert api.post(URL, json={"csv": ""}).status_code == 400


def test_utf8_bom_is_tolerated(api: TestClient, magazine: dict) -> None:
    result = api.post(URL, json={"csv": "﻿magazine,issue\nNational Geographic,7\n"}).json()
    assert result["issuesCreated"] == 1
