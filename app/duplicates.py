"""Duplicate detection and merge (C-12, ADR-0012).

Candidates are pairs of active contacts that share an email address (ignoring
case), or whose names are similar (``pg_trgm`` similarity >= 0.6) and whose
companies match or are blank on one side. A merge keeps one contact, moves
everything from the other onto it, stores a JSON snapshot of the other in
``contact_merge`` and deletes it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contacts import (
    ContactError,
    ContactNotFound,
    check_manager,
    get_contact,
    resolve_company,
)
from app.exchange import contact_record
from app.models import (
    Activity,
    Contact,
    ContactEmail,
    ContactMerge,
    ContactPhone,
    ContactPhoto,
    CustomField,
    DuplicateDismissal,
    ListMember,
    contact_tag,
)
from app.search import refresh_search

NAME_SIMILARITY = 0.6

# Fields the user chooses between when both contacts have different values.
MERGE_FIELDS: tuple[tuple[str, str], ...] = (
    ("display_name", "Display name"),
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("nickname", "Nickname"),
    ("contact_type_id", "Type"),
    ("company", "Company"),
    ("title", "Title"),
    ("team", "Team"),
    ("department", "Department"),
    ("location", "Location"),
    ("manager_id", "Manager"),
    ("slack_handle", "Slack handle"),
    ("slack_url", "Slack link"),
    ("teams_url", "Teams link"),
    ("pronunciation", "Pronunciation"),
)
# Free-text fields that are combined when both have different text.
COMBINED_FIELDS = ("works_on", "notes")

Side = Literal["keep", "other"]


@dataclass
class DuplicatePair:
    a: Contact
    b: Contact
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0


def _ordered(x: int, y: int) -> tuple[int, int]:
    return (x, y) if x < y else (y, x)


_EMAIL_PAIRS = text(
    """
    SELECT DISTINCT e1.contact_id AS a, e2.contact_id AS b, lower(e1.email) AS email
    FROM contact_email e1
    JOIN contact_email e2
      ON lower(e1.email) = lower(e2.email) AND e1.contact_id < e2.contact_id
    JOIN contact c1 ON c1.id = e1.contact_id AND c1.archived_at IS NULL
    JOIN contact c2 ON c2.id = e2.contact_id AND c2.archived_at IS NULL
    """
)

_NAME_PAIRS = text(
    """
    SELECT c1.id AS a, c2.id AS b,
           similarity(lower(c1.display_name), lower(c2.display_name)) AS sim
    FROM contact c1
    JOIN contact c2
      ON c1.id < c2.id
     AND lower(c1.display_name) % lower(c2.display_name)
     AND similarity(lower(c1.display_name), lower(c2.display_name)) >= :threshold
    WHERE c1.archived_at IS NULL AND c2.archived_at IS NULL
      AND (c1.company IS NULL OR c2.company IS NULL
           OR lower(c1.company) = lower(c2.company))
    """
)


def find_duplicates(session: Session, *, limit: int = 100) -> list[DuplicatePair]:
    """Likely duplicate pairs, strongest first; dismissed pairs are left out."""
    dismissed = {
        (a, b)
        for a, b in session.execute(
            select(DuplicateDismissal.contact_a, DuplicateDismissal.contact_b)
        ).all()
    }
    found: dict[tuple[int, int], tuple[list[str], float]] = {}
    for a, b, email in session.execute(_EMAIL_PAIRS).all():
        reasons, score = found.setdefault((a, b), ([], 0.0))
        reasons.append(f"same email {email}")
        found[(a, b)] = (reasons, max(score, 2.0))
    for a, b, sim in session.execute(_NAME_PAIRS, {"threshold": NAME_SIMILARITY}).all():
        reasons, score = found.setdefault((a, b), ([], 0.0))
        reasons.append("same name" if sim >= 0.999 else "similar name")
        found[(a, b)] = (reasons, score + float(sim))
    keys = sorted((k for k in found if k not in dismissed), key=lambda k: (-found[k][1], k))[:limit]
    if not keys:
        return []
    ids = {i for k in keys for i in k}
    contacts = {c.id: c for c in (get_contact(session, i) for i in sorted(ids))}
    return [
        DuplicatePair(contacts[a], contacts[b], found[(a, b)][0], found[(a, b)][1]) for a, b in keys
    ]


def dismiss_pair(session: Session, x: int, y: int) -> None:
    """Remember that these two are different people."""
    if x == y:
        raise ContactError("Pick two different contacts")
    a, b = _ordered(x, y)
    for cid in (a, b):
        if session.get(Contact, cid) is None:
            raise ContactNotFound(cid)
    session.execute(
        insert(DuplicateDismissal).values(contact_a=a, contact_b=b).on_conflict_do_nothing()
    )
    session.flush()


# ---------------------------------------------------------------- merge


def conflicts(keep: Contact, other: Contact) -> list[str]:
    """Merge fields where both contacts have a value and the values differ."""
    out = []
    for name, _label in MERGE_FIELDS:
        mine, theirs = getattr(keep, name), getattr(other, name)
        if mine not in (None, "") and theirs not in (None, "") and mine != theirs:
            out.append(name)
    return out


def _combine(mine: str | None, theirs: str | None) -> str | None:
    if not mine:
        return theirs
    if not theirs or theirs.strip() in mine:
        return mine
    return f"{mine}\n\n{theirs}"


def _pick_manager(
    session: Session, keep: Contact, other: Contact, wanted: int | None
) -> int | None:
    """The other contact's manager, unless that would point at either contact or make a cycle."""
    if wanted in (keep.id, other.id):
        return keep.manager_id
    try:
        check_manager(session, keep.id, wanted)
    except ContactError:
        return keep.manager_id
    return wanted


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def merge_contacts(
    session: Session,
    keep_id: int,
    other_id: int,
    choices: Mapping[str, Side] | None = None,
    *,
    today: date | None = None,
) -> Contact:
    """Merge ``other`` into ``keep``; returns the kept contact (C-12, ADR-0012).

    ``choices`` says, per conflicting field, whether the kept or the other
    contact's value wins (default: kept). Blank fields are filled from the other.
    """
    if keep_id == other_id:
        raise ContactError("Pick two different contacts")
    keep = get_contact(session, keep_id)
    other = get_contact(session, other_id)
    choices = choices or {}
    snapshot = contact_record(other, include_photo=False)
    other_name = other.display_name

    # Scalars: conflicts follow the user's choice; blanks are filled from the other.
    for name, _label in MERGE_FIELDS:
        mine, theirs = getattr(keep, name), getattr(other, name)
        if theirs in (None, ""):
            continue
        if mine in (None, "") or choices.get(name) == "other":
            value = theirs
            if name == "manager_id":
                value = _pick_manager(session, keep, other, theirs)
            elif name == "company":
                value = resolve_company(session, theirs)
            setattr(keep, name, value)
    if keep.manager_id == other.id:
        keep.manager_id = None
    for name in COMBINED_FIELDS:
        setattr(keep, name, _combine(getattr(keep, name), getattr(other, name)))
    keep.is_favorite = keep.is_favorite or other.is_favorite

    # Emails and phones: add what the kept contact doesn't already have.
    have = {e.email.lower() for e in keep.emails}
    for e in other.emails:
        if e.email.lower() not in have:
            keep.emails.append(ContactEmail(email=e.email, label=e.label, is_primary=False))
            have.add(e.email.lower())
    if keep.emails and not any(e.is_primary for e in keep.emails):
        keep.emails[0].is_primary = True
    numbers = {_digits(p.number) for p in keep.phones}
    for p in other.phones:
        if _digits(p.number) not in numbers:
            keep.phones.append(ContactPhone(number=p.number, label=p.label))
            numbers.add(_digits(p.number))

    # Custom fields: the kept contact wins on a name clash.
    names = {f.name.lower() for f in keep.custom_fields}
    order = len(keep.custom_fields)
    for f in other.custom_fields:
        if f.name.lower() not in names:
            keep.custom_fields.append(CustomField(name=f.name, value=f.value, sort_order=order))
            names.add(f.name.lower())
            order += 1
    session.flush()

    # Tags and list memberships (the kept contact's role note wins).
    tag_ids = [t.id for t in other.tags]
    if tag_ids:
        session.execute(
            insert(contact_tag)
            .values([{"contact_id": keep.id, "tag_id": t} for t in tag_ids])
            .on_conflict_do_nothing()
        )
    kept_lists = {m.list_id: m for m in keep.memberships}
    for m in other.memberships:
        existing = kept_lists.get(m.list_id)
        if existing is None:
            session.add(ListMember(list_id=m.list_id, contact_id=keep.id, role_note=m.role_note))
        elif not existing.role_note and m.role_note:
            existing.role_note = m.role_note

    # Activities, direct reports and the photo move across.
    session.execute(
        update(Activity).where(Activity.contact_id == other.id).values(contact_id=keep.id)
    )
    report_ids = list(
        session.scalars(
            select(Contact.id).where(Contact.manager_id == other.id, Contact.id != keep.id)
        )
    )
    if report_ids:
        session.execute(
            update(Contact).where(Contact.id.in_(report_ids)).values(manager_id=keep.id)
        )
    if keep.photo is None and other.photo is not None:
        session.execute(
            update(ContactPhoto)
            .where(ContactPhoto.contact_id == other.id)
            .values(contact_id=keep.id)
        )
    session.add(Activity(
        contact_id=keep.id,
        kind="note",
        occurred_on=today or date.today(),
        summary=f"Merged with {other_name} (a duplicate record).",
    ))  # fmt: skip
    session.add(ContactMerge(kept_id=keep.id, merged_name=other_name, snapshot=snapshot))
    keep.updated_at = datetime.now(UTC)
    session.flush()

    session.expunge(other)
    session.execute(delete(Contact).where(Contact.id == other_id))
    session.flush()
    session.expire_all()
    refresh_search(session, [keep.id, *report_ids])
    return get_contact(session, keep.id)


