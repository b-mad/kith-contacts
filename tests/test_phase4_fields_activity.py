"""Phase 4: custom fields (C-11) and the activity log (C-13)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.activity import add_activity, delete_activity, parse_date
from app.config import Settings
from app.contacts import ContactError, ContactNotFound, create_contact, get_contact, last_contact
from app.migrate import ensure_contact_types
from app.models import ContactType
from app.schemas import ContactCreate, ContactUpdate
from app.search import search

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf(client: TestClient) -> str:
    match = TOKEN.search(client.get("/contacts/new").text)
    assert match
    return match.group(1)


def form_post(client: TestClient, url: str, pairs: list[tuple[str, str]]) -> Any:
    """POST a form that repeats field names (rows)."""
    from urllib.parse import urlencode

    body = urlencode([("csrf_token", csrf(client)), *pairs])
    return client.post(
        url,
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def _type_id(session: Session, name: str = "Employee") -> int:
    ct = session.query(ContactType).filter(ContactType.name == name).one()
    return ct.id


def _new(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    body = {"display_name": name, "contact_type_id": _type_id(session), **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ---------------------------------------------------------------- C-11 custom fields


@pytest.mark.req("C-11")
def test_custom_fields_via_api_replace_and_keep(client: TestClient, db_session: Session) -> None:
    cid = _new(
        client,
        db_session,
        "Priya Shah",
        custom_fields=[
            {"name": "Epic role", "value": "Beaker analyst"},
            {"name": "Birthday", "value": "March 3"},
        ],
    )
    body = client.get(f"/api/contacts/{cid}").json()
    assert [(f["name"], f["value"]) for f in body["custom_fields"]] == [
        ("Epic role", "Beaker analyst"),
        ("Birthday", "March 3"),
    ]
    # Case-only rename of a field reuses the row; a removed field disappears.
    res = client.patch(
        f"/api/contacts/{cid}",
        json={"custom_fields": [{"name": "birthday", "value": "March 4"}]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["custom_fields"] == [{"name": "birthday", "value": "March 4"}]
    # A PATCH without custom_fields leaves them alone.
    res = client.patch(f"/api/contacts/{cid}", json={"title": "Analyst"})
    assert res.json()["custom_fields"] == [{"name": "birthday", "value": "March 4"}]
    # List endpoints do not carry the detail fields.
    listed = client.get("/api/contacts").json()
    assert all(c["custom_fields"] is None for c in listed)


@pytest.mark.req("C-11")
def test_custom_field_names_must_be_unique_ignoring_case(db_session: Session) -> None:
    with pytest.raises(ValueError, match="listed twice"):
        ContactCreate.model_validate(
            {
                "display_name": "X",
                "contact_type_id": 1,
                "custom_fields": [{"name": "Role", "value": "a"}, {"name": "role", "value": "b"}],
            }
        )
    with pytest.raises(ValueError, match="listed twice"):
        ContactUpdate.model_validate(
            {"custom_fields": [{"name": "Role", "value": "a"}, {"name": "ROLE", "value": "b"}]}
        )


@pytest.mark.req("C-11", "S-01")
def test_custom_field_values_are_searchable(client: TestClient, db_session: Session) -> None:
    _new(
        client,
        db_session,
        "Omar Reyes",
        custom_fields=[{"name": "Assistant", "value": "Genevieve Park"}],
    )
    hits = search(db_session, "genevieve")
    assert [h.contact.display_name for h in hits] == ["Omar Reyes"]


@pytest.mark.req("C-11")
def test_custom_fields_in_the_form_and_card(client: TestClient, db_session: Session) -> None:
    res = form_post(
        client,
        "/contacts",
        [
            ("display_name", "Lena Ortiz"),
            ("contact_type_id", str(_type_id(db_session))),
            ("field_name", "Epic role"),
            ("field_value", "Beaker analyst"),
            ("field_name", ""),
            ("field_value", ""),
        ],
    )
    assert res.status_code == 303, res.text
    card_url = res.headers["location"].split("?")[0]
    card = client.get(card_url).text
    assert 'data-testid="custom-field-list"' in card
    assert "Beaker analyst" in card
    cid = int(card_url.rsplit("/", 1)[1])

    edit = client.get(f"/contacts/{cid}/edit").text
    assert 'value="Epic role"' in edit
    assert '<option value="Epic role">' in edit  # name suggestions

    # A value without a name is reported, and the rows are re-rendered.
    bad = form_post(
        client,
        f"/contacts/{cid}/edit",
        [
            ("display_name", "Lena Ortiz"),
            ("contact_type_id", str(_type_id(db_session))),
            ("field_name", ""),
            ("field_value", "orphan value"),
        ],
    )
    assert bad.status_code == 422
    assert "Field 1:" in bad.text
    assert 'value="orphan value"' in bad.text

    # Removing every row clears the fields.
    ok = form_post(
        client,
        f"/contacts/{cid}/edit",
        [("display_name", "Lena Ortiz"), ("contact_type_id", str(_type_id(db_session)))],
    )
    assert ok.status_code == 303
    assert get_contact(db_session, cid).custom_fields == []


# ---------------------------------------------------------------- C-13 activity log


@pytest.mark.req("C-13")
def test_activity_log_on_the_card(client: TestClient, db_session: Session) -> None:
    cid = _new(client, db_session, "Maya Chen")
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    res = form_post(
        client,
        f"/contacts/{cid}/activities",
        [("kind", "meeting"), ("occurred_on", week_ago), ("summary", "Met at HIMSS booth")],
    )
    assert res.status_code == 303
    assert res.headers["location"].endswith("#activity-h")
    form_post(
        client,
        f"/contacts/{cid}/activities",
        [("kind", "note"), ("occurred_on", ""), ("summary", "Prefers Teams")],
    )
    card = client.get(f"/contacts/{cid}").text
    assert card.count('data-testid="activity"') == 2
    assert card.index("Prefers Teams") < card.index("Met at HIMSS")  # newest first
    # Notes don't count as contact.
    week = date.fromisoformat(week_ago)
    assert f"last contact {week.strftime('%b')} {week.day}, {week.year}" in card

    api = client.get(f"/api/contacts/{cid}").json()
    assert api["last_contact"] == week_ago
    assert [a["kind"] for a in api["activities"]] == ["note", "meeting"]

    bad = form_post(
        client, f"/contacts/{cid}/activities", [("kind", "fax"), ("summary", "Old school")]
    )
    assert bad.status_code == 422

    activity_id = api["activities"][1]["id"]
    res = form_post(client, f"/contacts/{cid}/activities/{activity_id}/delete", [])
    assert res.status_code == 303
    assert client.get(f"/api/contacts/{cid}").json()["last_contact"] is None
    missing = form_post(client, f"/contacts/{cid}/activities/{activity_id}/delete", [])
    assert missing.status_code == 404


@pytest.mark.req("C-13", "S-01")
def test_activity_summaries_are_searchable(client: TestClient, db_session: Session) -> None:
    cid = _new(client, db_session, "Theo Novak")
    add_activity(db_session, cid, kind="meeting", summary="Met at HIMSS, asked about FHIR")
    assert [h.contact.display_name for h in search(db_session, "himss fhir")] == ["Theo Novak"]
    activity = get_contact(db_session, cid).activities[0]
    delete_activity(db_session, cid, activity.id)
    assert search(db_session, "himss") == []


@pytest.mark.req("C-13")
def test_activity_rules(db_session: Session, settings: Settings) -> None:
    ensure_contact_types(db_session, settings.contact_types)
    contact = create_contact(
        db_session,
        ContactCreate(display_name="Rules", contact_type_id=_type_id(db_session)),
    )
    with pytest.raises(ContactError, match="short note"):
        add_activity(db_session, contact.id, kind="call", summary="   ")
    with pytest.raises(ContactError, match="under"):
        add_activity(db_session, contact.id, kind="call", summary="x" * 2001)
    with pytest.raises(ContactNotFound):
        add_activity(db_session, 999_999, kind="call", summary="nobody")
    with pytest.raises(ContactNotFound):
        delete_activity(db_session, contact.id, 999_999)

    today = date(2026, 9, 24)
    assert parse_date("", today=today) == today
    assert parse_date("2026-01-02", today=today) == date(2026, 1, 2)
    with pytest.raises(ContactError, match="Enter a date"):
        parse_date("next tuesday", today=today)
    with pytest.raises(ContactError, match="out of range"):
        parse_date("2030-01-01", today=today)

    add_activity(db_session, contact.id, kind="call", summary="a", occurred_on=date(2026, 1, 1))
    add_activity(db_session, contact.id, kind="email", summary="b", occurred_on=date(2026, 3, 1))
    add_activity(db_session, contact.id, kind="note", summary="c", occurred_on=date(2026, 5, 1))
    assert last_contact(get_contact(db_session, contact.id)) == date(2026, 3, 1)
