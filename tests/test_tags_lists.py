"""Tags (T-01, T-02) and project lists (L-01 to L-04) — service layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound, get_contact
from app.lists import (
    add_members,
    all_lists,
    create_list,
    find_or_create_list,
    get_list,
    remove_member,
    set_list_status,
    set_role_note,
    update_list,
)
from app.models import Contact, ContactType, Tag
from app.tags import add_tag, get_or_create_tag, normalize_tag, remove_tag, tag_counts


@pytest.fixture
def people(db_session: Session) -> list[int]:
    contact_type = ContactType(name="Tag-test type", sort_order=60)
    db_session.add(contact_type)
    db_session.flush()
    contacts = [
        Contact(display_name=n, contact_type_id=contact_type.id) for n in ("Ann", "Bo", "Cy")
    ]
    db_session.add_all(contacts)
    db_session.flush()
    return [c.id for c in contacts]


# ---------------------------------------------------------------- tags


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  HL7 ", "HL7"), ("#lab   ops", "lab ops"), ("a,b", "a b")],
)
def test_normalize_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "#", "x" * 51])
def test_invalid_tags_rejected(raw: str) -> None:
    with pytest.raises(ContactError):
        normalize_tag(raw)


@pytest.mark.req("T-01")
def test_tags_reused_ignoring_case(db_session: Session) -> None:
    first = get_or_create_tag(db_session, "HL7")
    again = get_or_create_tag(db_session, "hl7")
    assert first.id == again.id
    assert again.name == "HL7"


@pytest.mark.req("T-01")
def test_any_number_of_tags_and_bulk_tagging_is_idempotent(
    db_session: Session, people: list[int]
) -> None:
    add_tag(db_session, people, "HL7")
    add_tag(db_session, people[:1], "HL7")  # already tagged: no error, no duplicate
    add_tag(db_session, people[:1], "Vendor PM")
    add_tag(db_session, people[:1], "Lab")

    ann = get_contact(db_session, people[0])
    assert [t.name for t in ann.tags] == ["HL7", "Lab", "Vendor PM"]
    counts = {t.name: t.count for t in tag_counts(db_session)}
    assert counts["HL7"] == 3


@pytest.mark.req("T-01")
def test_remove_tag(db_session: Session, people: list[int]) -> None:
    tag = add_tag(db_session, people[:2], "HL7")
    remove_tag(db_session, people[0], tag.id)
    assert get_contact(db_session, people[0]).tags == []
    assert [t.name for t in get_contact(db_session, people[1]).tags] == ["HL7"]


def test_tag_counts_ignore_archived_and_filter_by_prefix(
    db_session: Session, people: list[int]
) -> None:
    add_tag(db_session, people, "HL7")
    add_tag(db_session, people[:1], "Hiring")
    add_tag(db_session, people[:1], "Lab")
    db_session.get(Contact, people[1]).archived_at = datetime.now(UTC)  # type: ignore[union-attr]
    db_session.flush()

    counts = {t.name: t.count for t in tag_counts(db_session)}
    assert counts["HL7"] == 2
    assert [t.name for t in tag_counts(db_session, "h")] == ["Hiring", "HL7"]


def test_tagging_unknown_contact_fails(db_session: Session) -> None:
    with pytest.raises(ContactError, match="Unknown contact"):
        add_tag(db_session, [999_999], "x")


def test_tag_with_no_contacts_just_creates_it(db_session: Session) -> None:
    tag = add_tag(db_session, [], "Orphan")
    assert db_session.get(Tag, tag.id) is not None


# ---------------------------------------------------------------- lists


@pytest.mark.req("L-01")
def test_create_rename_describe_archive(db_session: Session) -> None:
    project = create_list(db_session, "  Q4   LIS integration ", "Lab system cut-over")
    assert project.name == "Q4 LIS integration"

    update_list(db_session, project, name="Q4 LIS go-live", description="  ")
    set_list_status(db_session, project, "archived")

    assert (project.name, project.description, project.status) == (
        "Q4 LIS go-live",
        None,
        "archived",
    )
    assert project.id not in [cl.id for cl, _ in all_lists(db_session)]
    assert project.id in [cl.id for cl, _ in all_lists(db_session, include_archived=True)]
    with pytest.raises(ContactError):
        set_list_status(db_session, project, "deleted")


@pytest.mark.req("L-01")
def test_list_names_unique_ignoring_case(db_session: Session) -> None:
    create_list(db_session, "Launch")
    with pytest.raises(ContactError, match="already exists"):
        create_list(db_session, "LAUNCH")
    other = create_list(db_session, "Other")
    with pytest.raises(ContactError, match="already exists"):
        update_list(db_session, other, name="launch", description=None)
    assert find_or_create_list(db_session, "launch").name == "Launch"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_invalid_list_names(db_session: Session, name: str) -> None:
    with pytest.raises(ContactError):
        create_list(db_session, name)


@pytest.mark.req("L-02", "L-03")
def test_members_roles_and_many_lists(db_session: Session, people: list[int]) -> None:
    alpha = create_list(db_session, "Alpha")
    beta = create_list(db_session, "Beta")

    assert add_members(db_session, alpha, people, "reviewer") == 3
    assert add_members(db_session, alpha, people[:1], "customer sponsor") == 0  # updates role
    assert add_members(db_session, alpha, people[1:2]) == 0  # keeps existing role
    add_members(db_session, beta, people[:1])
    set_role_note(db_session, alpha, people[2], "vendor PM")

    roles = {m.contact_id: m.role_note for m in get_list(db_session, alpha.id).members}
    assert roles == {people[0]: "customer sponsor", people[1]: "reviewer", people[2]: "vendor PM"}
    assert sorted(
        cl.name for cl in [m.contact_list for m in get_contact(db_session, people[0]).memberships]
    ) == [
        "Alpha",
        "Beta",
    ]
    counts = {cl.name: n for cl, n in all_lists(db_session)}
    assert counts == {"Alpha": 3, "Beta": 1}


@pytest.mark.req("L-02")
def test_remove_member(db_session: Session, people: list[int]) -> None:
    alpha = create_list(db_session, "Alpha")
    add_members(db_session, alpha, people)
    remove_member(db_session, alpha, people[1])
    assert sorted(m.contact_id for m in get_list(db_session, alpha.id).members) == [
        people[0],
        people[2],
    ]


def test_member_errors(db_session: Session, people: list[int]) -> None:
    alpha = create_list(db_session, "Alpha")
    with pytest.raises(ContactError, match="Unknown contact"):
        add_members(db_session, alpha, [999_999])
    with pytest.raises(ContactNotFound):
        set_role_note(db_session, alpha, people[0], "x")
    with pytest.raises(ContactError, match="longer"):
        add_members(db_session, alpha, people[:1], "x" * 201)
    with pytest.raises(ContactNotFound):
        get_list(db_session, 999_999)


def test_deleting_a_contact_removes_memberships_and_tags(
    db_session: Session, people: list[int]
) -> None:
    alpha = create_list(db_session, "Alpha")
    add_members(db_session, alpha, people[:1])
    add_tag(db_session, people[:1], "HL7")
    db_session.delete(db_session.get(Contact, people[0]))
    db_session.flush()
    db_session.expire_all()
    assert get_list(db_session, alpha.id).members == []
    assert db_session.scalars(select(Tag)).one().contacts == []
