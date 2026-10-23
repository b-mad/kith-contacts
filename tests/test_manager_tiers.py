"""S-18: find managers by tier (L0 at the top of a reporting line, +1 for each line below)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import archive_contact
from app.models import Contact, ContactType
from app.saved_searches import clean_query, describe_query
from app.search import SearchFilters, search
from app.tiers import NOT_A_MANAGER, manager_tiers, parse_tiers, tier_label, tier_options
from tests.test_presenting import present


def _person(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    body = {"display_name": name, "contact_type_id": types["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


@pytest.fixture
def org(client: TestClient, db_session: Session) -> dict[str, int]:
    """Ceo > (Vp One > (Dir Deep > Ic Three, Ic One), Vp Two > Ic Two), plus a loner."""
    ids: dict[str, int] = {}
    for key, name, boss in (
        ("ceo", "Ceo Top", None),
        ("vp1", "Vp One", "ceo"),
        ("vp2", "Vp Two", "ceo"),
        ("dir", "Dir Deep", "vp1"),
        ("ic1", "Ic One", "vp1"),
        ("ic2", "Ic Two", "vp2"),
        ("ic3", "Ic Three", "dir"),
        ("loner", "Loner Alone", None),
    ):
        ids[key] = _person(client, db_session, name, manager_id=ids[boss] if boss else None)
    return ids


def _found(session: Session, **kw: Any) -> set[str]:
    return {h.contact.display_name for h in search(session, "", SearchFilters(**kw))}


def _rows(html: str) -> set[str]:
    return set(re.findall(r'<li class="result-card[^>]*data-name="([^"]+)"', html))


# ---------------------------------------------------------------- the tiers themselves


@pytest.mark.req("S-18")
def test_tiers_count_down_each_reporting_line_from_l0(
    db_session: Session, org: dict[str, int]
) -> None:
    assert manager_tiers(db_session) == {
        org["ceo"]: 0,
        org["vp1"]: 1,
        org["vp2"]: 1,
        org["dir"]: 2,
    }
    assert tier_options(db_session) == [0, 1, 2]
    assert manager_tiers(db_session, [org["vp1"], org["ic1"]]) == {org["vp1"]: 1}


@pytest.mark.req("S-18")
def test_every_top_of_a_line_is_l0_and_an_archived_boss_is_skipped(
    client: TestClient, db_session: Session, org: dict[str, int]
) -> None:
    boss = _person(client, db_session, "Boss Gone")
    mid = _person(client, db_session, "Mid Left", manager_id=boss)
    _person(client, db_session, "Low Left", manager_id=mid)
    archive_contact(db_session, db_session.get(Contact, boss))  # type: ignore[arg-type]
    tiers = manager_tiers(db_session)
    assert tiers[org["ceo"]] == 0
    assert tiers[mid] == 0  # same rule as the org chart: no active manager, so top of a line
    assert boss not in tiers


@pytest.mark.req("S-18")
def test_no_managers_means_no_options(client: TestClient, db_session: Session) -> None:
    _person(client, db_session, "Solo One")
    assert manager_tiers(db_session) == {}
    assert tier_options(db_session) == []


# ---------------------------------------------------------------- the filter


@pytest.mark.req("S-18")
def test_filter_by_tier_and_not_a_manager(db_session: Session, org: dict[str, int]) -> None:
    assert _found(db_session, manager_tiers=(0,)) == {"Ceo Top"}
    assert _found(db_session, manager_tiers=(1,)) == {"Vp One", "Vp Two"}
    assert _found(db_session, manager_tiers=(0, 2)) == {"Ceo Top", "Dir Deep"}
    assert _found(db_session, non_managers=True) == {
        "Ic One",
        "Ic Two",
        "Ic Three",
        "Loner Alone",
    }
    assert _found(db_session, manager_tiers=(2,), non_managers=True) == {
        "Dir Deep",
        "Ic One",
        "Ic Two",
        "Ic Three",
        "Loner Alone",
    }
    assert SearchFilters(manager_tiers=(0,)).active
    assert SearchFilters(non_managers=True).active
    assert not SearchFilters().active


@pytest.mark.req("S-18", "S-04")
def test_tier_combines_with_other_filters(db_session: Session, org: dict[str, int]) -> None:
    mine = db_session.get(Contact, org["vp2"])
    assert mine is not None
    mine.team = "Blue"
    db_session.flush()
    assert _found(db_session, manager_tiers=(1,), teams=("Blue",)) == {"Vp Two"}
    assert _found(db_session, manager_tiers=(0,), teams=("Blue",)) == set()


@pytest.mark.req("S-18")
def test_choosing_every_option_is_no_filter() -> None:
    options = [0, 1, 2]
    assert parse_tiers([], options) == ((), False)
    assert parse_tiers(["0", "1", "2", NOT_A_MANAGER], options) == ((), False)
    assert parse_tiers(["1", "0"], options) == ((0, 1), False)
    assert parse_tiers(["none"], options) == ((), True)
    assert parse_tiers(["x", "-1", " 2 ", "2", "none", "none"], options) == ((2,), True)
    # a tier that no longer exists still narrows (and finds nobody)
    assert parse_tiers(["7"], options) == ((7,), False)
    assert tier_label(0) == "L0"
    assert tier_label(NOT_A_MANAGER) == "Not a manager"


# ---------------------------------------------------------------- the contacts screen


@pytest.mark.req("S-18")
def test_page_offers_every_tier_ticked_by_default(client: TestClient, org: dict[str, int]) -> None:
    html = client.get("/").text
    assert 'data-testid="filter-tier"' in html
    boxes = re.findall(
        r'<input type="checkbox" name="tier" value="([^"]+)"[^>]*?( checked)?>', html
    )
    assert [(v, bool(c)) for v, c in boxes] == [
        ("0", True),
        ("1", True),
        ("2", True),
        ("none", True),
    ]
    assert len(_rows(html)) == 8  # nobody is filtered out by default


@pytest.mark.req("S-18")
def test_page_filters_by_the_ticked_tiers(client: TestClient, org: dict[str, int]) -> None:
    html = client.get("/?tier=1&tier=2").text
    assert _rows(html) == {"Vp One", "Vp Two", "Dir Deep"}
    boxes = dict(re.findall(r'name="tier" value="([^"]+)"[^>]*?( checked)?>', html))
    assert [k for k, v in boxes.items() if v] == ["1", "2"]
    # all options ticked is the same as no filter, and nothing is left in the saved-search URL
    everyone = client.get("/?tier=0&tier=1&tier=2&tier=none").text
    assert len(_rows(everyone)) == 8
    assert 'name="query"' not in everyone  # nothing to save: no filter is set
    saved = re.search(r'name="query" value="([^"]*)"', client.get("/?tier=1&tier=2&q=a").text)
    assert saved
    assert saved.group(1) == "q=a&amp;tier=1&amp;tier=2"
    only_managers = client.get("/?tier=0&tier=1&tier=2").text
    assert _rows(only_managers) == {"Ceo Top", "Vp One", "Vp Two", "Dir Deep"}


@pytest.mark.req("S-18")
def test_clear_resets_to_everyone(client: TestClient, org: dict[str, int]) -> None:
    html = client.get("/?tier=0&clear=tier").text
    assert len(_rows(html)) == 8


@pytest.mark.req("S-18")
def test_results_show_each_managers_tier(client: TestClient, org: dict[str, int]) -> None:
    html = client.get("/").text
    pills = {}
    for row in html.split('<li class="result-card')[1:]:
        name = re.search(r'data-name="([^"]+)"', row)
        pill = re.search(r'data-testid="tier-pill">(L\d) manager<', row)
        assert name
        if pill:
            pills[name.group(1)] = pill.group(1)
    assert pills == {"Ceo Top": "L0", "Vp One": "L1", "Vp Two": "L1", "Dir Deep": "L2"}
    card = client.get(f"/contacts/{org['dir']}").text
    assert re.search(r'data-testid="tier-pill">L2 manager<', card)
    assert 'data-testid="tier-pill"' not in client.get(f"/contacts/{org['ic1']}").text


# ---------------------------------------------------------------- saved searches and the API


@pytest.mark.req("S-18", "S-07")
def test_saved_searches_keep_the_chosen_tiers() -> None:
    assert clean_query("tier=1&tier=0&tier=1&tier=none&junk=1") == "tier=1&tier=0&tier=none"
    assert describe_query("tier=0&tier=none") == "manager tier L0 · manager tier Not a manager"


@pytest.mark.req("S-18")
def test_api_accepts_repeated_manager_tiers(client: TestClient, org: dict[str, int]) -> None:
    def names(query: str) -> set[str]:
        res = client.get(f"/api/search?{query}")
        assert res.status_code == 200, res.text
        return {r["contact"]["display_name"] for r in res.json()}

    assert names("manager_tier=0") == {"Ceo Top"}
    assert names("manager_tier=1&manager_tier=2") == {"Vp One", "Vp Two", "Dir Deep"}
    assert names("manager_tier=none") == {"Ic One", "Ic Two", "Ic Three", "Loner Alone"}
    assert len(names("")) == 8
    tiers = {
        r["contact"]["display_name"]: r["manager_tier"] for r in client.get("/api/search").json()
    }
    assert tiers["Vp One"] == 1
    assert tiers["Ic One"] is None


# ---------------------------------------------------------------- presenting mode


@pytest.mark.req("S-18", "P-02")
def test_presenting_leaves_private_people_out_of_the_tiers(
    client: TestClient, db_session: Session, org: dict[str, int]
) -> None:
    hidden = db_session.get(Contact, org["vp1"])
    assert hidden is not None
    hidden.is_private = True
    db_session.flush()
    present(client)
    html = client.get("/?tier=0").text
    assert "Vp One" not in html
    # the org chart's rule: a person whose manager is hidden heads a line of their own
    assert _rows(html) == {"Ceo Top", "Dir Deep"}
    assert "Vp One" not in client.get("/api/search?manager_tier=1").text
