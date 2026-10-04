"""Private contact types (P-08, ADR-0022)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import create_contact, get_contact, to_out
from app.models import Contact, ContactType
from app.privacy import COOKIE, DEFAULT, PRESENTING, Presenting
from app.schemas import ContactCreate
from app.search import search

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _types(session: Session) -> tuple[int, int]:
    work = ContactType(name="Colleague", sort_order=1)
    family = ContactType(name="Family", sort_order=2, is_private=True)
    session.add_all([work, family])
    session.flush()
    return work.id, family.id


def _contact(session: Session, name: str, type_id: int, **fields: Any) -> Contact:
    return create_contact(
        session,
        ContactCreate.model_validate({"display_name": name, "contact_type_id": type_id, **fields}),
    )


@pytest.mark.req("P-08", "P-02")
def test_presenting_withholds_every_contact_of_a_private_type(db_session: Session) -> None:
    work, family = _types(db_session)
    cousin = _contact(db_session, "Cousin Ola", family, team="Data")
    boss = _contact(db_session, "Boss Bea", work, team="Data", manager_id=None)
    report = _contact(db_session, "Report Ray", work, team="Data", manager_id=cousin.id)
    db_session.flush()
    db_session.expire_all()
    token = PRESENTING.set(Presenting(DEFAULT))
    try:
        names = {h.contact.display_name for h in search(db_session, "data")}
        types = set(db_session.scalars(select(ContactType.name)))
        hidden = db_session.scalars(select(Contact).where(Contact.id == cousin.id)).first()
        out = to_out(get_contact(db_session, report.id))
    finally:
        PRESENTING.reset(token)
    assert hidden is None
    assert names == {"Boss Bea", "Report Ray"}
    assert "Family" not in types
    assert "Colleague" in types
    assert out.manager is None  # a private-type manager is left out
    db_session.expire_all()
    assert {h.contact.display_name for h in search(db_session, "data")} == {
        "Boss Bea", "Report Ray", "Cousin Ola",
    }  # fmt: skip
    assert boss.id


@pytest.mark.req("P-08", "P-03")
def test_a_type_is_marked_private_from_settings(client: TestClient, db_session: Session) -> None:
    work, _ = _types(db_session)
    _contact(db_session, "Club Member", work)
    page = client.get("/settings/types").text
    token = TOKEN.search(page)
    assert token
    assert f'data-testid="private-type-{work}"' in page
    response = client.post(
        "/settings/privacy/item",
        data={
            "csrf_token": token.group(1),
            "kind": "type",
            "key": str(work),
            "private": "1",
            "next": "/settings/types",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings/types"
    db_session.expire_all()
    assert db_session.get(ContactType, work).is_private  # type: ignore[union-attr]
    assert "Colleague (private)" in client.get("/import").text
    privacy = client.get("/settings/privacy").text
    assert 'data-testid="private-type-' in privacy

    client.cookies.set(COOKIE, "1")
    assert "Club Member" not in client.get("/?q=club").text
