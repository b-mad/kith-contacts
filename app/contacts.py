"""Contact business logic (C-01 to C-08). Routes stay thin and call these functions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.links import contact_teams_url, mailto_url, slack_handle_display, tel_url
from app.links import normalize_phone as _normalize_phone
from app.models import Contact, ContactEmail, ContactPhone, ContactType
from app.schemas import (
    ContactCreate,
    ContactLinks,
    ContactOut,
    ContactUpdate,
    EmailIn,
    PhoneIn,
)

SortKey = Literal["name", "company", "team", "type", "updated"]
SORT_KEYS: tuple[SortKey, ...] = ("name", "company", "team", "type", "updated")
MAX_MANAGER_DEPTH = 100


class ContactError(ValueError):
    """A rule violation the user can fix; ``field`` names the offending input."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class ContactNotFound(LookupError):
    pass


# ---------------------------------------------------------------- queries


def _with_details(stmt: Select[tuple[Contact]]) -> Select[tuple[Contact]]:
    return stmt.options(
        selectinload(Contact.contact_type),
        selectinload(Contact.emails),
        selectinload(Contact.phones),
        selectinload(Contact.manager),
        selectinload(Contact.reports),
    )


def get_contact(session: Session, contact_id: int) -> Contact:
    contact = session.scalars(
        _with_details(select(Contact).where(Contact.id == contact_id))
    ).one_or_none()
    if contact is None:
        raise ContactNotFound(contact_id)
    return contact


def list_contact_types(session: Session) -> Sequence[ContactType]:
    return session.scalars(
        select(ContactType).order_by(ContactType.sort_order, ContactType.name)
    ).all()


def list_contacts(
    session: Session,
    *,
    contact_type_id: int | None = None,
    sort: SortKey = "name",
    include_archived: bool = False,
    limit: int = 500,
) -> Sequence[Contact]:
    stmt = _with_details(select(Contact))
    if not include_archived:
        stmt = stmt.where(Contact.archived_at.is_(None))
    if contact_type_id is not None:
        stmt = stmt.where(Contact.contact_type_id == contact_type_id)
    name = func.lower(Contact.display_name)
    orders: dict[str, list[Any]] = {
        "name": [name],
        "company": [func.lower(Contact.company).nulls_last(), name],
        "team": [func.lower(Contact.team).nulls_last(), name],
        "type": [Contact.contact_type_id, name],
        "updated": [Contact.updated_at.desc(), name],
    }
    return session.scalars(stmt.order_by(*orders[sort]).limit(limit)).all()


def lookup_contacts(
    session: Session, query: str, *, exclude_id: int | None = None, limit: int = 10
) -> Sequence[Contact]:
    """Name/company/team prefix-or-substring match for the manager picker (C-07).

    Full context search with ranking arrives in Phase 2 (S-01 to S-05).
    """
    term = query.strip()
    if not term:
        return []
    pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    stmt = (
        select(Contact)
        .where(Contact.archived_at.is_(None))
        .where(
            or_(
                Contact.display_name.ilike(pattern),
                Contact.company.ilike(pattern),
                Contact.team.ilike(pattern),
            )
        )
        .order_by(
            func.lower(Contact.display_name).startswith(term.lower()).desc(),
            func.lower(Contact.display_name),
        )
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Contact.id != exclude_id)
    return session.scalars(stmt).all()


# ---------------------------------------------------------------- validation


def _check_contact_type(session: Session, contact_type_id: int) -> None:
    if session.get(ContactType, contact_type_id) is None:
        raise ContactError("Unknown contact type", "contact_type_id")


def _check_manager(session: Session, contact_id: int | None, manager_id: int | None) -> None:
    """C-07: manager must exist and must not create a reporting cycle."""
    if manager_id is None:
        return
    if contact_id is not None and manager_id == contact_id:
        raise ContactError("A contact cannot be their own manager", "manager_id")
    current: int | None = manager_id
    for _ in range(MAX_MANAGER_DEPTH):
        if current is None:
            return
        row = session.execute(
            select(Contact.id, Contact.manager_id).where(Contact.id == current)
        ).one_or_none()
        if row is None:
            if current == manager_id:
                raise ContactError("Manager not found", "manager_id")
            return  # pragma: no cover - FK guarantees parents exist
        if contact_id is not None and row.manager_id == contact_id:
            raise ContactError(
                "This manager reports (directly or indirectly) to this contact, "
                "so it would create a reporting cycle",
                "manager_id",
            )
        current = row.manager_id
    raise ContactError("Reporting chain is too deep", "manager_id")  # pragma: no cover


# ---------------------------------------------------------------- writes


