"""Related contacts on a card (T-03): shared tags, lists, team, manager and company."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.models import Contact, ContactList, ListMember, Tag, contact_tag

WEIGHTS = {"tag": 3, "list": 2, "team": 2, "manager": 2, "company": 1}
# A company only counts when it is small enough to be a signal (not "everyone at work").
MAX_COMPANY_SIZE = 25


@dataclass
class Related:
    contact: Contact
    score: int = 0
    reasons: list[str] = field(default_factory=list)


def related_contacts(session: Session, contact: Contact, limit: int = 8) -> list[Related]:
    scores: dict[int, int] = defaultdict(int)
    reasons: dict[int, list[str]] = defaultdict(list)
    shared_tags: dict[int, list[str]] = defaultdict(list)
    shared_lists: dict[int, list[str]] = defaultdict(list)

    other_tag = aliased(contact_tag)
    for other_id, tag_name in session.execute(
        select(other_tag.c.contact_id, Tag.name)
        .select_from(contact_tag)
        .join(other_tag, and_(other_tag.c.tag_id == contact_tag.c.tag_id))
        .join(Tag, Tag.id == contact_tag.c.tag_id)
        .where(contact_tag.c.contact_id == contact.id, other_tag.c.contact_id != contact.id)
    ).all():
        shared_tags[other_id].append(tag_name)

    other_member = aliased(ListMember)
    for other_id, list_name in session.execute(
        select(other_member.contact_id, ContactList.name)
        .select_from(ListMember)
        .join(other_member, other_member.list_id == ListMember.list_id)
        .join(ContactList, ContactList.id == ListMember.list_id)
        .where(
            ListMember.contact_id == contact.id,
            other_member.contact_id != contact.id,
            ContactList.status == "active",
        )
    ).all():
        shared_lists[other_id].append(list_name)

    for other_id, names in shared_tags.items():
        scores[other_id] += WEIGHTS["tag"] * len(names)
        reasons[other_id].append(
            "tag" + ("s " if len(names) > 1 else " ") + ", ".join(sorted(names))
        )
    for other_id, names in shared_lists.items():
        scores[other_id] += WEIGHTS["list"] * len(names)
        reasons[other_id].append("list " + ", ".join(sorted(names)))

    def same(column: object, label: str, weight: int) -> None:
        stmt = select(Contact.id).where(Contact.id != contact.id, Contact.archived_at.is_(None))
        value = getattr(contact, label if label != "manager" else "manager_id")
        if value is None:
            return
        if label in {"team", "company"}:
            stmt = stmt.where(func.lower(column) == str(value).lower())
        else:
            stmt = stmt.where(column == value)
        ids = session.scalars(stmt).all()
        if label == "company" and len(ids) + 1 > MAX_COMPANY_SIZE:
            return
        for other_id in ids:
            scores[other_id] += weight
            reasons[other_id].append(f"same {label}")

    same(Contact.team, "team", WEIGHTS["team"])
    same(Contact.manager_id, "manager", WEIGHTS["manager"])
    same(Contact.company, "company", WEIGHTS["company"])

    # Manager and direct reports are already on the card.
    exclude = {r.id for r in contact.reports} | (
        {contact.manager_id} if contact.manager_id else set()
    )
    candidates = [cid for cid in scores if cid not in exclude]
    if not candidates:
        return []
    people = {
        c.id: c
        for c in session.scalars(
            select(Contact).where(Contact.id.in_(candidates), Contact.archived_at.is_(None))
        )
    }
    ranked = sorted(
        (cid for cid in candidates if cid in people),
        key=lambda cid: (-scores[cid], people[cid].display_name.lower()),
    )
    return [Related(people[cid], scores[cid], reasons[cid]) for cid in ranked[:limit]]
