"""Phase 4: copy a contact between instances with a JSON file (I-09, ADR-0012)."""

from __future__ import annotations

import io
import json
import re
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.contacts import ContactError
from app.exchange import FORMAT, plan_import, rows_from_json, run_import
from app.lists import add_members, create_list
from app.main import create_app
from app.migrate import upgrade_to_head
from app.models import ContactType
from app.photos import set_photo
from app.tags import add_tag
from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
from tests.conftest import make_settings

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _token(client: TestClient) -> str:
    match = TOKEN.search(client.get("/contacts/new").text)
    assert match
    return match.group(1)


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def personal(admin_url: str, tmp_path: Path) -> Iterator[TestClient]:
    """A second, isolated instance with its own database and types (I-02)."""
    spec = InstanceSpec(name=f"tp-{uuid.uuid4().hex[:6]}", port=5195, app_env="test")
    info = bootstrap(spec, admin_url, None)
    settings = make_settings(
        info.database_url,
        instance_name="Personal",
        contact_types=["Friend", "Family"],
        backup_dir=str(tmp_path / "b"),
    )
    upgrade_to_head(settings)
    with TestClient(create_app(settings)) as client:
        yield client
    drop_database(spec, admin_url)


def _rich_contact(client: TestClient, session: Session) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    res = client.post(
        "/api/contacts",
        json={
            "display_name": "Nora Kim",
            "contact_type_id": types["Vendor"],
            "company": "LabCo",
            "pronunciation": "NOR-ah",
            "is_favorite": True,
            "teams_url": "https://teams.microsoft.com/l/chat/0/0?users=nora@labco.example",
            "emails": [{"email": "nora@labco.example", "is_primary": True}],
            "phones": [{"number": "+14045550123", "label": "mobile"}],
            "custom_fields": [{"name": "Account #", "value": "LC-778"}],
        },
    )
    assert res.status_code == 201, res.text
    cid = int(res.json()["id"])
    add_tag(session, [cid], "Reference lab")
    add_members(session, create_list(session, "Send-outs"), [cid], "account manager")
    add_activity(session, cid, kind="meeting", summary="Contract review",
                 occurred_on=date(2026, 8, 3))  # fmt: skip
    set_photo(session, cid, _png())
    return cid


