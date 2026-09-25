"""Phase 4: saved searches (S-07), related tags (T-05) and list tags (L-05)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound
from app.lists import add_list_tag, all_lists, create_list, remove_list_tag
from app.models import ContactType, Tag
from app.saved_searches import (
    clean_query,
    delete_saved_search,
    describe_query,
    get_saved_search,
    list_saved_searches,
    rename_saved_search,
    save_search,
)
from app.tags import add_tag, delete_tag, related_tags, rename_tag

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


def _new(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    body = {"display_name": name, "contact_type_id": types["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ---------------------------------------------------------------- S-07 saved searches


@pytest.mark.req("S-07")
def test_clean_query_keeps_known_params_only() -> None:
    assert clean_query({"q": "  lab   res ", "tag": "HL7", "sort": "name", "x": "1"}) == (
        "q=lab+res&tag=HL7"
    )
    assert clean_query("type=3&favorites=1&notice=saved") == "type=3&favorites=1"
    assert clean_query({"q": ""}) == ""
    assert describe_query("q=lab+res&type=3&tag=HL7&favorites=1") == (
        "text “lab res” · type #3 · tag HL7 · favorites"
    )


@pytest.mark.req("S-07")
def test_save_rename_delete(db_session: Session) -> None:
    saved = save_search(db_session, "Vendors tagged HL7", "type=2&tag=HL7&sort=name")
    assert saved.query == "type=2&tag=HL7"
    again = save_search(db_session, "vendors TAGGED hl7", "tag=FHIR")  # same name: update
    assert again.id == saved.id
    assert again.query == "tag=FHIR"
    other = save_search(db_session, "Favorites", "favorites=1")
    assert [s.name for s in list_saved_searches(db_session)] == ["Favorites", "vendors TAGGED hl7"]
    with pytest.raises(ContactError, match="already exists"):
        rename_saved_search(db_session, other, "VENDORS tagged HL7")
    rename_saved_search(db_session, other, "My favorites")
    with pytest.raises(ContactError, match="Type a search"):
        save_search(db_session, "Empty", "sort=name")
    with pytest.raises(ContactError, match="name"):
        save_search(db_session, "  ", "q=x")
    with pytest.raises(ContactError, match="longer"):
        save_search(db_session, "x" * 101, "q=x")
    with pytest.raises(ContactError, match="too long"):
        save_search(db_session, "Long", "q=" + "a" * 200 + "&company=" + "b" * 200
                    + "&team=" + "c" * 200 + "&tag=" + "d" * 200 + "&list=" + "e" * 200)  # fmt: skip
    delete_saved_search(db_session, other)
    with pytest.raises(ContactNotFound):
        get_saved_search(db_session, other.id)


@pytest.mark.req("S-07")
def test_saved_searches_in_the_ui(client: TestClient, db_session: Session) -> None:
    _new(client, db_session, "Ada Byron", team="Data Platform")
    page = client.get("/?q=data").text
    assert 'data-testid="save-search"' in page
    assert 'name="query" value="q=data"' in page
    assert 'data-testid="saved-searches"' not in page  # none saved yet
    # The results fragment fetched while typing carries the form too.
    assert 'data-testid="save-search"' in client.get("/contacts/results?q=data").text

    res = form_post(client, "/saved-searches", [("name", "Data people"), ("query", "q=data")])
    assert res.status_code == 303
    assert res.headers["location"].startswith("/?q=data&notice=search_saved")
    page = client.get("/?q=data").text
    assert 'data-testid="saved-search"' in page
    assert "Data people" in page
    assert 'aria-current="true" data-testid="saved-search"' in page

    manage = client.get("/saved-searches").text
    assert "text “data”" in manage
    saved_id = list_saved_searches(db_session)[0].id
    assert form_post(client, f"/saved-searches/{saved_id}/rename",
                     [("name", "Data team")]).status_code == 303  # fmt: skip
    assert "Data team" in client.get("/saved-searches").text
    assert form_post(client, f"/saved-searches/{saved_id}/rename",
                     [("name", "")]).status_code == 422  # fmt: skip
    assert form_post(client, f"/saved-searches/{saved_id}/delete", []).status_code == 303
    assert 'data-testid="no-saved"' in client.get("/saved-searches").text
    assert form_post(client, "/saved-searches/999999/delete", []).status_code == 404
    assert form_post(client, "/saved-searches", [("name", "x"), ("query", "")]).status_code == 422
    assert 'data-testid="save-search"' not in client.get("/").text  # nothing to save


# ---------------------------------------------------------------- T-05 related tags


@pytest.mark.req("T-05")
def test_related_tags_rank_by_shared_active_contacts(
    client: TestClient, db_session: Session
) -> None:
    a = _new(client, db_session, "A")
    b = _new(client, db_session, "B")
    c = _new(client, db_session, "C")
    gone = _new(client, db_session, "Gone")
    add_tag(db_session, [a, b, c, gone], "HL7")
    add_tag(db_session, [a, b], "Interfaces")
    add_tag(db_session, [c], "FHIR")
    add_tag(db_session, [gone], "Legacy")
    client.delete(f"/api/contacts/{gone}")

    assert [(t.name, t.shared) for t in related_tags(db_session, "hl7")] == [
        ("Interfaces", 2),
        ("FHIR", 1),
    ]
    assert related_tags(db_session, "nothing") == []

    page = client.get("/?tag=HL7").text
    assert 'data-testid="related-tags"' in page
    assert page.index(">Interfaces<") < page.index(">FHIR<")
    assert 'data-testid="related-tags"' not in client.get("/?tag=Legacy").text


# ---------------------------------------------------------------- L-05 list tags


@pytest.mark.req("L-05")
def test_list_tags_filter_and_follow_tag_admin(client: TestClient, db_session: Session) -> None:
    lis = create_list(db_session, "Q4 LIS")
    epic = create_list(db_session, "Epic upgrade")
    add_list_tag(db_session, lis, "Interfaces")
    tag = add_list_tag(db_session, lis, "interfaces")  # same tag, added once
    assert [t.name for t in lis.tags] == ["Interfaces"]
    add_list_tag(db_session, epic, "Go-live")
    assert [cl.name for cl, _ in all_lists(db_session, tag="INTERFACES")] == ["Q4 LIS"]

    # Renaming onto an existing tag merges list tags too.
    rename_tag(db_session, db_session.get(Tag, tag.id) or tag, "Go-live")
    assert {cl.name for cl, _ in all_lists(db_session, tag="go-live")} == {"Q4 LIS", "Epic upgrade"}

    golive = db_session.scalars(select(Tag).where(Tag.name == "Go-live")).one()
    remove_list_tag(db_session, epic, golive.id)
    assert [t.name for t in epic.tags] == []
    delete_tag(db_session, golive)
    assert all_lists(db_session, tag="go-live") == []
    with pytest.raises(ContactError):
        add_list_tag(db_session, epic, "   ")


@pytest.mark.req("L-05")
def test_list_tags_in_the_ui(client: TestClient, db_session: Session) -> None:
    lis = create_list(db_session, "Q4 LIS")
    create_list(db_session, "Other")
    res = form_post(client, f"/lists/{lis.id}/tags", [("tag", "Interfaces")])
    assert res.status_code == 303
    detail = client.get(res.headers["location"]).text
    assert "Tagged the list “Interfaces”." in detail
    assert 'data-testid="list-tags"' in detail
    assert ">Interfaces</a>" in detail

    index = client.get("/lists?tag=interfaces").text
    assert 'data-testid="list-tag-filter"' in index
    assert "Q4 LIS" in index
    assert ">Other<" not in index
    tags_page = client.get("/tags").text
    assert 'data-testid="tag-lists-link"' in tags_page
    assert "1 list" in tags_page

    tag_id = db_session.scalars(select(Tag.id).where(Tag.name == "Interfaces")).one()
    assert form_post(client, f"/lists/{lis.id}/tags/{tag_id}/remove", []).status_code == 303
    assert ">Interfaces</a>" not in client.get(f"/lists/{lis.id}").text
    assert form_post(client, f"/lists/{lis.id}/tags", [("tag", " ")]).status_code == 422
