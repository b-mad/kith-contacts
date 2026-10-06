"""Org chart Focus and Outline views (S-06, S-16, S-17, ADR-0030)."""

from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import create_contact
from app.models import Contact, ContactType
from app.org import build_focus, build_org, find_people, outline_rows, search_terms
from app.photos import set_photo
from app.privacy import PrivacySettings
from app.schemas import ContactCreate
from scripts.seed import seed
from tests.test_presenting import fresh, present, use_settings


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def cid(session: Session, name: str) -> int:
    return session.scalars(select(Contact.id).where(Contact.display_name == name)).one()


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (200, 200), (30, 120, 90)).save(out, "JPEG")
    return out.getvalue()


def person(session: Session, name: str, manager: int | None = None, **fields: object) -> Contact:
    kind = session.scalars(select(ContactType.id).order_by(ContactType.id)).first()
    if kind is None:
        created = ContactType(name="Employee")
        session.add(created)
        session.flush()
        kind = created.id
    data = ContactCreate.model_validate(
        {"display_name": name, "contact_type_id": kind, "manager_id": manager, **fields}
    )
    return create_contact(session, data)


# ---------------------------------------------------------------- Focus data (S-16)


@pytest.mark.req("S-16")
def test_focus_without_a_person_lists_the_leaders(seeded: Session) -> None:
    view = build_focus(seeded)
    assert view.focus is None
    assert view.cards[0].name == "Priya Raman"  # the biggest organization first
    assert {"Daniel Kim", "Paul Bennett"} <= {c.name for c in view.cards}
    assert view.cards[0].direct == len(build_org(seeded).roots[0].children)
    assert view.cards[0].total == build_org(seeded).roots[0].total_reports
    assert view.unplaced > 0  # people with no manager and no reports stay out


@pytest.mark.req("S-16")
def test_focus_on_a_manager_shows_chain_peers_and_reports(seeded: Session) -> None:
    view = build_focus(seeded, cid(seeded, "Maria Lopez"))
    assert view.focus is not None
    assert view.focus.name == "Maria Lopez"
    assert view.focus.title
    assert view.focus.team
    assert [p.name for p in view.chain] == ["Priya Raman"]
    assert view.manager is not None
    assert view.manager.name == "Priya Raman"
    assert "Maria Lopez" not in [p.name for p in view.peers]
    assert {"Aisha Bello", "Ben Okafor"} <= {p.name for p in view.peers}
    assert len(view.cards) == 5
    assert view.focus.direct == 5
    assert [c.name for c in view.cards] == sorted((c.name for c in view.cards), key=str.lower)


@pytest.mark.req("S-16")
def test_focus_on_a_leaf_and_on_an_unknown_id(seeded: Session) -> None:
    leaf = build_focus(seeded, cid(seeded, "Dev Patel"))
    assert [p.name for p in leaf.chain] == ["Priya Raman", "Maria Lopez"]
    assert leaf.cards == []
    assert build_focus(seeded, 999_999).focus is None


@pytest.mark.req("S-16")
def test_top_level_peers_are_the_other_leaders(seeded: Session) -> None:
    view = build_focus(seeded, cid(seeded, "Priya Raman"))
    assert view.manager is None
    assert view.chain == []
    assert "Daniel Kim" in [p.name for p in view.peers]


@pytest.mark.req("S-16")
def test_peers_are_capped_with_a_count_of_the_rest(db_session: Session) -> None:
    boss = person(db_session, "Big Boss")
    for n in range(12):
        person(db_session, f"Report {n:02d}", boss.id)
    view = build_focus(db_session, cid(db_session, "Report 00"))
    assert len(view.peers) == 8
    assert view.more_peers == 3  # 11 peers, 8 listed


@pytest.mark.req("S-16")
def test_photo_flag_follows_the_stored_photo(seeded: Session) -> None:
    maria = cid(seeded, "Maria Lopez")
    assert not build_focus(seeded, maria).focus.has_photo  # type: ignore[union-attr]
    set_photo(seeded, maria, jpeg())
    view = build_focus(seeded, cid(seeded, "Dev Patel"))
    assert [p.has_photo for p in view.chain] == [False, True]  # Priya, Maria


# ---------------------------------------------------------------- Outline data (S-17)


def shown(rows: list) -> list[str]:  # type: ignore[type-arg]
    return [r.person.name for r in rows if not r.hidden]


