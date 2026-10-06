"""Contact business logic (C-01 to C-08). Routes stay thin and call these functions."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, selectinload

from app.addresses import normalize_address
from app.geo import place_of
from app.links import contact_teams_url, mailto_url, slack_handle_display, tel_url
from app.links import normalize_phone as _normalize_phone
from app.models import (
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
    ContactType,
    CustomField,
    ListMember,
)
from app.privacy import presenting, redact
from app.schemas import (
    AddressIn,
    ContactCreate,
    ContactLinks,
    ContactOut,
    ContactUpdate,
    CustomFieldIn,
    EmailIn,
    PhoneIn,
)
from app.search import refresh_search

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
        selectinload(Contact.addresses),
        selectinload(Contact.manager),
        selectinload(Contact.reports),
        selectinload(Contact.tags),
        selectinload(Contact.photo),
        selectinload(Contact.memberships).selectinload(ListMember.contact_list),
        selectinload(Contact.custom_fields),
        selectinload(Contact.activities),
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


def check_manager(session: Session, contact_id: int | None, manager_id: int | None) -> None:
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


# ---------------------------------------------------------------- reuse existing spellings (C-25)

# (value column, owning contact's id column) for the free-text fields that suggest and reuse values.
_Column = tuple[InstrumentedAttribute[str | None], InstrumentedAttribute[int | None]]
_SPELLED_FIELDS: tuple[str, ...] = ("team", "department", "location")
_LABEL_COLUMNS: tuple[_Column, ...] = (
    (ContactEmail.label, ContactEmail.contact_id),
    (ContactPhone.label, ContactPhone.contact_id),
    (ContactAddress.label, ContactAddress.contact_id),
)
MAX_SUGGESTIONS = 500


def _tidy(text: str | None) -> str:
    return " ".join((text or "").split())


def _best_spelling(counts: Counter[str]) -> str:
    """The most used spelling; ties go to the alphabetically first."""
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def resolve_spelling(
    session: Session, columns: Sequence[_Column], raw: str | None, exclude_id: int | None = None
) -> str | None:
    """C-25: reuse an existing spelling when the value matches ignoring case and spaces.

    ``exclude_id`` leaves one contact's own rows out, so fixing the case of a value nobody
    else uses still works."""
    name = _tidy(raw)
    if not name:
        return None
    counts: Counter[str] = Counter()
    for column, owner in columns:
        stmt = (
            select(column, func.count()).where(func.lower(column) == name.lower()).group_by(column)
        )
        if exclude_id is not None:
            stmt = stmt.where(owner != exclude_id)
        for value, uses in session.execute(stmt):
            counts[value] += uses
    return _best_spelling(counts) if counts else name


class _Spellings:
    """Spellings to reuse while one contact is saved: scalar fields and email/phone/address types.

    A type spelled one way earlier in the same save is reused for the later rows."""

    def __init__(self, session: Session, exclude_id: int | None = None) -> None:
        self.session = session
        self.exclude_id = exclude_id
        self._labels: dict[str, str | None] = {}

    def field(self, name: str, raw: str | None) -> str | None:
        column = getattr(Contact, name)
        return resolve_spelling(self.session, [(column, Contact.id)], raw, self.exclude_id)

    def label(self, raw: str | None) -> str | None:
        name = _tidy(raw)
        if not name:
            return None
        key = name.lower()
        if key not in self._labels:
            self._labels[key] = resolve_spelling(
                self.session, _LABEL_COLUMNS, name, self.exclude_id
            )
        return self._labels[key]

    def emails(self, items: list[EmailIn]) -> list[EmailIn]:
        return [e.model_copy(update={"label": self.label(e.label)}) for e in items]

    def phones(self, items: list[PhoneIn]) -> list[PhoneIn]:
        return [p.model_copy(update={"label": self.label(p.label)}) for p in items]

    def addresses(self, items: list[AddressIn]) -> list[AddressIn]:
        return [a.model_copy(update={"label": self.label(a.label)}) for a in items]


def _usage(session: Session, columns: Sequence[_Column]) -> dict[str, Counter[str]]:
    """Spellings in use, grouped by their case- and space-folded form."""
    folded: dict[str, Counter[str]] = defaultdict(Counter)
    for column, _owner in columns:
        rows = session.execute(
            select(column, func.count()).where(column.is_not(None)).group_by(column)
        )
        for value, uses in rows:
            text = _tidy(value)
            if text:
                folded[text.lower()][text] += uses
    return folded


def field_suggestions(session: Session) -> dict[str, list[str]]:
    """C-25: values in use, for the form's suggestion lists (Team, Department, Location and the
    shared email/phone/address type). Presenting mode applies: the session already withholds
    private contacts and personal-label rows, Location is left out when it is hidden, and
    "names and companies only" offers nothing."""
    out: dict[str, list[str]] = {"team": [], "department": [], "location": [], "label": []}
    p = presenting()
    if p is not None and p.names_only:
        return out
    for name in _SPELLED_FIELDS:
        if name == "location" and p is not None and p.hides("location"):
            continue
        usage = _usage(session, [(getattr(Contact, name), Contact.id)])
        out[name] = [_best_spelling(usage[key]) for key in sorted(usage)][:MAX_SUGGESTIONS]
    labels = _usage(session, _LABEL_COLUMNS)
    ranked = sorted(labels, key=lambda key: (-sum(labels[key].values()), key))
    out["label"] = [_best_spelling(labels[key]) for key in ranked][:MAX_SUGGESTIONS]
    return out


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


def address_row(item: AddressIn, region: str) -> ContactAddress:
    """C-19: an address as stored, with country and region normalised (ADR-0021)."""
    norm = normalize_address(
        street=item.street,
        city=item.city,
        region=item.region,
        postal_code=item.postal_code,
        country=item.country,
        home_region=region,
    )
    row = ContactAddress(label=item.label, **vars(norm))
    place_address(row)
    return row


def place_address(row: ContactAddress) -> None:
    """C-22: coordinates, time zone and precision from offline data (ADR-0023)."""
    found = place_of(
        city=row.city, region=row.region, postal_code=row.postal_code, country_code=row.country_code
    )
    row.latitude = found.latitude if found else None
    row.longitude = found.longitude if found else None
    row.time_zone = found.time_zone if found else None
    row.place_precision = found.precision if found else "none"


def place_missing(session: Session, limit: int = 5000) -> int:
    """C-22: look up addresses saved before places existed (start-up; cheap when done)."""
    rows = session.scalars(
        select(ContactAddress).where(ContactAddress.place_precision.is_(None)).limit(limit)
    ).all()
    for row in rows:
        place_address(row)
    session.flush()
    return len(rows)


def _apply_addresses(contact: Contact, addresses: list[AddressIn], region: str) -> None:
    contact.addresses = [address_row(a, region) for a in addresses]


def _apply_custom_fields(session: Session, contact: Contact, fields: list[CustomFieldIn]) -> None:
    """C-11: replace the fields, reusing rows by name so the unique index never sees a clash."""
    wanted = {f.name.lower() for f in fields}
    for row in list(contact.custom_fields):
        if row.name.lower() not in wanted:
            contact.custom_fields.remove(row)
    session.flush()
    existing = {row.name.lower(): row for row in contact.custom_fields}
    for order, item in enumerate(fields):
        match = existing.get(item.name.lower())
        if match is None:
            contact.custom_fields.append(
                CustomField(name=item.name, value=item.value, sort_order=order)
            )
        else:
            match.name, match.value, match.sort_order = item.name, item.value, order


def custom_field_names(session: Session) -> list[str]:
    """Field names already in use, most used first (suggestions in the form)."""
    rows = session.execute(
        select(func.min(CustomField.name))
        .group_by(func.lower(CustomField.name))
        .order_by(func.count().desc(), func.lower(func.min(CustomField.name)))
        .limit(100)
    ).scalars()
    return list(rows)


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
    "linkedin_url",
    "pronunciation",
    "birthday",  # C-20
    "is_favorite",
)


# ---------------------------------------------------------------- companies (C-14)


def list_companies(session: Session) -> list[str]:
    """Distinct company names in use, alphabetically (for the company dropdown)."""
    rows = session.scalars(
        select(Contact.company)
        .where(Contact.company.is_not(None))
        .group_by(Contact.company)
        .order_by(func.lower(Contact.company))
    ).all()
    return [r for r in rows if r]


def resolve_company(session: Session, raw: str | None) -> str | None:
    """Reuse an existing spelling when the name matches ignoring case (C-14)."""
    name = " ".join((raw or "").split())
    if not name:
        return None
    existing = session.scalars(
        select(Contact.company)
        .where(func.lower(Contact.company) == name.lower())
        .group_by(Contact.company)
        .order_by(func.count().desc())
    ).first()
    return existing or name


def home_company(session: Session, configured: str | None = None) -> str | None:
    """Default company for new employees: HOME_COMPANY, else the most common one among
    contacts whose type is named "Employee" (C-14, ADR-0009)."""
    if configured:
        return resolve_company(session, configured)
    return session.scalars(
        select(Contact.company)
        .join(ContactType, ContactType.id == Contact.contact_type_id)
        .where(func.lower(ContactType.name) == "employee", Contact.company.is_not(None))
        .group_by(Contact.company)
        .order_by(func.count().desc(), func.lower(Contact.company))
    ).first()


def employee_type_id(session: Session) -> int | None:
    return session.scalar(select(ContactType.id).where(func.lower(ContactType.name) == "employee"))


# ---------------------------------------------------------------- writes (continued)


def create_contact(
    session: Session, data: ContactCreate, *, phone_region: str = "US", bulk: bool = False
) -> Contact:
    """Create a contact. ``bulk=True`` (imports) skips the reload and the search refresh;
    the caller must call ``refresh_search`` for the new ids afterwards."""
    _check_contact_type(session, data.contact_type_id)
    check_manager(session, None, data.manager_id)
    contact = Contact(**{f: getattr(data, f) for f in _SCALAR_FIELDS})
    contact.company = resolve_company(session, data.company)
    spelled = _Spellings(session)
    for name in _SPELLED_FIELDS:
        setattr(contact, name, spelled.field(name, getattr(data, name)))
    session.add(contact)
    session.flush()
    _apply_emails(session, contact, spelled.emails(data.emails))
    _apply_phones(contact, spelled.phones(data.phones), phone_region)
    _apply_addresses(contact, spelled.addresses(data.addresses), phone_region)
    if data.custom_fields:
        _apply_custom_fields(session, contact, data.custom_fields)
    session.flush()
    if bulk:
        return contact
    refresh_search(session, [contact.id])
    return get_contact(session, contact.id)


def update_contact(
    session: Session, contact: Contact, data: ContactUpdate, *, phone_region: str = "US"
) -> Contact:
    sent = data.model_fields_set
    if "contact_type_id" in sent and data.contact_type_id is not None:
        _check_contact_type(session, data.contact_type_id)
    if "manager_id" in sent:
        check_manager(session, contact.id, data.manager_id)
    renamed = "display_name" in sent and data.display_name != contact.display_name
    for field in _SCALAR_FIELDS:
        if field in sent:
            setattr(contact, field, getattr(data, field))
    if "company" in sent:
        contact.company = resolve_company(session, data.company)
    spelled = _Spellings(session, exclude_id=contact.id)
    for name in _SPELLED_FIELDS:
        if name in sent:
            setattr(contact, name, spelled.field(name, getattr(data, name)))
    if data.emails is not None:
        _apply_emails(session, contact, spelled.emails(data.emails))
    if data.phones is not None:
        _apply_phones(contact, spelled.phones(data.phones), phone_region)
    if data.addresses is not None:
        _apply_addresses(contact, spelled.addresses(data.addresses), phone_region)
    if data.custom_fields is not None:
        _apply_custom_fields(session, contact, data.custom_fields)
    contact.updated_at = datetime.now(UTC)
    session.flush()
    # Reports carry their manager's name in their search document (S-01).
    report_ids = [r.id for r in contact.reports] if renamed else []
    refresh_search(session, [contact.id, *report_ids])
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


def slack_for_copy(contact: Contact) -> str:
    """M-07: the handle to copy, with its "@" ("" when none, or while presenting names only)."""
    p = presenting()
    if p is not None and p.names_only:
        return ""
    return slack_handle_display(contact.slack_handle) or ""


def contact_links(contact: Contact) -> ContactLinks:
    """M-04 / ADR-0007: email, Teams, Slack and phone actions for a card."""
    email = primary_email(contact)
    return ContactLinks(
        mailto=mailto_url([email]) if email else None,
        teams=contact_teams_url(contact.teams_url, email),
        slack=contact.slack_url,
        tel=tel_url(contact.phones[0].number) if contact.phones else None,
    )


def last_contact(contact: Contact) -> date | None:
    """C-13: date of the newest interaction (notes don't count)."""
    return max((a.occurred_on for a in contact.activities if a.kind != "note"), default=None)


def to_out(contact: Contact, *, detail: bool = False) -> ContactOut:
    """``detail=True`` adds custom fields and activities (card and single-contact API)."""
    extra: dict[str, Any] = {}
    if detail:
        extra = {
            "custom_fields": contact.custom_fields,
            "activities": contact.activities,
            "last_contact": last_contact(contact),
        }
    data: dict[str, Any] = {
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
        "addresses": contact.addresses,
        "tags": contact.tags,
        "lists": sorted(
            (
                m.contact_list
                for m in contact.memberships
                # None: a private list withheld while presenting (app.privacy)
                if m.contact_list is not None and m.contact_list.status == "active"
            ),
            key=lambda cl: cl.name.lower(),
        ),
        "links": contact_links(contact),
        "archived": contact.archived_at is not None,
        "has_photo": contact.photo is not None,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
        **extra,
    }
    p = presenting()
    if p is not None:
        data = redact(data, p)  # P-02: only the public fields leave the server
    return ContactOut.model_validate(data)


__all__ = [
    "SORT_KEYS",
    "ContactError",
    "ContactNotFound",
    "SortKey",
    "address_row",
    "archive_contact",
    "contact_links",
    "create_contact",
    "custom_field_names",
    "field_suggestions",
    "get_contact",
    "last_contact",
    "list_contact_types",
    "list_contacts",
    "lookup_contacts",
    "place_address",
    "place_missing",
    "primary_email",
    "restore_contact",
    "slack_for_copy",
    "slack_handle_display",
    "to_out",
    "update_contact",
]
