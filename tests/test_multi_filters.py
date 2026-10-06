"""S-15: several Company, Team, Tag or List values on the contacts screen."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lists import add_members, create_list
from app.models import ContactType
from app.saved_searches import clean_query, describe_query
from app.search import SearchFilters, match_mode, multi_ids, multi_texts, search
from app.tags import add_tag, related_tags


def _person(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    body = {"display_name": name, "contact_type_id": types["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _found(session: Session, **kw: Any) -> set[str]:
    return {h.contact.display_name for h in search(session, "", SearchFilters(**kw))}


@pytest.fixture
def world(client: TestClient, db_session: Session) -> dict[str, int]:
    ids = {
        "ann": _person(client, db_session, "Ann Acme", company="Acme", team="Blue"),
        "bo": _person(client, db_session, "Bo Beta", company="Beta Corp", team="Red"),
        "cy": _person(client, db_session, "Cy Core", company="Core Inc", team="Blue"),
        "di": _person(client, db_session, "Di Dune", company="Acme", team="Red"),
    }
    add_tag(db_session, [ids["ann"], ids["bo"]], "alpha")
    add_tag(db_session, [ids["bo"], ids["cy"]], "gamma")
    add_tag(db_session, [ids["ann"]], "gamma")
    one = create_list(db_session, "One")
    two = create_list(db_session, "Two")
    add_members(db_session, one, [ids["ann"], ids["cy"]])
    add_members(db_session, two, [ids["cy"], ids["di"]])
    ids["list1"], ids["list2"] = one.id, two.id
    return ids


# ---------------------------------------------------------------- parsing helpers


@pytest.mark.req("S-15")
def test_value_helpers_clean_repeated_parameters() -> None:
    assert multi_texts(["  Acme ", "acme", "", "Beta   Corp"]) == ("Acme", "Beta Corp")
    assert len(multi_texts([str(i) for i in range(100)])) == 25
    assert multi_ids(["3", "x", "3", " 4 ", "-1", ""]) == (3, 4)
    assert match_mode("all") == "all"
    assert match_mode("anything") == "any"
    assert match_mode(None) == "any"


# ---------------------------------------------------------------- search semantics


@pytest.mark.req("S-04", "S-15")
def test_company_and_team_match_any_value(world: dict[str, int], db_session: Session) -> None:
    assert _found(db_session, companies=("acme", "BETA corp")) == {"Ann Acme", "Bo Beta", "Di Dune"}
    assert _found(db_session, teams=("Blue", "Red")) == {
        "Ann Acme",
        "Bo Beta",
        "Cy Core",
        "Di Dune",
    }


@pytest.mark.req("S-15")
def test_different_filters_combine_with_and(world: dict[str, int], db_session: Session) -> None:
    assert _found(db_session, companies=("Acme", "Core Inc"), teams=("Blue",)) == {
        "Ann Acme",
        "Cy Core",
    }


@pytest.mark.req("S-15")
def test_tags_any_versus_all(world: dict[str, int], db_session: Session) -> None:
    assert _found(db_session, tags=("alpha", "GAMMA")) == {"Ann Acme", "Bo Beta", "Cy Core"}
    assert _found(db_session, tags=("alpha", "gamma"), tag_match="all") == {"Ann Acme", "Bo Beta"}
    assert _found(db_session, tags=("alpha", "nosuch"), tag_match="all") == set()
    assert _found(db_session, tags=("alpha",), tag_match="all") == {"Ann Acme", "Bo Beta"}


@pytest.mark.req("S-15")
def test_lists_any_versus_all(world: dict[str, int], db_session: Session) -> None:
    both = (world["list1"], world["list2"])
    assert _found(db_session, list_ids=both) == {"Ann Acme", "Cy Core", "Di Dune"}
    assert _found(db_session, list_ids=both, list_match="all") == {"Cy Core"}
    assert _found(db_session, list_ids=(world["list2"],)) == {"Cy Core", "Di Dune"}


# ---------------------------------------------------------------- saved searches


@pytest.mark.req("S-07", "S-15")
def test_saved_query_keeps_every_value_and_match_mode() -> None:
    pairs = [
        ("company", "Acme"),
        ("company", "Beta Corp"),
        ("tag", "a"),
        ("tag", "b"),
        ("tag_match", "all"),
        ("sort", "name"),
    ]
    saved = clean_query(pairs)
    assert saved == clean_query(saved)
    assert saved.count("company=") == 2
    assert "tag_match=all" in saved
    assert "sort" not in saved
    text = describe_query(saved)
    assert "Acme" in text
    assert "Beta Corp" in text


# ---------------------------------------------------------------- web page


@pytest.mark.req("S-15")
def test_page_filters_by_several_values_and_shows_them(
    client: TestClient, world: dict[str, int]
) -> None:
    html = client.get("/?company=Acme&company=Beta+Corp").text
    assert "Ann Acme" in html
    assert "Bo Beta" in html
    assert "Cy Core" not in html
    assert "Company: 2 selected" in html
    assert 'data-testid="clear-company">' in html  # visible, not hidden

    single = client.get("/?company=Acme").text
    assert "Company: Acme" in single
    assert 'data-testid="clear-company" hidden' in client.get("/").text


@pytest.mark.req("S-15")
def test_tag_all_mode_on_page_and_clear_drops_it(client: TestClient, world: dict[str, int]) -> None:
    page = client.get("/contacts/results?tag=alpha&tag=gamma&tag_match=all").text
    assert "Ann Acme" in page
    assert "Bo Beta" in page
    assert "Cy Core" not in page
    full = client.get("/?tag=alpha&tag=gamma&tag_match=all").text
    assert 'name="tag_match" value="all" checked' in full

    cleared = client.get("/?tag=alpha&tag=gamma&tag_match=all&clear=tag").text
    assert "Tag: " not in cleared
    assert 'name="tag_match" value="all" checked' not in cleared
    assert "Cy Core" in cleared


@pytest.mark.req("S-15")
def test_list_filter_on_page(client: TestClient, world: dict[str, int]) -> None:
    html = client.get(f"/contacts/results?list={world['list1']}&list={world['list2']}").text
    assert "Ann Acme" in html
    assert "Di Dune" in html
    assert "Bo Beta" not in html


@pytest.mark.req("S-15")
def test_related_tags_only_for_a_single_tag(
    client: TestClient, db_session: Session, world: dict[str, int]
) -> None:
    assert related_tags(db_session, "alpha")
    assert 'data-testid="related-tags"' in client.get("/?tag=alpha").text
    assert 'data-testid="related-tags"' not in client.get("/?tag=alpha&tag=gamma").text


# ---------------------------------------------------------------- API


@pytest.mark.req("S-15")
def test_api_accepts_repeated_parameters(client: TestClient, world: dict[str, int]) -> None:
    def names(params: list[tuple[str, str]]) -> set[str]:
        res = client.get("/api/search?" + urlencode(params))
        assert res.status_code == 200, res.text
        return {h["contact"]["display_name"] for h in res.json()}

    assert names([("company", "Acme"), ("company", "Core Inc")]) == {
        "Ann Acme",
        "Cy Core",
        "Di Dune",
    }
    assert names([("team", "Blue"), ("team", "Red"), ("company", "Beta Corp")]) == {"Bo Beta"}
    assert names([("tag", "alpha"), ("tag", "gamma"), ("tag_match", "all")]) == {
        "Ann Acme",
        "Bo Beta",
    }
    both = [("list", str(world["list1"])), ("list", str(world["list2"]))]
    assert names([*both, ("list_match", "all")]) == {"Cy Core"}


@pytest.mark.req("S-15")
def test_assets_carry_a_version_so_a_stale_stylesheet_is_not_reused(client: TestClient) -> None:
    html = client.get("/").text
    assert re.search(r'/static/app\.css\?v=\d+"', html)
    assert re.search(r'/static/js/app\.js\?v=\d+"', html)
    assert client.get("/static/app.css?v=1").status_code == 200