@pytest.mark.req("S-17")
def test_outline_levels(seeded: Session) -> None:
    roots = build_org(seeded).roots
    one = outline_rows(roots, "1")
    assert shown(one) == [r.name for r in roots]
    assert all(not r.open for r in one)

    two = outline_rows(roots, "2")
    assert "Maria Lopez" in shown(two)
    assert "Dev Patel" not in shown(two)  # three levels down
    assert "Dev Patel" in [r.person.name for r in two]  # still on the page, closed
    assert next(r for r in two if r.person.name == "Priya Raman").open
    assert not next(r for r in two if r.person.name == "Maria Lopez").open

    everything = outline_rows(roots, "all")
    assert not any(r.hidden for r in everything)
    assert len(everything) == sum(1 + r.total_reports for r in roots)
    leaf = next(r for r in everything if r.person.name == "Dev Patel")
    assert not leaf.expandable


@pytest.mark.req("S-17")
def test_outline_search_keeps_matches_and_their_managers_open(seeded: Session) -> None:
    rows = outline_rows(build_org(seeded).roots, "1", search_terms("dev"))
    names = [r.person.name for r in rows]
    assert names == ["Priya Raman", "Maria Lopez", "Dev Patel"]
    assert [r.hit for r in rows] == [False, False, True]
    assert all(r.open and not r.hidden for r in rows[:2])
    assert not rows[2].expandable
    assert outline_rows(build_org(seeded).roots, "2", search_terms("zzzz")) == []


@pytest.mark.req("S-17")
def test_outline_counts_are_direct_and_total(seeded: Session) -> None:
    rows = outline_rows(build_org(seeded).roots, "all")
    maria = next(r for r in rows if r.person.name == "Maria Lopez")
    assert (maria.person.direct, maria.person.total) == (5, 5)
    priya = next(r for r in rows if r.person.name == "Priya Raman")
    assert priya.person.total > priya.person.direct


@pytest.mark.req("S-17")
def test_find_people_matches_name_or_title_words(seeded: Session) -> None:
    assert [p.name for p in find_people(seeded, "maria")] == ["Maria Lopez"]
    assert find_people(seeded, "   ") == []
    manager_titled = find_people(seeded, "engineering manager")
    assert manager_titled
    assert all("manager" in (p.title or "").lower() for p in manager_titled)
    for found in find_people(seeded, "a"):
        manager = seeded.scalar(select(Contact.manager_id).where(Contact.id == found.id))
        assert found.direct > 0 or manager is not None  # people outside the chart are not listed


# ---------------------------------------------------------------- pages


