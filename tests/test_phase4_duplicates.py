"""Phase 4: duplicate detection and merge (C-12, ADR-0012)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.contacts import ContactError, ContactNotFound, get_contact
from app.duplicates import dismiss_pair, find_duplicates, merge_contacts
from app.lists import add_members, create_list
from app.models import Contact, ContactMerge, ContactPhoto, ContactType
from app.search import search
from app.tags import add_tag

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def form_post(client: TestClient, url: str, pairs: list[tuple[str, str]]) -> Any:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    return client.post(
        url,
        content=urlencode([("csrf_token", token.group(1)), *pairs]),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def _types(session: Session) -> dict[str, int]:
    return {t.name: t.id for t in session.scalars(select(ContactType))}


def _new(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    body = {"display_name": name, "contact_type_id": _types(session)["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _pair_ids(session: Session) -> list[set[int]]:
    return [{p.a.id, p.b.id} for p in find_duplicates(session)]


@pytest.mark.req("C-12")
def test_finds_shared_email_and_similar_name_at_same_company(
    client: TestClient, db_session: Session
) -> None:
    a = _new(client, db_session, "Maria Lopez", company="Acme Health",
             emails=[{"email": "maria@acme.com"}])  # fmt: skip
    b = _new(client, db_session, "M. Lopez", emails=[{"email": "MARIA@acme.com"}])
    c = _new(client, db_session, "Maria Lopes", company="acme health")
    far = _new(client, db_session, "Maria Lopez", company="Other Co")
    archived = _new(client, db_session, "Maria Lopez", company="Acme Health")
    client.delete(f"/api/contacts/{archived}")

    pairs = find_duplicates(db_session)
    by_ids = {frozenset({p.a.id, p.b.id}): p for p in pairs}
    assert "same email maria@acme.com" in by_ids[frozenset({a, b})].reasons
    assert by_ids[frozenset({a, c})].reasons == ["similar name"]
    assert frozenset({a, far}) not in by_ids  # different companies
    assert not any(archived in k for k in by_ids)
    assert pairs[0].reasons[0].startswith("same email")  # strongest first

    dismiss_pair(db_session, c, a)
    assert {a, c} not in _pair_ids(db_session)
    dismiss_pair(db_session, a, c)  # idempotent
    with pytest.raises(ContactError):
        dismiss_pair(db_session, a, a)
    with pytest.raises(ContactNotFound):
        dismiss_pair(db_session, a, 999_999)


@pytest.mark.req("C-12")
def test_merge_moves_everything_and_keeps_a_snapshot(
    client: TestClient, db_session: Session
) -> None:
    types = _types(db_session)
    boss = _new(client, db_session, "Boss Person")
    keep = _new(client, db_session, "Dev Patel", title="Engineer", company="Acme Health",
                notes="Met at HIMSS", emails=[{"email": "dev@acme.com", "is_primary": True}],
                phones=[{"number": "+14045550100"}],
                custom_fields=[{"name": "Role", "value": "Lead"}])  # fmt: skip
    other = _new(client, db_session, "Devendra Patel", title="Staff Engineer",
                 team="Data Platform", manager_id=boss, notes="Prefers Teams",
                 contact_type_id=types["Vendor"],
                 emails=[{"email": "DEV@acme.com"}, {"email": "dev.p@home.com"}],
                 phones=[{"number": "(404) 555-0100"}, {"number": "+14045550199"}],
                 custom_fields=[{"name": "role", "value": "ignored"},
                                {"name": "Birthday", "value": "May 1"}])  # fmt: skip
    report = _new(client, db_session, "Report Person", manager_id=other)
    add_tag(db_session, [keep], "HL7")
    add_tag(db_session, [other], "HL7")
    add_tag(db_session, [other], "FHIR")
    lis = create_list(db_session, "Q4 LIS")
    add_members(db_session, lis, [keep])
    add_members(db_session, lis, [other], "tech lead")
    solo = create_list(db_session, "Solo list")
    add_members(db_session, solo, [other], "sponsor")
    add_activity(db_session, other, kind="call", summary="Kickoff call",
                 occurred_on=date(2026, 5, 1))  # fmt: skip
    db_session.add(ContactPhoto(contact_id=other, content_type="image/png", data=b"png"))
    db_session.flush()

    merged = merge_contacts(db_session, keep, other, {"title": "other"}, today=date(2026, 9, 24))

    assert db_session.get(Contact, other) is None
    assert merged.title == "Staff Engineer"  # chosen
    assert merged.team == "Data Platform"  # blank filled
    assert merged.manager_id == boss
    assert merged.contact_type.name == "Employee"  # conflict defaults to kept
    assert merged.notes == "Met at HIMSS\n\nPrefers Teams"
    assert sorted(e.email for e in merged.emails) == ["dev.p@home.com", "dev@acme.com"]
    assert [e.email for e in merged.emails if e.is_primary] == ["dev@acme.com"]
    assert sorted(p.number for p in merged.phones) == ["+14045550100", "+14045550199"]
    assert [(f.name, f.value) for f in merged.custom_fields] == [
        ("Role", "Lead"),
        ("Birthday", "May 1"),
    ]
    assert sorted(t.name for t in merged.tags) == ["FHIR", "HL7"]
    roles = {m.contact_list.name: m.role_note for m in merged.memberships}
    assert roles == {"Q4 LIS": "tech lead", "Solo list": "sponsor"}
    kinds = [(a.kind, a.summary) for a in merged.activities]
    assert ("call", "Kickoff call") in kinds
    assert ("note", "Merged with Devendra Patel (a duplicate record).") in kinds
    assert merged.photo is not None
    assert get_contact(db_session, report).manager_id == keep

    snap = db_session.scalars(select(ContactMerge)).one()
    assert snap.kept_id == keep
    assert snap.merged_name == "Devendra Patel"
    assert snap.snapshot["title"] == "Staff Engineer"
    assert snap.snapshot["custom_fields"][1] == {"name": "Birthday", "value": "May 1"}

    # Search documents follow: the report now finds its new manager's name.
    assert keep in {h.contact.id for h in search(db_session, "fhir")}
    assert report in {h.contact.id for h in search(db_session, "report dev patel")}


@pytest.mark.req("C-12")
def test_merge_rules(client: TestClient, db_session: Session) -> None:
    a = _new(client, db_session, "Ana Silva")
    b = _new(client, db_session, "Ana Silva", manager_id=a)
    with pytest.raises(ContactError):
        merge_contacts(db_session, a, a)
    with pytest.raises(ContactNotFound):
        merge_contacts(db_session, a, 999_999)
    # b reports to a: taking b's manager would make a its own manager.
    merged = merge_contacts(db_session, a, b, {"manager_id": "other"})
    assert merged.manager_id is None


@pytest.mark.req("C-12")
def test_duplicates_page_merge_and_dismiss(client: TestClient, db_session: Session) -> None:
    a = _new(client, db_session, "Chris Wong", title="PM", emails=[{"email": "cw@example.com"}])
    b = _new(client, db_session, "Christopher Wong", title="Product Manager",
             emails=[{"email": "cw@example.com"}])  # fmt: skip
    c = _new(client, db_session, "Sam Lee", emails=[{"email": "sam@example.com"}])
    d = _new(client, db_session, "Sam Lee", emails=[{"email": "sam@example.com"}])

    page = client.get("/duplicates").text
    assert page.count('data-testid="dup-pair"') == 2
    assert "Same email cw@example.com" in page
    assert 'data-testid="duplicates-link"' in client.get("/settings").text

    review = client.get(f"/duplicates/merge?a={a}&b={b}").text
    assert 'data-testid="conflict-title"' in review
    assert 'data-testid="conflict-display_name"' in review

    # Keep B's record but A's name and B's title.
    res = form_post(
        client,
        "/duplicates/merge",
        [("a", str(a)), ("b", str(b)), ("keep", "b"),
         ("choice_display_name", "a"), ("choice_title", "b")],
    )  # fmt: skip
    assert res.status_code == 303
    assert res.headers["location"].startswith(f"/contacts/{b}?notice=merged")
    card = client.get(res.headers["location"]).text
    assert "Merged “Chris Wong” into this contact." in card
    kept = get_contact(db_session, b)
    assert (kept.display_name, kept.title) == ("Chris Wong", "Product Manager")
    assert db_session.get(Contact, a) is None

    res = form_post(client, "/duplicates/dismiss", [("a", str(c)), ("b", str(d))])
    assert res.status_code == 303
    assert 'data-testid="no-duplicates"' in client.get("/duplicates").text

    assert form_post(client, "/duplicates/dismiss", [("a", "x"), ("b", "1")]).status_code == 422
    assert (
        form_post(client, "/duplicates/dismiss", [("a", str(c)), ("b", str(c))]).status_code == 422
    )
    assert (
        form_post(client, "/duplicates/dismiss", [("a", str(c)), ("b", "999999")]).status_code
        == 404
    )
    assert client.get(f"/duplicates/merge?a={c}&b={c}").status_code == 422
    assert client.get(f"/duplicates/merge?a={c}&b=999999").status_code == 404
    assert form_post(client, "/duplicates/merge", [("a", "")]).status_code == 422