def _apply_emails(session: Session, contact: Contact, emails: list[EmailIn]) -> None:
    """Replace the email list, reusing rows so unique indexes never see transient duplicates."""
    wanted = {str(e.email).lower(): e for e in emails}
    for row in list(contact.emails):
        if row.email.lower() not in wanted:
            contact.emails.remove(row)
        row.is_primary = False
    session.flush()  # deletes and primary resets first (uq_contact_email_one_primary)

    existing = {row.email.lower(): row for row in contact.emails}
    for item in emails:
        match = existing.get(str(item.email).lower())
        if match is None:
            contact.emails.append(ContactEmail(email=str(item.email), label=item.label))
        else:
            match.email = str(item.email)
            match.label = item.label
    session.flush()
    for item in emails:
        if item.is_primary:
            key = str(item.email).lower()
            next(r for r in contact.emails if r.email.lower() == key).is_primary = True


def _apply_phones(contact: Contact, phones: list[PhoneIn], region: str) -> None:
    contact.phones = [
        ContactPhone(number=_normalize_phone(p.number, region), label=p.label) for p in phones
    ]


_SCALAR_FIELDS = (
    "display_name",
    "first_name",
    "last_name",
    "nickname",
    "contact_type_id",
    "company",
    "title",
    "team",
    "department",
    "location",
    "manager_id",
    "works_on",
    "notes",
    "slack_handle",
    "slack_url",
    "teams_url",
    "pronunciation",
    "is_favorite",
)


def create_contact(session: Session, data: ContactCreate, *, phone_region: str = "US") -> Contact:
    _check_contact_type(session, data.contact_type_id)
    _check_manager(session, None, data.manager_id)
    contact = Contact(**{f: getattr(data, f) for f in _SCALAR_FIELDS})
    session.add(contact)
    session.flush()
    _apply_emails(session, contact, data.emails)
    _apply_phones(contact, data.phones, phone_region)
    session.flush()
    return get_contact(session, contact.id)


def update_contact(
    session: Session, contact: Contact, data: ContactUpdate, *, phone_region: str = "US"
) -> Contact:
    sent = data.model_fields_set
    if "contact_type_id" in sent and data.contact_type_id is not None:
        _check_contact_type(session, data.contact_type_id)
    if "manager_id" in sent:
        _check_manager(session, contact.id, data.manager_id)
    for field in _SCALAR_FIELDS:
        if field in sent:
            setattr(contact, field, getattr(data, field))
    if data.emails is not None:
        _apply_emails(session, contact, data.emails)
    if data.phones is not None:
        _apply_phones(contact, data.phones, phone_region)
    contact.updated_at = datetime.now(UTC)
    session.flush()
    session.expire(contact)
    return get_contact(session, contact.id)


def archive_contact(session: Session, contact: Contact) -> Contact:
    """C-01: archive instead of delete; reports keep their manager link."""
    if contact.archived_at is None:
        contact.archived_at = datetime.now(UTC)
        session.flush()
    return contact


def restore_contact(session: Session, contact: Contact) -> Contact:
    contact.archived_at = None
    session.flush()
    return contact


# ---------------------------------------------------------------- presentation


def primary_email(contact: Contact) -> str | None:
    for row in contact.emails:
        if row.is_primary:
            return row.email
    return contact.emails[0].email if contact.emails else None


def contact_links(contact: Contact) -> ContactLinks:
    """M-04 / ADR-0007: email, Teams, Slack and phone actions for a card."""
    email = primary_email(contact)
    return ContactLinks(
        mailto=mailto_url([email]) if email else None,
        teams=contact_teams_url(contact.teams_url, email),
        slack=contact.slack_url,
        tel=tel_url(contact.phones[0].number) if contact.phones else None,
    )


def to_out(contact: Contact) -> ContactOut:
    return ContactOut.model_validate(
        {
            **{
                f: getattr(contact, f)
                for f in _SCALAR_FIELDS
                if f not in {"manager_id", "contact_type_id"}
            },
            "id": contact.id,
            "contact_type": contact.contact_type,
            "manager": contact.manager,
            "reports": sorted(
                (r for r in contact.reports if r.archived_at is None),
                key=lambda r: r.display_name.lower(),
            ),
            "emails": sorted(contact.emails, key=lambda e: (not e.is_primary, e.id or 0)),
            "phones": contact.phones,
            "links": contact_links(contact),
            "archived": contact.archived_at is not None,
            "created_at": contact.created_at,
            "updated_at": contact.updated_at,
        }
    )


__all__ = [
    "SORT_KEYS",
    "ContactError",
    "ContactNotFound",
    "SortKey",
    "archive_contact",
    "contact_links",
    "create_contact",
    "get_contact",
    "list_contact_types",
    "list_contacts",
    "lookup_contacts",
    "primary_email",
    "restore_contact",
    "slack_handle_display",
    "to_out",
    "update_contact",
]