@pytest.mark.req("I-09")
def test_copy_a_contact_to_another_instance(
    client: TestClient, db_session: Session, personal: TestClient
) -> None:
    cid = _rich_contact(client, db_session)
    res = client.get(f"/contacts/{cid}/export.json")
    assert res.status_code == 200
    assert res.headers["content-disposition"].endswith('filename="Nora-Kim.json"')
    doc = res.json()
    assert doc["format"] == FORMAT
    assert len(doc["contacts"]) == 1
    assert doc["contacts"][0]["photo"]["content_type"] == "image/jpeg"  # re-encoded on upload
    assert f'href="/contacts/{cid}/export.json"' in client.get(f"/contacts/{cid}").text

    # Preview in the other instance shows the extras; then import.
    token = _token(personal)
    preview = personal.post(
        "/import/preview",
        data={"csrf_token": token},
        files={"file": ("Nora-Kim.json", res.content, "application/json")},
    )
    assert preview.status_code == 200, preview.text
    assert "1 field · 1 activity · 1 list · photo" in preview.text
    ran = personal.post(
        "/import/run",
        content=urlencode({"csrf_token": token, "kind": "json", "raw": res.text}),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert ran.status_code == 303

    hits = personal.get("/api/search", params={"q": "nora"}).json()
    assert len(hits) == 1
    copied = personal.get(f"/api/contacts/{hits[0]['contact']['id']}").json()
    assert copied["contact_type"]["name"] == "Friend"  # "Vendor" doesn't exist here
    assert copied["pronunciation"] == "NOR-ah"
    assert copied["is_favorite"] is True
    assert copied["teams_url"].startswith("https://teams.microsoft.com/")
    assert copied["custom_fields"] == [{"name": "Account #", "value": "LC-778"}]
    assert [(a["kind"], a["summary"]) for a in copied["activities"]] == [
        ("meeting", "Contract review")
    ]
    assert [t["name"] for t in copied["tags"]] == ["Reference lab"]
    assert [lst["name"] for lst in copied["lists"]] == ["Send-outs"]
    assert copied["has_photo"] is True
    list_page = personal.get(f"/lists/{copied['lists'][0]['id']}").text
    assert 'value="account manager"' in list_page
    # Searchable by the imported activity (the search document was refreshed).
    assert personal.get("/api/search", params={"q": "contract review"}).json()

    # Importing the same file again flags it as a duplicate.
    again = personal.post(
        "/import/preview",
        data={"csrf_token": token},
        files={"file": ("Nora-Kim.json", res.content, "application/json")},
    )
    assert "email nora@labco.example already exists" in again.text


@pytest.mark.req("I-09")
def test_json_rows_are_validated(client: TestClient, db_session: Session) -> None:
    with pytest.raises(ContactError, match="not valid JSON"):
        rows_from_json("{nope")
    with pytest.raises(ContactError, match="not an export"):
        rows_from_json(json.dumps({"format": "other/1", "contacts": []}))
    with pytest.raises(ContactError, match="no contacts"):
        rows_from_json(json.dumps({"format": FORMAT, "contacts": []}))

    doc: dict[str, Any] = {
        "format": FORMAT,
        "contacts": [
            {
                "display_name": "Old Friend",
                "archived_at": "2026-01-01T00:00:00+00:00",
                "emails": [{"email": "old@friend.example"}, {"bad": 1}],
                "activities": [
                    {"kind": "call", "occurred_on": "2026-02-01", "summary": "Caught up"},
                    {"kind": "fax", "occurred_on": "2026-02-01", "summary": "skipped"},
                    {"kind": "call", "occurred_on": "someday", "summary": "skipped"},
                ],
                "photo": {"content_type": "image/png", "data_base64": "bm90IGFuIGltYWdl"},
                "lists": [{"name": "Book club", "role_note": None}, {"name": ""}],
            },
            "not a contact",
        ],
    }
    records = rows_from_json(json.dumps(doc))
    types = {t.name: t.id for t in db_session.scalars(select(ContactType))}
    planned = plan_import(db_session, records, types["Employee"])
    assert planned[0].ok
    assert planned[0].extras_summary == "3 activities · 1 list · photo · archived"
    assert not planned[1].ok  # no name
    result = run_import(db_session, planned)
    assert len(result.created) == 1
    assert result.skipped_errors == 1
    got = client.get(f"/api/contacts/{result.created[0]}").json()
    assert got["archived"] is True
    assert [a["summary"] for a in got["activities"]] == ["Caught up"]
    assert got["has_photo"] is False  # bad image skipped, import still succeeded
    assert [lst["name"] for lst in got["lists"]] == ["Book club"]


@pytest.mark.req("I-09", "C-15", "C-16", "P-03")
def test_json_carries_keep_in_touch_and_private_flags(
    client: TestClient, db_session: Session
) -> None:
    from datetime import timedelta

    from app.contacts import get_contact
    from app.exchange import export_contact_json
    from app.keep_in_touch import set_cadence, snooze
    from app.models import Contact, ContactList, CustomField, Tag

    type_id = db_session.scalars(select(ContactType.id)).first()
    created = client.post(
        "/api/contacts",
        json={
            "display_name": "Petra Private",
            "contact_type_id": type_id,
            "custom_fields": [{"name": "Birthday", "value": "May 1"}],
        },
    ).json()
    contact = db_session.get(Contact, created["id"])
    assert contact is not None
    started = date.today() - timedelta(days=20)
    set_cadence(db_session, [contact], "3m", today=started)
    snooze(db_session, contact, date.today() + timedelta(days=9))
    contact.is_private = True
    tag = add_tag(db_session, [contact.id], "hush")
    tag.is_private = True
    secret = create_list(db_session, "Quiet list")
    secret.is_private = True
    add_members(db_session, secret, [contact.id])
    for f in contact.custom_fields:
        f.is_private = True
    db_session.flush()

    record = export_contact_json(get_contact(db_session, contact.id), "Business")
    exported = record["contacts"][0]
    assert exported["keep_in_touch"] == "3m"
    assert exported["keep_in_touch_started_on"] == started.isoformat()
    assert exported["is_private"] is True
    assert exported["private_tags"] == ["hush"]
    assert exported["lists"][0]["private"] is True
    assert exported["custom_fields"][0]["private"] is True

    # The target instance has the tag and list, but public: private in the source wins.
    tag.is_private = False
    secret.is_private = False
    exported["display_name"] = "Petra Copy"
    db_session.flush()
    planned = plan_import(db_session, rows_from_json(json.dumps(record)), int(type_id or 0))
    assert "keep in touch" in planned[0].extras_summary
    assert "private" in planned[0].extras_summary
    result = run_import(db_session, planned, include_duplicates=True)
    db_session.flush()
    db_session.expire_all()
    copy = db_session.get(Contact, result.created[0])
    assert copy is not None
    assert (copy.kit_interval, copy.kit_started_on) == ("3m", started)
    assert copy.kit_snoozed_until == date.today() + timedelta(days=9)
    assert copy.is_private
    assert db_session.scalars(select(Tag.is_private).where(Tag.name == "hush")).one()
    assert db_session.scalars(
        select(ContactList.is_private).where(ContactList.name == "Quiet list")
    ).one()
    assert db_session.scalars(
        select(CustomField.is_private).where(CustomField.contact_id == copy.id)
    ).one()


@pytest.mark.req("I-09", "C-15")
def test_json_ignores_a_bad_cadence(client: TestClient, db_session: Session) -> None:
    from app.models import Contact

    type_id = int(db_session.scalars(select(ContactType.id)).first() or 0)
    doc = {
        "format": FORMAT,
        "contacts": [
            {"display_name": "Odd Cadence", "keep_in_touch": "weekly", "is_private": "yes"},
        ],
    }
    result = run_import(
        db_session, plan_import(db_session, rows_from_json(json.dumps(doc)), type_id)
    )
    db_session.flush()
    copy = db_session.get(Contact, result.created[0])
    assert copy is not None
    assert copy.kit_interval is None
    assert copy.is_private is False
