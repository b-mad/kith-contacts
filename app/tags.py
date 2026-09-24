"""Tags (T-01, T-02)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contacts import ContactError
from app.models import Contact, Tag, contact_tag
from app.search import refresh_search

MAX_TAG_LENGTH = 50


def normalize_tag(raw: str) -> str:
    name = " ".join(raw.replace(",", " ").split()).lstrip("#")
    if not name:
        raise ContactError("Tag cannot be empty", "tag")
    if len(name) > MAX_TAG_LENGTH:
        raise ContactError(f"Tag is longer than {MAX_TAG_LENGTH} characters", "tag")
    return name


def get_or_create_tag(session: Session, raw: str) -> Tag:
    """Case-insensitive: 'hl7' reuses an existing 'HL7'."""
    name = normalize_tag(raw)
    tag = session.scalars(select(Tag).where(func.lower(Tag.name) == name.lower())).first()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag


def add_tag(session: Session, contact_ids: Iterable[int], raw: str) -> Tag:
    """Tag one or many contacts (bulk from the action bar). Existing links are kept."""
    ids = sorted(set(contact_ids))
    tag = get_or_create_tag(session, raw)
    if ids:
        existing = set(session.scalars(select(Contact.id).where(Contact.id.in_(ids))).all())
        missing = set(ids) - existing
        if missing:
            raise ContactError(f"Unknown contact id(s): {sorted(missing)}", "contact_ids")
        session.execute(
            insert(contact_tag)
            .values([{"contact_id": i, "tag_id": tag.id} for i in ids])
            .on_conflict_do_nothing()
        )
        session.expire_all()
        refresh_search(session, ids)
    return tag


def remove_tag(session: Session, contact_id: int, tag_id: int) -> None:
    session.execute(
        delete(contact_tag).where(
            contact_tag.c.contact_id == contact_id, contact_tag.c.tag_id == tag_id
        )
    )
    session.expire_all()
    refresh_search(session, [contact_id])


@dataclass(frozen=True)
class TagCount:
    id: int
    name: str
    count: int


def tag_counts(session: Session, q: str = "", limit: int = 500) -> Sequence[TagCount]:
    """Tags with the number of active contacts using them; ``q`` filters by prefix."""
    stmt = (
        select(Tag.id, Tag.name, func.count(Contact.id))
        .select_from(Tag)
        .outerjoin(contact_tag, contact_tag.c.tag_id == Tag.id)
        .outerjoin(
            Contact, (Contact.id == contact_tag.c.contact_id) & Contact.archived_at.is_(None)
        )
        .group_by(Tag.id, Tag.name)
        .order_by(func.lower(Tag.name))
        .limit(limit)
    )
    if q.strip():
        stmt = stmt.where(func.lower(Tag.name).startswith(q.strip().lower(), autoescape=True))
    return [TagCount(i, n, c) for i, n, c in session.execute(stmt).all()]
