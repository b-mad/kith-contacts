"""Contact-type administration per instance (I-08, C-05)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound
from app.models import Contact, ContactType

MAX_NAME = 50


def _clean(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise ContactError("Type name cannot be empty", "name")
    if len(name) > MAX_NAME:
        raise ContactError(f"Type name is longer than {MAX_NAME} characters", "name")
    return name


def _get(session: Session, type_id: int) -> ContactType:
    contact_type = session.get(ContactType, type_id)
    if contact_type is None:
        raise ContactNotFound(type_id)
    return contact_type


def _unique(session: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(ContactType.id).where(func.lower(ContactType.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(ContactType.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ContactError(f"A type named “{name}” already exists", "name")


def types_with_counts(session: Session) -> Sequence[tuple[ContactType, int]]:
    count = (
        select(func.count())
        .select_from(Contact)
        .where(Contact.contact_type_id == ContactType.id)
        .scalar_subquery()
    )
    rows = session.execute(
        select(ContactType, count).order_by(ContactType.sort_order, ContactType.name)
    )
    return [(t, int(n)) for t, n in rows.all()]


def add_type(session: Session, raw: str) -> ContactType:
    name = _clean(raw)
    _unique(session, name)
    last = session.scalar(select(func.max(ContactType.sort_order))) or 0
    contact_type = ContactType(name=name, sort_order=last + 1)
    session.add(contact_type)
    session.flush()
    return contact_type


def rename_type(session: Session, type_id: int, raw: str) -> ContactType:
    contact_type = _get(session, type_id)
    name = _clean(raw)
    _unique(session, name, exclude_id=type_id)
    contact_type.name = name
    session.flush()
    return contact_type


def move_type(session: Session, type_id: int, direction: int) -> None:
    """Swap with the neighbour above (-1) or below (+1)."""
    ordered = [t for t, _ in types_with_counts(session)]
    index = next(i for i, t in enumerate(ordered) if t.id == _get(session, type_id).id)
    other = index + direction
    if 0 <= other < len(ordered):
        ordered[index], ordered[other] = ordered[other], ordered[index]
        for position, contact_type in enumerate(ordered):
            contact_type.sort_order = position
        session.flush()


def delete_type(session: Session, type_id: int, move_to_id: int | None = None) -> int:
    """Delete a type; contacts using it must be moved to another type first. Returns moved count."""
    contact_type = _get(session, type_id)
    if session.scalar(select(func.count()).select_from(ContactType)) == 1:
        raise ContactError("An instance needs at least one contact type", "type")
    used = session.scalar(select(func.count()).where(Contact.contact_type_id == type_id)) or 0
    if used and move_to_id is None:
        raise ContactError(
            f"{used} contact(s) use “{contact_type.name}”: choose a type to move them to", "move_to"
        )
    if move_to_id is not None:
        if move_to_id == type_id:
            raise ContactError("Choose a different type to move contacts to", "move_to")
        _get(session, move_to_id)
        session.execute(
            update(Contact)
            .where(Contact.contact_type_id == type_id)
            .values(contact_type_id=move_to_id)
        )
    session.delete(contact_type)
    session.flush()
    return int(used)
