"""N-09, C-01: the Edit button on the full contact card has a keyboard shortcut (E)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactType
from tests.test_presenting import present


def _person(client: TestClient, session: Session, name: str) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    res = client.post(
        "/api/contacts", json={"display_name": name, "contact_type_id": types["Employee"]}
    )
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


@pytest.mark.req("N-09", "C-01")
def test_card_edit_button_is_the_target_of_the_e_shortcut(
    client: TestClient, db_session: Session
) -> None:
    cid = _person(client, db_session, "Edie Hotkey")
    html = client.get(f"/contacts/{cid}").text
    assert f'href="/contacts/{cid}/edit"' in html
    assert "data-edit-hotkey" in html
    assert 'aria-keyshortcuts="E"' in html


@pytest.mark.req("N-09", "P-05")
def test_no_edit_shortcut_target_while_presenting(client: TestClient, db_session: Session) -> None:
    cid = _person(client, db_session, "Edie Hidden")
    present(client)
    html = client.get(f"/contacts/{cid}").text
    assert "data-edit-hotkey" not in html
    assert f"/contacts/{cid}/edit" not in html


@pytest.mark.req("N-09")
def test_shortcut_list_names_the_edit_key(client: TestClient) -> None:
    html = client.get("/").text
    assert "<dt><kbd>e</kbd></dt><dd>Edit the person (on their full card)</dd>" in html