def merge_preview_rows(a: Contact, b: Contact) -> list[dict[str, Any]]:
    """Rows for the side-by-side merge page: every field where either has a value."""
    rows = []
    for name, label in MERGE_FIELDS:
        va, vb = getattr(a, name), getattr(b, name)
        if va in (None, "") and vb in (None, ""):
            continue
        rows.append(
            {
                "name": name,
                "label": label,
                "a": _display(a, name),
                "b": _display(b, name),
                "conflict": va not in (None, "") and vb not in (None, "") and va != vb,
            }
        )
    return rows


def _display(contact: Contact, name: str) -> str:
    if name == "contact_type_id":
        return contact.contact_type.name
    if name == "manager_id":
        return contact.manager.display_name if contact.manager else ""
    value = getattr(contact, name)
    return "" if value is None else str(value)


def merged_counts(a: Contact, b: Contact) -> dict[str, int]:
    """How many emails, phones, tags, lists and activities the merged contact will have."""
    return {
        "emails": len({e.email.lower() for e in [*a.emails, *b.emails]}),
        "phones": len({_digits(p.number) for p in [*a.phones, *b.phones]}),
        "tags": len({t.id for t in [*a.tags, *b.tags]}),
        "lists": len({m.list_id for m in [*a.memberships, *b.memberships]}),
        "activities": len(a.activities) + len(b.activities),
        "fields": len({f.name.lower() for f in [*a.custom_fields, *b.custom_fields]}),
    }


def merge_history(session: Session, contact_id: int) -> Sequence[ContactMerge]:
    return session.scalars(
        select(ContactMerge)
        .where(ContactMerge.kept_id == contact_id)
        .order_by(ContactMerge.merged_at.desc())
    ).all()
