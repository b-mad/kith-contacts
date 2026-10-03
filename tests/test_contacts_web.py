"""Contact pages: list, card, form, archive (C-01 to C-08, M-04, N-05)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from app.web import parse_contact_form

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def csrf(client: TestClient) -> str:
    match = TOKEN.search(client.get("/contacts/new").text)
    assert match, "form has no CSRF token"
    return match.group(1)


def form(client: TestClient, **fields: Any) -> dict[str, Any]:
    return {"csrf_token": csrf(client), **fields}


def api_create(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


# ---------------------------------------------------------------- create via form


@pytest.mark.req("C-01", "C-02", "C-03", "C-06", "C-08")
def test_add_contact_through_form(client: TestClient, types: dict[str, int]) -> None:
    response = client.post(
        "/contacts",
        data=form(
            client,
            display_name="Dev Patel",
            contact_type_id=types["Employee"],
            company="Acme Health",
            team="Data Platform",
            title="Data Engineer",
            works_on="Lab results pipeline",
            notes="Sat next to Raj; asked about API rate limits",
            email_address=["dev@acme.example", "", "dev@home.example"],
            email_label=["work", "", "personal"],
            primary_email="2",
            phone_number=["404 555 0123", ""],
            phone_label=["mobile", ""],
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    card = client.get(response.headers["location"])
    html = card.text
    assert card.status_code == 200
    assert "Saved." in html
    assert "Dev Patel" in html
    assert "Data Platform" in html
    assert "Acme Health" in html
    assert "Lab results pipeline" in html
    assert "Sat next to Raj" in html
    assert "(404) 555-0123" in html
    # the third row was marked primary; blank rows are ignored
    assert 'href="mailto:dev@home.example" data-testid="action-email"' in html


@pytest.mark.req("C-01")
def test_form_shows_errors_and_keeps_input(client: TestClient, types: dict[str, int]) -> None:
    response = client.post(
        "/contacts",
        data=form(
            client,
            display_name="",
            contact_type_id=types["Vendor"],
            company="Keep Me Inc",
            email_address=["not-an-email"],
            email_label=["work"],
        ),
    )

    assert response.status_code == 422
    assert 'data-testid="error-summary"' in response.text
    assert 'value="Keep Me Inc"' in response.text
    assert "Email 1:" in response.text


@pytest.mark.req("C-07")
def test_typed_but_unpicked_manager_is_an_error(client: TestClient, types: dict[str, int]) -> None:
    response = client.post(
        "/contacts",
        data=form(
            client,
            display_name="New Hire",
            contact_type_id=types["Employee"],
            manager_label="Somebody",
            manager_id="",
        ),
    )
    assert response.status_code == 422
    assert "Pick the manager from the suggestions" in response.text


@pytest.mark.req("C-07")
def test_form_rejects_manager_cycle(client: TestClient, types: dict[str, int]) -> None:
    boss = api_create(client, display_name="Boss", contact_type_id=types["Employee"])
    report = api_create(
        client, display_name="Report", contact_type_id=types["Employee"], manager_id=boss["id"]
    )

    response = client.post(
        f"/contacts/{boss['id']}/edit",
        data=form(
            client,
            display_name="Boss",
            contact_type_id=types["Employee"],
            manager_id=str(report["id"]),
            manager_label="Report",
        ),
    )
    assert response.status_code == 422
    assert "reporting cycle" in response.text


# ---------------------------------------------------------------- CSRF (N-05)


def test_form_post_without_csrf_token_is_forbidden(
    client: TestClient, types: dict[str, int]
) -> None:
    client.get("/")  # receive the cookie
    response = client.post(
        "/contacts", data={"display_name": "X", "contact_type_id": types["Vendor"]}
    )
    assert response.status_code == 403


def test_form_post_with_wrong_csrf_token_is_forbidden(
    client: TestClient, types: dict[str, int]
) -> None:
    client.get("/")
    response = client.post(
        "/contacts",
        data={"csrf_token": "forged", "display_name": "X", "contact_type_id": types["Vendor"]},
    )
    assert response.status_code == 403


def test_csrf_cookie_is_strict_and_http_only(client: TestClient) -> None:
    client.cookies.clear()
    cookie = client.get("/").headers["set-cookie"].lower()
    assert "contacts_csrf=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


# ---------------------------------------------------------------- card (M-04, C-07)


@pytest.mark.req("M-04", "C-04")
def test_card_shows_one_click_actions(client: TestClient, types: dict[str, int]) -> None:
    contact = api_create(
        client,
        display_name="Maria Lopez",
        contact_type_id=types["Employee"],
        emails=[{"email": "maria@acme.example"}],
        phones=[{"number": "+14045550100"}],
        slack_handle="maria",
    )

    html = client.get(f"/contacts/{contact['id']}").text

    assert 'href="mailto:maria@acme.example" data-testid="action-email"' in html
    assert 'href="tel:+14045550100" data-testid="action-call"' in html
    assert (
        'href="https://teams.microsoft.com/l/chat/0/0?users=maria@acme.example"' in html
    )  # generated from the primary email
    assert 'data-testid="action-slack">Slack @maria' in html  # handle shown when no DM link


@pytest.mark.req("C-07")
def test_card_links_manager_and_direct_reports(client: TestClient, types: dict[str, int]) -> None:
    maria = api_create(client, display_name="Maria Lopez", contact_type_id=types["Employee"])
    api_create(
        client,
        display_name="Dev Patel",
        contact_type_id=types["Employee"],
        manager_id=maria["id"],
        title="Data Engineer",
    )

    html = client.get(f"/contacts/{maria['id']}").text

    assert 'data-testid="reports"' in html
    assert 'Dev Patel</a> <span class="muted">· Data Engineer' in html
    assert f'href="/contacts/new?manager={maria["id"]}"' in html


def test_new_form_prefills_manager_from_query(client: TestClient, types: dict[str, int]) -> None:
    maria = api_create(client, display_name="Maria Lopez", contact_type_id=types["Employee"])
    html = client.get(f"/contacts/new?manager={maria['id']}").text
    assert 'value="Maria Lopez"' in html
    assert f'name="manager_id" value="{maria["id"]}"' in html


def test_unknown_contact_page_is_404(client: TestClient) -> None:
    assert client.get("/contacts/999999").status_code == 404
    assert client.get("/contacts/999999/edit").status_code == 404


# ---------------------------------------------------------------- edit, archive


@pytest.mark.req("C-01")
def test_edit_form_round_trip(client: TestClient, types: dict[str, int]) -> None:
    contact = api_create(
        client,
        display_name="Sam",
        contact_type_id=types["Customer"],
        company="Peachtree Labs",
        emails=[{"email": "sam@peachtree.example", "label": "work"}],
    )
    edit_html = client.get(f"/contacts/{contact['id']}/edit").text
    assert 'value="sam@peachtree.example"' in edit_html
    assert 'value="Peachtree Labs"' in edit_html

    response = client.post(
        f"/contacts/{contact['id']}/edit",
        data=form(
            client,
            display_name="Sam Rivera",
            contact_type_id=types["Customer"],
            company="Peachtree Labs",
            email_address=["sam@peachtree.example"],
            email_label=["work"],
            primary_email="0",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    body = client.get(f"/api/contacts/{contact['id']}").json()
    assert body["display_name"] == "Sam Rivera"
    assert body["emails"][0]["email"] == "sam@peachtree.example"


@pytest.mark.req("C-01")
def test_archive_and_restore_from_card(client: TestClient, types: dict[str, int]) -> None:
    contact = api_create(client, display_name="Old Vendor", contact_type_id=types["Vendor"])

    client.post(f"/contacts/{contact['id']}/archive", data=form(client))
    card = client.get(f"/contacts/{contact['id']}").text
    listing = client.get("/").text
    listing_all = client.get("/?archived=1").text
    client.post(f"/contacts/{contact['id']}/restore", data=form(client))

    assert 'data-testid="archived-badge"' in card
    assert "Old Vendor" not in listing
    assert "Old Vendor" in listing_all
    assert client.get("/api/contacts/" + str(contact["id"])).json()["archived"] is False


# ---------------------------------------------------------------- list


@pytest.mark.req("C-05")
def test_list_filters_by_type(client: TestClient, types: dict[str, int]) -> None:
    api_create(client, display_name="Vera Vendor", contact_type_id=types["Vendor"])
    api_create(client, display_name="Carl Customer", contact_type_id=types["Customer"])

    html = client.get(f"/?type={types['Vendor']}&sort=company").text

    assert "Vera Vendor" in html
    assert "Carl Customer" not in html
    assert '<option value="company" selected>Company</option>' in html  # the Sort control


def test_list_ignores_bad_query_values(client: TestClient) -> None:
    assert client.get("/?type=abc&sort=salary").status_code == 200


# ---------------------------------------------------------------- form parsing (unit)


def test_parse_contact_form_maps_rows_and_primary() -> None:
    data, values = parse_contact_form(
        FormData(
            [
                ("display_name", " Pat "),
                ("contact_type_id", "3"),
                ("manager_id", "12"),
                ("email_address", "a@x.example"),
                ("email_label", "work"),
                ("email_address", ""),
                ("email_label", ""),
                ("primary_email", "0"),
                ("phone_number", "404-555-0100"),
                ("phone_label", ""),
                ("is_favorite", "on"),
            ]
        )
    )
    assert data["display_name"] == "Pat"
    assert data["manager_id"] == 12
    assert data["is_favorite"] is True
    assert data["emails"] == [{"email": "a@x.example", "label": "work", "is_primary": True}]
    assert data["phones"] == [{"number": "404-555-0100", "label": ""}]
    assert len(values["emails"]) == 2  # blank row kept for re-rendering
