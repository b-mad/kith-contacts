"""Command palette (S-12, ADR-0017) and the shortcut list (N-09)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.privacy import COOKIE


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def make(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.mark.req("S-12")
def test_palette_finds_people_lists_tags_and_saved_searches(
    client: TestClient, types: dict[str, int]
) -> None:
    from tests.test_presenting import csrf

    maria = make(
        client,
        display_name="Maria Lopez",
        contact_type_id=types["Employee"],
        title="Integration lead",
        company="Northwind",
    )
    token = csrf(client)
    client.post("/lists", data={"csrf_token": token, "name": "Maria's rollout"})
    client.post(
        "/selection/tag",
        data={"csrf_token": token, "tag": "maria-fans", "contact_ids": maria["id"]},
    )
    client.post(
        "/saved-searches", data={"csrf_token": token, "name": "Maria watchers", "query": "q=maria"}
    )
    data = client.get("/palette", params={"q": "maria"}).json()
    assert data["people"] == [
        {
            "id": maria["id"],
            "name": "Maria Lopez",
            "sub": "Integration lead · Northwind",
            "url": f"/contacts/{maria['id']}",
        }
    ]
    assert [x["name"] for x in data["lists"]] == ["Maria's rollout"]
    assert data["tags"] == [{"name": "maria-fans", "count": 1, "url": "/?tag=maria-fans"}]
    assert [x["url"] for x in data["saved"]] == ["/?q=maria"]


@pytest.mark.req("S-12")
def test_palette_with_no_query_returns_nothing(client: TestClient) -> None:
    assert client.get("/palette").json() == {"people": [], "lists": [], "tags": [], "saved": []}


@pytest.mark.req("S-12", "P-02")
def test_palette_respects_presenting_mode(client: TestClient, types: dict[str, int]) -> None:
    from tests.test_presenting import csrf

    hidden = make(client, display_name="Zed Secret", contact_type_id=types["Employee"])
    client.post(
        f"/contacts/{hidden['id']}/private",
        data={"csrf_token": csrf(client), "private": "1"},
    )
    assert client.get("/palette", params={"q": "zed"}).json()["people"]
    client.cookies.set(COOKIE, "1")
    assert client.get("/palette", params={"q": "zed"}).json()["people"] == []
    page = client.get("/").text
    assert "Stop presenting <kbd>⇧P</kbd>" in page
    assert 'data-href="/settings/privacy"' not in page  # not offered while presenting


@pytest.mark.req("S-12", "N-09")
def test_every_page_has_the_palette_and_the_shortcut_list(client: TestClient) -> None:
    page = client.get("/lists").text
    assert 'data-testid="palette-open"' in page
    assert "data-palette-actions" in page
    assert 'data-testid="shortcuts"' in page
    assert "Copy the selected people's emails" in page
    assert 'aria-keyshortcuts="Control+K Meta+K"' in page
