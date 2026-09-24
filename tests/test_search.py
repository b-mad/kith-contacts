"""Context search (S-01 to S-05)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.contacts import create_contact, get_contact, update_contact
from app.lists import add_members, create_list, update_list
from app.models import Contact, ContactType
from app.schemas import ContactCreate, ContactUpdate
from app.search import (
    SearchFilters,
    matched_fields,
    query_terms,
    refresh_all,
    search,
    to_tsquery_text,
)
from app.tags import add_tag
from scripts.seed import seed


def names(hits: list) -> list[str]:  # type: ignore[type-arg]
    return [h.contact.display_name for h in hits]


def by_name(session: Session, name: str) -> Contact:
    return session.scalars(select(Contact).where(Contact.display_name == name)).one()


@pytest.fixture
def type_id(db_session: Session) -> int:
    contact_type = ContactType(name="Search-test type", sort_order=50)
    db_session.add(contact_type)
    db_session.flush()
    return contact_type.id


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


# ---------------------------------------------------------------- parsing (unit)


def test_query_terms_split_words_and_drop_punctuation() -> None:
    assert query_terms("Lab-res,  MARIA's  (HL7)") == ["lab", "res", "maria", "s", "hl7"]
    assert query_terms("   ") == []
    assert query_terms("a b c d e f g h i j", limit=3) == ["a", "b", "c"]


def test_tsquery_is_prefix_and_injection_safe() -> None:
    terms = query_terms("lab & !res:* | (x)")
    assert to_tsquery_text(terms, "&") == "lab:* & res:* & x:*"
    assert to_tsquery_text(["a", "b"], "|") == "a:* | b:*"


# ---------------------------------------------------------------- user stories (S-01, S-02)


@pytest.mark.req("S-01", "S-02")
def test_recall_by_context_finds_engineer_on_marias_team(seeded: Session) -> None:
    """US-1: 'lab results pipeline Maria' finds the engineer who owns that work."""
    hits = search(seeded, "lab results pipeline maria")

    assert "Dev Patel" in names(hits)[:3]
    dev = next(h for h in hits if h.contact.display_name == "Dev Patel")
    fields = dict(dev.matched)
    assert fields["manager"] == "Maria Lopez"
    assert "lab results pipeline" in fields["works on"].lower()


@pytest.mark.req("S-01")
def test_name_match_ranks_first(seeded: Session) -> None:
    hits = search(seeded, "data platform maria")
    assert names(hits)[0] == "Maria Lopez"
    assert {"Dev Patel", "Chen Wei"} <= set(names(hits))


@pytest.mark.req("S-01")
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("peachtree lab director", "Robert Lin"),  # company + title
        ("submission", "Fatima Zahra"),  # works on / notes
        ("interlink", "Yuki Tanaka"),  # company
        ("cloudvaulthosting", "Carlos Mendes"),  # email domain
        ("pronounced", None),  # nothing
    ],
)
def test_matches_across_context_fields(seeded: Session, query: str, expected: str | None) -> None:
    result = names(search(seeded, query))
    if expected is None:
        assert result == []
    else:
        assert expected in result[:3]


@pytest.mark.req("S-03")
def test_prefix_matching(seeded: Session) -> None:
    assert "Dev Patel" in names(search(seeded, "lab res pipe"))


@pytest.mark.req("S-03")
def test_typo_tolerance_on_names(seeded: Session) -> None:
    hits = search(seeded, "Mria")
    assert names(hits)[0] == "Maria Lopez"
    assert hits[0].fuzzy is True


def test_any_word_fallback_when_no_contact_has_every_word(seeded: Session) -> None:
    hits = search(seeded, "kwame zzzzqq")
    assert names(hits)[0] == "Kwame Mensah"


@pytest.mark.req("S-02")
def test_matched_fields_skip_the_persons_own_name(seeded: Session) -> None:
    maria = get_contact(seeded, by_name(seeded, "Maria Lopez").id)
    assert matched_fields(maria, ["maria"]) == []
    dev = get_contact(seeded, by_name(seeded, "Dev Patel").id)
    assert ("manager", "Maria Lopez") in matched_fields(dev, ["maria"])


def test_long_fields_are_shown_as_snippets(seeded: Session) -> None:
    contact = by_name(seeded, "Samir Haddad")
    contact.notes = "Lorem ipsum dolor sit amet " * 5 + "rustacean " + "consectetur " * 10
    matched = dict(matched_fields(contact, ["rustacean"]))
    assert matched["notes"].startswith("…")
    assert matched["notes"].endswith("…")
    assert "rustacean" in matched["notes"]
    assert len(matched["notes"]) <= 62


# ---------------------------------------------------------------- filters (S-04)


@pytest.mark.req("S-04")
def test_filters_combine(seeded: Session) -> None:
    maria = by_name(seeded, "Maria Lopez")
    employee = seeded.scalars(select(ContactType).where(ContactType.name == "Employee")).one()

    team = names(search(seeded, "", SearchFilters(team="data platform")))
    reports = names(search(seeded, "", SearchFilters(manager_id=maria.id)))
    both = names(search(seeded, "analytics", SearchFilters(manager_id=maria.id)))
    company = names(search(seeded, "", SearchFilters(company="PEACHTREE LABS")))
    typed = search(seeded, "", SearchFilters(type_id=employee.id))

    assert "Maria Lopez" in team
    assert len(team) == 6
    assert "Maria Lopez" not in reports
    assert set(reports) == set(team) - {"Maria Lopez"}
    assert both == ["Olivia Brooks"]
    assert set(company) == {"Robert Lin", "Sofia Rossi", "Jamal Wright", "Brian Howell"}
    assert all(h.contact.contact_type_id == employee.id for h in typed)


@pytest.mark.req("S-04", "T-02")
def test_tag_filter(seeded: Session) -> None:
    ids = [by_name(seeded, n).id for n in ("Dev Patel", "Yuki Tanaka")]
    add_tag(seeded, ids, "HL7")
    assert set(names(search(seeded, "", SearchFilters(tag="hl7")))) == {"Dev Patel", "Yuki Tanaka"}


@pytest.mark.req("S-04", "L-02")
def test_list_filter(seeded: Session) -> None:
    project = create_list(seeded, "Q4 LIS integration")
    add_members(seeded, project, [by_name(seeded, "Robert Lin").id])
    assert names(search(seeded, "", SearchFilters(list_id=project.id))) == ["Robert Lin"]


@pytest.mark.req("C-10", "S-04")
def test_favorites_filter(seeded: Session) -> None:
    by_name(seeded, "Grace Kim").is_favorite = True
    seeded.flush()
    assert names(search(seeded, "", SearchFilters(favorites=True))) == ["Grace Kim"]


def test_archived_hidden_unless_requested(seeded: Session) -> None:
    from datetime import UTC, datetime

    by_name(seeded, "Grace Kim").archived_at = datetime.now(UTC)
    seeded.flush()
    assert "Grace Kim" not in names(search(seeded, "grace"))
    assert "Grace Kim" in names(search(seeded, "grace", SearchFilters(include_archived=True)))


def test_sort_without_query(seeded: Session) -> None:
    by_company = names(search(seeded, "", SearchFilters(team="Data Platform"), sort="name"))
    assert by_company == sorted(by_company, key=str.lower)


# ---------------------------------------------------------------- the index stays current (S-01)


@pytest.mark.req("S-01")
def test_index_follows_every_kind_of_change(seeded: Session) -> None:
    dev = by_name(seeded, "Dev Patel")
    maria = get_contact(seeded, by_name(seeded, "Maria Lopez").id)

    # a tag
    add_tag(seeded, [dev.id], "Quokka")
    assert names(search(seeded, "quokka")) == ["Dev Patel"]

    # a list, then renaming the list
    project = create_list(seeded, "Wombat rollout")
    add_members(seeded, project, [dev.id])
    assert names(search(seeded, "wombat")) == ["Dev Patel"]
    update_list(seeded, project, name="Platypus rollout", description=None)
    assert names(search(seeded, "wombat")) == []
    assert names(search(seeded, "platypus")) == ["Dev Patel"]

    # the manager's name changes -> reports are found by the new name
    update_contact(seeded, maria, ContactUpdate(display_name="Mariela Lopez"))
    assert "Dev Patel" in names(search(seeded, "mariela"))

    # an email is added
    update_contact(
        seeded,
        get_contact(seeded, dev.id),
        ContactUpdate.model_validate({"emails": [{"email": "devp@numbat.example"}]}),
    )
    assert names(search(seeded, "numbat")) == ["Dev Patel"]


def test_new_contact_is_searchable_immediately(db_session: Session, type_id: int) -> None:
    create_contact(
        db_session,
        ContactCreate(display_name="Xiomara", contact_type_id=type_id, works_on="Echidna project"),
    )
    assert names(search(db_session, "echidna")) == ["Xiomara"]


# ---------------------------------------------------------------- performance (S-05, N-03)


@pytest.mark.req("S-05")
def test_search_is_fast_with_ten_thousand_contacts(db_session: Session, type_id: int) -> None:
    db_session.execute(
        text(
            """
            INSERT INTO contact (display_name, contact_type_id, company, team, title, works_on)
            SELECT 'Person ' || g, :type_id, 'Company ' || (g % 200), 'Team ' || (g % 50),
                   'Engineer', 'Project ' || (g % 500) || ' pipeline work'
            FROM generate_series(1, 10000) AS g
            """
        ),
        {"type_id": type_id},
    )
    refresh_all(db_session)
    db_session.execute(text("ANALYZE contact"))

    timings = []
    for query in ["project 42 pipeline", "team 7", "persn 99", "company 150 engineer"]:
        start = time.perf_counter()
        hits = search(db_session, query, limit=50)
        timings.append(time.perf_counter() - start)
        assert hits

    assert max(timings) < 0.2, f"search took {max(timings):.3f}s"
