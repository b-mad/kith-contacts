"""C-24: a larger view of a contact's photo with name, title and company."""

from __future__ import annotations

import io
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactType
from app.photos import set_photo


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "teal").save(buf, "PNG")
    return buf.getvalue()


def _person(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    body = {"display_name": name, "contact_type_id": types["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _with_photo(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    cid = _person(client, session, name, **fields)
    set_photo(session, cid, _png())
    return cid


@pytest.mark.req("C-24")
def test_photo_opens_a_larger_view_from_results_preview_and_card(
    client: TestClient, db_session: Session
) -> None:
    cid = _with_photo(client, db_session, "Pia Photo", title="Director", company="Acme")
    attrs = (
        f'data-photo-src="/contacts/{cid}/photo" data-name="Pia Photo" '
        'data-title="Director" data-company="Acme"'
    )
    for url in ("/contacts/results", f"/contacts/{cid}/preview", f"/contacts/{cid}"):
        html = client.get(url).text
        assert "data-photo-zoom" in html, url
        assert attrs in html, url
    page = client.get("/").text
    assert "data-photo-view" in page  # the shared dialog
    assert re.search(r"data-photo-view-name", page)


@pytest.mark.req("C-24")
def test_no_photo_means_nothing_to_enlarge(client: TestClient, db_session: Session) -> None:
    cid = _person(client, db_session, "Nia NoPhoto")
    assert "data-photo-zoom" not in client.get(f"/contacts/{cid}").text
    assert "data-photo-zoom" not in client.get("/contacts/results").text
