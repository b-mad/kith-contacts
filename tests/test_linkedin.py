"""LinkedIn profile link on every card (C-18, ADR-0018)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anonymize import anonymize
from app.contacts import get_contact
from app.exchange import (
    FORMAT,
    contact_record,
    export_csv,
    guess_mapping,
    plan_import,
    read_csv,
    rows_from_csv,
    rows_from_json,
    rows_from_vcards,
    run_import,
)
from app.links import linkedin_name, normalize_linkedin
from app.models import Contact, ContactType
from app.privacy import COOKIE, DEFAULT, save_privacy
from app.vcard import parse_vcards, to_vcard

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')
MARIA = "https://www.linkedin.com/in/maria-lopez"


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def make(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


# ---------------------------------------------------------------- validation


@pytest.mark.req("C-18")
@pytest.mark.parametrize(
    "raw",
    [
        "https://www.linkedin.com/in/maria-lopez",
        "https://www.linkedin.com/in/Maria-Lopez/",
        "http://linkedin.com/in/maria-lopez?trk=public_profile",
        "www.linkedin.com/in/maria-lopez/details/experience/",
        "linkedin.com/in/maria-lopez#about",
        "https://uk.linkedin.com/in/maria-lopez",
        "maria-lopez",
        "@maria-lopez",
        "  maria-lopez  ",
    ],
)
def test_profile_links_and_names_are_stored_one_way(raw: str) -> None:
    assert normalize_linkedin(raw) == MARIA


@pytest.mark.req("C-18")
@pytest.mark.parametrize(
    "raw",
    [
        "https://www.linkedin.com/company/northwind",
        "https://example.com/in/maria-lopez",
        "https://linkedin.com.evil.example/in/maria-lopez",
        "javascript:alert(1)//linkedin.com/in/x",
        "https://www.linkedin.com/in/",
        "ab",
        "maria lopez",
        "",
    ],
)
def test_anything_else_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="LinkedIn"):
        normalize_linkedin(raw)


@pytest.mark.req("C-18")
def test_display_name_from_a_profile_link() -> None:
    assert linkedin_name(MARIA) == "maria-lopez"
    assert linkedin_name(None) is None


# ---------------------------------------------------------------- form, card, preview, API


@pytest.mark.req("C-18")
def test_form_saves_a_profile_and_the_card_links_to_it(
    client: TestClient, types: dict[str, int]
) -> None:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    response = client.post(
        "/contacts",
        data={
            "csrf_token": token.group(1),
            "display_name": "Maria Lopez",
            "contact_type_id": types["Employee"],
            "linkedin_url": "linkedin.com/in/Maria-Lopez/?trk=abc",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    card = client.get(response.headers["location"]).text
    assert (
        f'<a class="action" href="{MARIA}" target="_blank" rel="noopener noreferrer" '
        'title="LinkedIn: maria-lopez" data-testid="action-linkedin">'
    ) in card
    edit = client.get(response.headers["location"].split("?")[0] + "/edit").text
    assert f'value="{MARIA}"' in edit


@pytest.mark.req("C-18")
def test_form_rejects_a_link_that_is_not_a_profile(
    client: TestClient, types: dict[str, int]
) -> None:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    response = client.post(
        "/contacts",
        data={
            "csrf_token": token.group(1),
            "display_name": "Maria Lopez",
            "contact_type_id": types["Employee"],
            "linkedin_url": "https://www.linkedin.com/company/northwind",
        },
    )
    assert response.status_code == 422
    assert "must be a LinkedIn profile link like linkedin.com/in/name" in response.text
    assert 'value="https://www.linkedin.com/company/northwind"' in response.text  # kept


@pytest.mark.req("C-18")
def test_api_normalises_and_validates(client: TestClient, types: dict[str, int]) -> None:
    created = make(
        client, display_name="Api Person", contact_type_id=types["Employee"], linkedin_url="api-p"
    )
    assert created["linkedin_url"] == "https://www.linkedin.com/in/api-p"
    bad = client.post(
        "/api/contacts",
        json={"display_name": "X", "contact_type_id": types["Employee"], "linkedin_url": "x y"},
    )
    assert bad.status_code == 422
    cleared = client.patch(f"/api/contacts/{created['id']}", json={"linkedin_url": ""})
    assert cleared.json()["linkedin_url"] is None


@pytest.mark.req("C-18", "M-04")
def test_without_a_profile_the_action_says_so(client: TestClient, types: dict[str, int]) -> None:
    person = make(client, display_name="No Profile", contact_type_id=types["Employee"])
    card = client.get(f"/contacts/{person['id']}").text
    assert 'title="No LinkedIn profile saved" data-testid="action-linkedin-none"' in card
    preview = client.get(f"/contacts/{person['id']}/preview").text
    assert 'data-testid="action-linkedin-none"' in preview


@pytest.mark.req("C-18", "P-02", "P-07")
def test_presenting_shows_the_profile_except_in_the_names_view(
    client: TestClient, db_session: Session, types: dict[str, int]
) -> None:
    person = make(
        client, display_name="Maria Lopez", contact_type_id=types["Employee"], linkedin_url=MARIA
    )
    client.cookies.set(COOKIE, "1")
    assert MARIA in client.get(f"/contacts/{person['id']}/preview").text
    client.app.state.privacy = save_privacy(  # type: ignore[attr-defined]
        db_session, DEFAULT.__class__(view="names")
    )
    assert MARIA not in client.get(f"/contacts/{person['id']}").text


# ---------------------------------------------------------------- import and export


LINKEDIN_EXPORT = """Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Maria,Lopez,https://www.linkedin.com/in/maria-lopez,maria@northwind.example,Northwind Health,Integration Lead,14 Mar 2024
Sam,Okafor,https://www.linkedin.com/in/sam-okafor-123,,Northwind Health,Interface Analyst,02 Jan 2025
"""


@pytest.mark.req("C-18", "D-01")
def test_linkedin_connections_export_imports_profiles(
    client: TestClient, db_session: Session
) -> None:
    headers, body = read_csv(LINKEDIN_EXPORT.encode())
    assert headers[:3] == ["First Name", "Last Name", "URL"]
    mapping = guess_mapping(headers)
    assert {headers[i]: t for i, t in mapping.items()} == {
        "First Name": "first_name",
        "Last Name": "last_name",
        "URL": "linkedin_url",
        "Email Address": "email",
        "Company": "company",
        "Position": "title",
    }
    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    planned = plan_import(db_session, rows_from_csv(body, mapping), type_id)
    assert all(row.ok for row in planned)
    result = run_import(db_session, planned)
    db_session.flush()
    people = {
        c.display_name: c
        for c in db_session.scalars(select(Contact).where(Contact.id.in_(result.created)))
    }
    assert people["Maria Lopez"].linkedin_url == MARIA
    assert people["Maria Lopez"].title == "Integration Lead"
    assert people["Sam Okafor"].linkedin_url == "https://www.linkedin.com/in/sam-okafor-123"


@pytest.mark.req("C-18", "D-01")
def test_a_url_that_is_not_a_profile_is_left_out_not_an_error(db_session: Session) -> None:
    headers, body = read_csv(b"Name,URL\nPat Web,https://pat.example.com\n")
    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    planned = plan_import(db_session, rows_from_csv(body, guess_mapping(headers)), type_id)
    assert planned[0].ok
    assert "linkedin_url" not in planned[0].data


@pytest.mark.req("C-18", "D-02")
def test_vcard_round_trip_and_apple_escaping(client: TestClient, db_session: Session) -> None:
    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    person = make(client, display_name="Maria Lopez", contact_type_id=type_id, linkedin_url=MARIA)
    card = to_vcard(get_contact(db_session, person["id"]))
    assert f"X-SOCIALPROFILE;TYPE=linkedin:{MARIA}" in card
    assert parse_vcards(card)[0].linkedin_url == MARIA
    apple = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ann Apple\r\n"
        "X-SOCIALPROFILE;type=linkedin:https\\://www.linkedin.com/in/ann-apple\r\nEND:VCARD\r\n"
    )
    records = rows_from_vcards(parse_vcards(apple))
    planned = plan_import(db_session, records, type_id)
    assert planned[0].data["linkedin_url"] == "https://www.linkedin.com/in/ann-apple"


@pytest.mark.req("C-18", "I-09", "D-03")
def test_json_and_csv_exports_carry_the_profile(client: TestClient, db_session: Session) -> None:
    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    person = make(client, display_name="Maria Lopez", contact_type_id=type_id, linkedin_url=MARIA)
    record = contact_record(get_contact(db_session, person["id"]))
    assert record["linkedin_url"] == MARIA
    doc = {"format": FORMAT, "contacts": [{**record, "display_name": "Maria Copy"}]}
    assert rows_from_json(json.dumps(doc))[0]["linkedin_url"] == MARIA
    csv_text = export_csv(db_session)
    assert csv_text.splitlines()[0].endswith(",linkedin")
    assert MARIA in csv_text


@pytest.mark.req("C-18", "I-07")
def test_anonymised_copies_drop_the_profile(client: TestClient, db_session: Session) -> None:
    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    person = make(client, display_name="Maria Lopez", contact_type_id=type_id, linkedin_url=MARIA)
    anonymize(db_session)
    db_session.expire_all()
    contact = db_session.get(Contact, person["id"])
    assert contact is not None
    assert contact.linkedin_url is None
