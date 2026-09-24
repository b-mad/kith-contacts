"""Phase 2 pages: search, selection actions, tags, lists, favorites, company picker."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.web import safe_next, with_notice

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def csrf(client: TestClient) -> str:
    match = TOKEN.search(client.get("/contacts/new").text)
    assert match
    return match.group(1)


def post(client: TestClient, url: str, **fields: Any) -> Any:
    return client.post(url, data={"csrf_token": csrf(client), **fields}, follow_redirects=False)


def make(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture
def team(client: TestClient, types: dict[str, int]) -> dict[str, dict[str, Any]]:
    emp = types["Employee"]
    maria = make(
        client,
        display_name="Maria Lopez",
        contact_type_id=emp,
        team="Data Platform",
        company="Acme Health",
        emails=[{"email": "maria@acme.example"}],
    )
    dev = make(
        client,
        display_name="Dev Patel",
        contact_type_id=emp,
        team="Data Platform",
        company="Acme Health",
        manager_id=maria["id"],
        works_on="Lab results pipeline",
        emails=[{"email": "dev@acme.example"}],
    )
    rob = make(
        client,
        display_name="Robert Lin",
        contact_type_id=types["Customer"],
        company="Peachtree Labs",
        title="Lab Director",
    )
    return {"maria": maria, "dev": dev, "rob": rob}


# ---------------------------------------------------------------- search page (S-01 to S-05)


@pytest.mark.req("S-01", "S-02")
def test_search_page_shows_matches_with_context(client: TestClient, team: dict[str, Any]) -> None:
    html = client.get("/?q=lab+results+maria").text
    assert 'data-testid="search-input"' in html
    assert "Dev Patel" in html
    assert '<span class="match-field">manager:</span> Maria Lopez' in html
    assert "Robert Lin" not in html
    assert "matching “lab results maria”" in html


@pytest.mark.req("S-05")
def test_results_partial_for_live_search(client: TestClient, team: dict[str, Any]) -> None:
    response = client.get("/contacts/results?q=dev")
    assert response.status_code == 200
    assert "<html" not in response.text  # fragment only
    assert 'data-testid="result-row"' in response.text
    assert 'data-email="dev@acme.example"' in response.text


@pytest.mark.req("S-04")
def test_filter_chips_and_manager_filter(client: TestClient, team: dict[str, Any]) -> None:
    maria_id = team["maria"]["id"]
    html = client.get(f"/?manager={maria_id}&company=Acme+Health").text
    assert "Reports to Maria Lopez" in html
    assert "Company: Acme Health" in html
    assert "Dev Patel" in html
    assert html.count('data-testid="result-row"') == 1  # only Dev reports to Maria
    assert 'href="/?company=Acme+Health"' in html  # removing the manager chip keeps company


def test_no_results_message(client: TestClient, team: dict[str, Any]) -> None:
    assert 'data-testid="no-results"' in client.get("/?q=zzzzqq").text


def test_card_links_to_team_search(client: TestClient, team: dict[str, Any]) -> None:
    html = client.get(f"/contacts/{team['maria']['id']}").text
    assert f'href="/?manager={team["maria"]["id"]}" data-testid="see-team"' in html


@pytest.mark.req("S-01")
def test_search_api(client: TestClient, team: dict[str, Any]) -> None:
    hits = client.get("/api/search", params={"q": "lab director"}).json()
    assert hits[0]["contact"]["display_name"] == "Robert Lin"
    assert {"field": "title", "value": "Lab Director"} in hits[0]["matched"]
    assert client.get("/api/search", params={"q": "maria", "type": 999}).json() == []


# ------------------------------------------------------- selection actions (M-01, T-01, L-02)


@pytest.mark.req("M-01", "T-01")
def test_tag_selected_contacts(client: TestClient, team: dict[str, Any]) -> None:
    ids = [team["dev"]["id"], team["rob"]["id"]]
    response = post(client, "/selection/tag", contact_ids=ids, tag="HL7", next="/?q=lab")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/?q=lab&notice=tagged")
    tagged = {h["contact"]["display_name"] for h in client.get("/api/search?tag=hl7").json()}
    assert tagged == {"Dev Patel", "Robert Lin"}
    assert "Tagged 2 contact(s) with “HL7”." in client.get(response.headers["location"]).text


@pytest.mark.req("M-01", "L-02", "L-03")
def test_add_selected_contacts_to_new_list(client: TestClient, team: dict[str, Any]) -> None:
    ids = [team["dev"]["id"], team["rob"]["id"]]
    response = post(
        client, "/selection/list", contact_ids=ids, list_name="Q4 LIS integration", role_note="core"
    )
    location = response.headers["location"]
    page = client.get(location).text

    assert re.match(r"^/lists/\d+\?notice=listed", location)
    assert "Q4 LIS integration" in page
    assert "Added 2 contact(s)" in page
    assert page.count('data-testid="member-row"') == 2
    assert 'value="core"' in page


def test_selection_without_ids_just_returns(client: TestClient) -> None:
    response = post(client, "/selection/tag", tag="x", next="/?q=a")
    assert response.headers["location"] == "/?q=a"
    assert post(client, "/selection/list", list_name="x").headers["location"] == "/"


def test_selection_errors_are_422(client: TestClient, team: dict[str, Any]) -> None:
    ids = [team["dev"]["id"]]
    assert post(client, "/selection/tag", contact_ids=ids, tag="  ").status_code == 422
    assert post(client, "/selection/list", contact_ids=ids, list_name="").status_code == 422


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/lists/3", "/lists/3"),
        ("//evil.example", "/"),
        ("https://evil.example", "/"),
        ("/\\evil", "/"),
        (None, "/"),
    ],
)
def test_redirect_targets_stay_on_site(value: object, expected: str) -> None:
    assert safe_next(value) == expected


def test_with_notice_appends_query() -> None:
    assert with_notice("/?q=a", "tagged", n=2) == "/?q=a&notice=tagged&n=2"
    assert with_notice("/lists/1", "saved") == "/lists/1?notice=saved"


# ---------------------------------------------------------------- card: tags, lists, favorite


@pytest.mark.req("T-01", "T-02")
def test_card_add_and_remove_tag(client: TestClient, team: dict[str, Any]) -> None:
    dev_id = team["dev"]["id"]
    post(client, f"/contacts/{dev_id}/tags", tag="Pipeline")
    card = client.get(f"/contacts/{dev_id}").text
    tag = client.get("/api/contacts/" + str(dev_id)).json()["tags"][0]

    assert 'href="/?tag=Pipeline"' in card
    assert tag["name"] == "Pipeline"
    post(client, f"/contacts/{dev_id}/tags/{tag['id']}/remove")
    assert client.get(f"/api/contacts/{dev_id}").json()["tags"] == []
    assert post(client, f"/contacts/{dev_id}/tags/999999/remove").status_code == 404
    assert post(client, f"/contacts/{dev_id}/tags", tag="").status_code == 422


@pytest.mark.req("L-02")
def test_card_add_to_list_and_remove(client: TestClient, team: dict[str, Any]) -> None:
    rob_id = team["rob"]["id"]
    post(client, f"/contacts/{rob_id}/lists", list_name="Customer council", role_note="sponsor")
    body = client.get(f"/api/contacts/{rob_id}").json()
    card = client.get(f"/contacts/{rob_id}").text

    assert body["lists"][0]["name"] == "Customer council"
    assert "· sponsor" in card
    post(client, f"/contacts/{rob_id}/lists/{body['lists'][0]['id']}/remove")
    assert client.get(f"/api/contacts/{rob_id}").json()["lists"] == []
    assert post(client, f"/contacts/{rob_id}/lists/999999/remove").status_code == 404
    assert post(client, f"/contacts/{rob_id}/lists", list_name=" ").status_code == 422


@pytest.mark.req("C-10")
def test_favorite_toggle(client: TestClient, team: dict[str, Any]) -> None:
    rob_id = team["rob"]["id"]
    post(client, f"/contacts/{rob_id}/favorite")
    assert client.get(f"/api/contacts/{rob_id}").json()["is_favorite"] is True
    assert "Robert Lin" in client.get("/?favorites=1").text
    post(client, f"/contacts/{rob_id}/favorite")
    assert client.get(f"/api/contacts/{rob_id}").json()["is_favorite"] is False


# ---------------------------------------------------------------- list pages (L-01 to L-04)


@pytest.mark.req("L-01", "L-04")
def test_list_pages_end_to_end(client: TestClient, team: dict[str, Any]) -> None:
    created = post(client, "/lists", name="Vendor review", description="FY27 renewals")
    list_url = created.headers["location"].split("?")[0]
    list_id = int(list_url.rsplit("/", 1)[1])

    post(client, f"{list_url}/members", contact_id=str(team["dev"]["id"]), role_note="tech lead")
    post(client, f"{list_url}/members", contact_id=str(team["rob"]["id"]))
    post(client, f"{list_url}/members/{team['rob']['id']}/role", role_note="customer sponsor")
    page = client.get(list_url).text

    # L-04: members with type, company, role and contact methods
    assert page.count('data-testid="member-row"') == 2
    assert "Peachtree Labs" in page
    assert 'value="customer sponsor"' in page
    assert 'href="mailto:dev@acme.example"' in page
    assert "Employee" in page

    index = client.get("/lists").text
    assert "Vendor review" in index
    assert "FY27 renewals" in index

    post(client, f"{list_url}/edit", name="Vendor review FY27", description="")
    post(client, f"{list_url}/members/{team['rob']['id']}/remove")
    post(client, f"{list_url}/archive")
    assert "Vendor review FY27" not in client.get("/lists").text
    assert "Vendor review FY27" in client.get("/lists?archived=1").text
    post(client, f"{list_url}/restore")
    assert client.get(f"/?list={list_id}").text.count('data-testid="result-row"') == 1


def test_list_page_errors(client: TestClient, team: dict[str, Any]) -> None:
    post(client, "/lists", name="Dup")
    duplicate = post(client, "/lists", name="dup")
    assert duplicate.status_code == 422
    assert "already exists" in duplicate.text
    assert client.get("/lists/999999").status_code == 404
    list_url = post(client, "/lists", name="Other").headers["location"].split("?")[0]
    assert post(client, f"{list_url}/members", contact_id="").status_code == 422
    assert post(client, f"{list_url}/members", contact_id="999999").status_code == 422
    assert post(client, f"{list_url}/members/999999/role", role_note="x").status_code == 404
    assert post(client, f"{list_url}/edit", name="Dup").status_code == 422


@pytest.mark.req("T-02")
def test_tags_page_and_api(client: TestClient, team: dict[str, Any]) -> None:
    post(client, "/selection/tag", contact_ids=[team["dev"]["id"]], tag="HL7")
    page = client.get("/tags").text
    assert 'href="/?tag=HL7"' in page
    assert client.get("/api/tags?q=h").json() == [
        {"id": client.get("/api/tags").json()[0]["id"], "name": "HL7", "count": 1}
    ]


# ---------------------------------------------------------------- company picker (C-14)


@pytest.mark.req("C-14")
def test_new_employee_defaults_to_home_company(client: TestClient, team: dict[str, Any]) -> None:
    html = client.get("/contacts/new").text
    assert 'data-home-company="Acme Health"' in html  # inferred: most common employee company
    assert '<option value="Acme Health" selected>Acme Health (home)</option>' in html
    assert '<option value="Peachtree Labs">Peachtree Labs</option>' in html
    assert 'value="__new__"' in html


@pytest.mark.req("C-14")
def test_home_company_setting_wins(
    settings: Settings, db_session: Session, team: dict[str, Any]
) -> None:
    configured = settings.model_copy(update={"home_company": "peachtree labs"})
    app = create_app(configured, run_migrations=False)
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as other:
        html = other.get("/contacts/new").text
    # resolved to the existing spelling
    assert '<option value="Peachtree Labs" selected>Peachtree Labs (home)</option>' in html


@pytest.mark.req("C-14")
def test_add_new_company_and_reuse_existing_spelling(
    client: TestClient, types: dict[str, int], team: dict[str, Any]
) -> None:
    emp = str(types["Employee"])
    new = post(
        client,
        "/contacts",
        display_name="Nia",
        contact_type_id=emp,
        company="__new__",
        company_new="  Globex   Corp ",
    )
    same = post(
        client,
        "/contacts",
        display_name="Ola",
        contact_type_id=emp,
        company="__new__",
        company_new="acme health",
    )

    nia = client.get(
        new.headers["location"].split("?")[0].replace("/contacts/", "/api/contacts/")
    ).json()
    ola = client.get(
        same.headers["location"].split("?")[0].replace("/contacts/", "/api/contacts/")
    ).json()
    assert nia["company"] == "Globex Corp"
    assert ola["company"] == "Acme Health"
    assert "Globex Corp" in client.get("/contacts/new").text


@pytest.mark.req("C-14")
def test_company_dropdown_keeps_new_value_after_error(
    client: TestClient, types: dict[str, int]
) -> None:
    response = post(
        client,
        "/contacts",
        display_name="",
        contact_type_id=str(types["Employee"]),
        company="__new__",
        company_new="Initech",
    )
    assert response.status_code == 422
    assert 'value="Initech"' in response.text
    assert '<option value="__new__" selected>' in response.text


def test_api_resolves_company_spelling(
    client: TestClient, types: dict[str, int], team: dict[str, Any]
) -> None:
    body = make(
        client, display_name="Zed", contact_type_id=types["Vendor"], company="PEACHTREE labs"
    )
    assert body["company"] == "Peachtree Labs"
    patched = client.patch(f"/api/contacts/{body['id']}", json={"company": "acme HEALTH"}).json()
    assert patched["company"] == "Acme Health"
