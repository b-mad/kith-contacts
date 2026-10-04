"""Project lists (L-01 to L-05)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.contacts import ContactError, ContactNotFound
from app.models import Contact, ContactList, ListMember, Tag, list_tag
from app.search import refresh_search

MAX_NAME = 100
MAX_ROLE = 200


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise ContactError("List name cannot be empty", "name")
    if len(name) > MAX_NAME:
        raise ContactError(f"List name is longer than {MAX_NAME} characters", "name")
    return name


def _clean_role(raw: str | None) -> str | None:
    role = " ".join((raw or "").split())
    if len(role) > MAX_ROLE:
        raise ContactError(f"Role note is longer than {MAX_ROLE} characters", "role_note")
    return role or None


def _check_unique(session: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(ContactList.id).where(func.lower(ContactList.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(ContactList.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ContactError(f"A list named “{name}” already exists", "name")


def get_list(session: Session, list_id: int) -> ContactList:
    contact_list = session.scalars(
        select(ContactList)
        .where(ContactList.id == list_id)
        .options(
            selectinload(ContactList.members)
            .selectinload(ListMember.contact)
            .selectinload(Contact.emails),
            selectinload(ContactList.members)
            .selectinload(ListMember.contact)
            .selectinload(Contact.phones),
            selectinload(ContactList.members)
            .selectinload(ListMember.contact)
            .selectinload(Contact.addresses),
            selectinload(ContactList.members)
            .selectinload(ListMember.contact)
            .selectinload(Contact.contact_type),
            selectinload(ContactList.tags),
        )
    ).one_or_none()
    if contact_list is None:
        raise ContactNotFound(list_id)
    return contact_list


def all_lists(
    session: Session, *, include_archived: bool = False, tag: str | None = None
) -> Sequence[tuple[ContactList, int]]:
    """Lists with their active member counts, newest activity first by name."""
    count = (
        select(func.count())
        .select_from(ListMember)
        .join(Contact, Contact.id == ListMember.contact_id)
        .where(ListMember.list_id == ContactList.id, Contact.archived_at.is_(None))
        .scalar_subquery()
    )
    stmt = (
        select(ContactList, count)
        .options(selectinload(ContactList.tags))
        .order_by(ContactList.status, func.lower(ContactList.name))
    )
    if not include_archived:
        stmt = stmt.where(ContactList.status == "active")
    if tag:  # L-05: filter lists by one of their tags
        stmt = stmt.where(
            ContactList.id.in_(
                select(list_tag.c.list_id)
                .join(Tag, Tag.id == list_tag.c.tag_id)
                .where(func.lower(Tag.name) == tag.lower())
            )
        )
    return [(row[0], int(row[1])) for row in session.execute(stmt).all()]


def create_list(session: Session, name: str, description: str | None = None) -> ContactList:
    clean = _clean_name(name)
    _check_unique(session, clean)
    contact_list = ContactList(name=clean, description=(description or "").strip() or None)
    session.add(contact_list)
    session.flush()
    return contact_list


def find_or_create_list(session: Session, name: str) -> ContactList:
    clean = _clean_name(name)
    existing = session.scalars(
        select(ContactList).where(func.lower(ContactList.name) == clean.lower())
    ).first()
    return existing or create_list(session, clean)


def update_list(
    session: Session, contact_list: ContactList, *, name: str, description: str | None
) -> ContactList:
    clean = _clean_name(name)
    _check_unique(session, clean, exclude_id=contact_list.id)
    renamed = clean != contact_list.name
    contact_list.name = clean
    contact_list.description = (description or "").strip() or None
    session.flush()
    if renamed:  # list names are part of members' search documents (S-01)
        refresh_search(session, [m.contact_id for m in contact_list.members])
    return contact_list


def set_list_status(session: Session, contact_list: ContactList, status: str) -> ContactList:
    if status not in {"active", "archived"}:
        raise ContactError("Unknown status", "status")
    contact_list.status = status
    session.flush()
    return contact_list


def add_members(
    session: Session,
    contact_list: ContactList,
    contact_ids: Iterable[int],
    role_note: str | None = None,
) -> int:
    """Add contacts (bulk). Existing members keep their role unless a new one is given."""
    ids = sorted(set(contact_ids))
    role = _clean_role(role_note)
    found = set(session.scalars(select(Contact.id).where(Contact.id.in_(ids))).all())
    if missing := set(ids) - found:
        raise ContactError(f"Unknown contact id(s): {sorted(missing)}", "contact_ids")
    current = {m.contact_id: m for m in contact_list.members}
    added = 0
    for contact_id in ids:
        member = current.get(contact_id)
        if member is None:
            contact_list.members.append(ListMember(contact_id=contact_id, role_note=role))
            added += 1
        elif role:
            member.role_note = role
    session.flush()
    refresh_search(session, ids)
    return added


def remove_member(session: Session, contact_list: ContactList, contact_id: int) -> None:
    for member in list(contact_list.members):
        if member.contact_id == contact_id:
            contact_list.members.remove(member)
    session.flush()
    refresh_search(session, [contact_id])


def set_role_note(
    session: Session, contact_list: ContactList, contact_id: int, role_note: str | None
) -> None:
    member = next((m for m in contact_list.members if m.contact_id == contact_id), None)
    if member is None:
        raise ContactNotFound(contact_id)
    member.role_note = _clean_role(role_note)
    session.flush()


# ---------------------------------------------------------------- list tags (L-05)


def add_list_tag(session: Session, contact_list: ContactList, raw: str) -> Tag:
    """Tag a list with an existing or new tag (the same vocabulary as contacts)."""
    from app.tags import get_or_create_tag

    tag = get_or_create_tag(session, raw)
    if all(t.id != tag.id for t in contact_list.tags):
        contact_list.tags.append(tag)
        session.flush()
    return tag


def remove_list_tag(session: Session, contact_list: ContactList, tag_id: int) -> None:
    session.execute(
        delete(list_tag).where(list_tag.c.list_id == contact_list.id, list_tag.c.tag_id == tag_id)
    )
    session.flush()
    session.expire(contact_list, ["tags"])