@pytest.fixture
def seeded_client(client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    return client


@pytest.mark.req("S-16")
def test_default_view_is_focus_with_team_on_the_cards(seeded_client: TestClient) -> None:
    page = seeded_client.get("/org").text
    assert 'data-testid="org-cards"' in page
    assert 'data-testid="org-outline"' not in page
    assert "Priya Raman" in page
    assert "not shown" in page  # the footnote about people without a manager or reports

    maria = seeded_client.get("/api/search", params={"q": "Maria Lopez"}).json()[0]["contact"]
    focused = seeded_client.get(f"/org?root={maria['id']}").text
    assert 'data-testid="org-chain"' in focused
    assert 'data-testid="org-focus"' in focused
    assert "Dev Patel" in focused
    assert "Paul Bennett" not in focused
    assert re.search(r'class="org-team">[^<]+<', focused)
    assert "5 direct reports · 5 in total" in focused  # the focus card


@pytest.mark.req("S-16")
def test_report_cards_link_down_a_level(seeded_client: TestClient, db_session: Session) -> None:
    priya = cid(db_session, "Priya Raman")
    maria = cid(db_session, "Maria Lopez")
    page = seeded_client.get(f"/org?root={priya}").text
    assert f'href="/org?root={maria}"' in page
    assert re.search(r"5 direct · 5 in total", page)


@pytest.mark.req("S-16")
def test_photos_show_when_they_exist_and_initials_otherwise(
    seeded_client: TestClient, db_session: Session
) -> None:
    priya = cid(db_session, "Priya Raman")
    maria = cid(db_session, "Maria Lopez")
    set_photo(db_session, maria, jpeg())
    page = seeded_client.get(f"/org?root={priya}").text
    assert f'src="/contacts/{maria}/photo"' in page
    assert 'loading="lazy"' in page
    assert f'src="/contacts/{cid(db_session, "Ben Okafor")}/photo"' not in page
    assert 'class="av av-48 initials"' in page


@pytest.mark.req("S-16")
def test_unknown_values_fall_back_to_defaults(seeded_client: TestClient) -> None:
    assert 'data-testid="org-cards"' in seeded_client.get("/org?view=bogus&levels=9").text
    outline = seeded_client.get("/org?view=outline&levels=9").text
    assert 'aria-current="true">2<' in outline
    assert seeded_client.get("/org?root=999999").status_code == 200


@pytest.mark.req("S-16")
def test_focus_search_lists_matches(seeded_client: TestClient) -> None:
    page = seeded_client.get("/org?q=maria").text
    assert 'data-testid="org-matches"' in page
    assert "Maria Lopez" in page
    none = seeded_client.get("/org?q=zzzz").text
    assert "No one in the chart matches" in none


@pytest.mark.req("S-17")
def test_outline_page_has_counts_levels_and_no_team(seeded_client: TestClient) -> None:
    page = seeded_client.get("/org?view=outline").text
    assert 'data-testid="org-outline"' in page
    assert "data-org-toggle" in page
    assert "<b>5</b> · 5" in page
    assert "Show levels" in page
    assert "Collapse all" in page
    assert "Expand all" in page
    assert "org-team" not in page  # Team is not shown on Outline rows
    assert "not shown" in page
    hidden_rows = re.findall(r"<li class=\"org-row[^\"]*\" [^>]*hidden", page)
    assert hidden_rows  # level 2 closes the third level
    everything = seeded_client.get("/org?view=outline&levels=all").text
    assert not re.findall(r"<li class=\"org-row[^\"]*\" [^>]*hidden", everything)


@pytest.mark.req("S-17")
def test_outline_search_highlights_and_opens_ancestors(seeded_client: TestClient) -> None:
    page = seeded_client.get("/org?view=outline&q=dev").text
    assert "<mark>Dev</mark>" in page
    assert "Maria Lopez" in page
    assert "Paul Bennett" not in page
    assert "1 match for" in page
    assert "No one in the chart matches" in seeded_client.get("/org?view=outline&q=zzzz").text


@pytest.mark.req("S-17")
def test_outline_rows_link_to_the_focus_view(
    seeded_client: TestClient, db_session: Session
) -> None:
    maria = cid(db_session, "Maria Lopez")
    page = seeded_client.get("/org?view=outline").text
    assert (
        f'href="/org?root={maria}" aria-label="Show the team of Maria Lopez in Focus view"' in page
    )


@pytest.mark.req("S-17")
def test_switching_views_keeps_the_focused_person(
    seeded_client: TestClient, db_session: Session
) -> None:
    maria = cid(db_session, "Maria Lopez")
    page = seeded_client.get(f"/org?root={maria}").text
    assert f'href="/org?view=outline&amp;root={maria}"' in page


# ---------------------------------------------------------------- presenting mode (P-02, P-03)


@pytest.mark.req("P-02", "S-16")
def test_presenting_hides_photos_and_private_people(
    client: TestClient, db_session: Session
) -> None:
    hidden = person(db_session, "Zqxcanaryboss Hidden")
    hidden.is_private = True
    lead = person(db_session, "Lena Lead", title="Director", team="Platform")
    shown = person(db_session, "Sam Shown", lead.id, title="Engineer", team="Platform")
    person(db_session, "Quinn Under", hidden.id, title="Analyst")
    set_photo(db_session, shown.id, jpeg())
    use_settings(client, db_session, PrivacySettings(hidden=frozenset({"photo"})))
    fresh(db_session)

    before = client.get(f"/org?root={lead.id}").text
    assert f'src="/contacts/{shown.id}/photo"' in before

    present(client)
    for url in (f"/org?root={lead.id}", "/org", "/org?view=outline&levels=all"):
        page = client.get(url).text
        assert "/photo" not in page, url
        assert "zqxcanary" not in page.lower(), url
    assert "Sam Shown" in client.get(f"/org?root={lead.id}").text


@pytest.mark.req("P-03", "S-16", "S-17")
def test_names_only_blanks_title_team_and_photos(client: TestClient, db_session: Session) -> None:
    lead = person(db_session, "Lena Lead", title="Zqxdirector", team="Zqxplatform")
    sam = person(db_session, "Sam Shown", lead.id, title="Zqxengineer", team="Zqxplatform")
    set_photo(db_session, sam.id, jpeg())
    use_settings(client, db_session, PrivacySettings(view="names"))
    fresh(db_session)
    present(client)
    for url in (f"/org?root={lead.id}", "/org", "/org?view=outline&levels=all"):
        page = client.get(url).text
        assert "Lena Lead" in page, url
        assert "zqx" not in page.lower(), url
        assert "/photo" not in page, url  # initials only
    assert "Sam Shown" in client.get(f"/org?root={lead.id}").text
    searched = client.get("/org?q=zqxengineer").text
    assert "No one in the chart matches" in searched  # the hidden title can't be searched
