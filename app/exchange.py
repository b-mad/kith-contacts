"""Export (D-03) and import (D-01, D-02) of contacts.

Exports: CSV (one row per contact), JSON (lossless, ``format: contacts-app/1``)
and vCard. Imports: CSV with column mapping, or vCard; both go through
``plan_import`` (preview, duplicates, errors) and ``run_import``.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.contacts import ContactError, check_manager, create_contact, resolve_company
from app.lists import add_members, find_or_create_list
from app.models import Contact, ContactEmail, ContactList, ContactType, ListMember, Tag
from app.schemas import ContactCreate
from app.search import refresh_search
from app.tags import add_tag
from app.vcard import ParsedCard

FORMAT = "contacts-app/1"
MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _all_contacts(session: Session) -> list[Contact]:
    return list(
        session.scalars(
            select(Contact)
            .options(
                selectinload(Contact.contact_type),
                selectinload(Contact.emails),
                selectinload(Contact.phones),
                selectinload(Contact.manager),
                selectinload(Contact.tags),
                selectinload(Contact.memberships).selectinload(ListMember.contact_list),
            )
            .order_by(func.lower(Contact.display_name), Contact.id)
            .execution_options(populate_existing=True)  # always export what is stored now
        ).all()
    )


# ---------------------------------------------------------------- export (D-03)


def export_json(session: Session, instance_name: str) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    contacts = _all_contacts(session)
    return {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(),
        "instance": instance_name,
        "contact_types": [
            {"name": t.name, "sort_order": t.sort_order}
            for t in session.scalars(select(ContactType).order_by(ContactType.sort_order))
        ],
        "tags": [
            {"name": t.name, "color": t.color}
            for t in session.scalars(select(Tag).order_by(Tag.name))
        ],
        "lists": [
            {"name": cl.name, "description": cl.description, "status": cl.status}
            for cl in session.scalars(select(ContactList).order_by(ContactList.name))
        ],
        "contacts": [
            {
                "id": c.id,
                "display_name": c.display_name,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "nickname": c.nickname,
                "type": c.contact_type.name,
                "company": c.company,
                "title": c.title,
                "team": c.team,
                "department": c.department,
                "location": c.location,
                "manager_id": c.manager_id,
                "manager": c.manager.display_name if c.manager else None,
                "works_on": c.works_on,
                "notes": c.notes,
                "slack_handle": c.slack_handle,
                "slack_url": c.slack_url,
                "teams_url": c.teams_url,
                "pronunciation": c.pronunciation,
                "is_favorite": c.is_favorite,
                "archived_at": iso(c.archived_at),
                "created_at": iso(c.created_at),
                "updated_at": iso(c.updated_at),
                "emails": [
                    {"email": e.email, "label": e.label, "is_primary": e.is_primary}
                    for e in c.emails
                ],
                "phones": [{"number": p.number, "label": p.label} for p in c.phones],
                "tags": [t.name for t in c.tags],
                "lists": [
                    {"name": m.contact_list.name, "role_note": m.role_note} for m in c.memberships
                ],
            }
            for c in contacts
        ],
    }


CSV_COLUMNS = [
    "display_name", "first_name", "last_name", "nickname", "type", "company", "title", "team",
    "department", "location", "manager", "primary_email", "emails", "phones", "slack_handle",
    "slack_url", "teams_url", "works_on", "notes", "tags", "lists", "favorite", "archived",
]  # fmt: skip

_FORMULA = re.compile(r"^[=@\t\r]|^[+-](?!\d)")


def _cell(value: object) -> str:
    """CSV-injection guard: a spreadsheet must never run a cell as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if _FORMULA.match(text) else text


def export_csv(session: Session) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for c in _all_contacts(session):
        primary = next((e.email for e in c.emails if e.is_primary), "")
        writer.writerow(
            [
                _cell(v)
                for v in (
                    c.display_name,
                    c.first_name,
                    c.last_name,
                    c.nickname,
                    c.contact_type.name,
                    c.company,
                    c.title,
                    c.team,
                    c.department,
                    c.location,
                    c.manager.display_name if c.manager else "",
                    primary,
                    "; ".join(e.email for e in c.emails),
                    "; ".join(f"{p.number} ({p.label})" if p.label else p.number for p in c.phones),
                    c.slack_handle,
                    c.slack_url,
                    c.teams_url,
                    c.works_on,
                    c.notes,
                    "; ".join(t.name for t in c.tags),
                    "; ".join(m.contact_list.name for m in c.memberships),
                    "yes" if c.is_favorite else "",
                    "yes" if c.archived_at else "",
                )
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------- import: reading CSV (D-01)

# Target fields and header spellings seen in Outlook, Google and hand-made CSVs.
FIELDS: dict[str, tuple[str, ...]] = {
    "display_name": ("name", "fullname", "displayname", "contact", "contactname"),
    "first_name": ("firstname", "givenname", "first"),
    "last_name": ("lastname", "familyname", "surname", "last"),
    "nickname": ("nickname",),
    "email": ("email", "emailaddress", "email1", "email1value", "primaryemail", "workemail"),
    "email2": ("email2", "email2address", "email2value", "personalemail", "otheremail"),
    "email3": ("email3", "email3address", "email3value"),
    "phone": ("phone", "mobilephone", "mobile", "cell", "cellphone", "phone1value", "telephone",
              "primaryphone", "phonenumber"),
    "phone2": ("businessphone", "workphone", "phone2value", "businessphone2", "officephone"),
    "phone3": ("homephone", "phone3value", "otherphone"),
    "company": ("company", "organization", "organisation", "organization1name", "employer",
                "companyname"),
    "title": ("title", "jobtitle", "organization1title", "position", "role"),
    "department": ("department", "organization1department", "dept"),
    "team": ("team", "group", "squad"),
    "location": ("location", "city", "officelocation", "businesscity", "office"),
    "manager": ("manager", "managername", "reportsto", "managersname", "supervisor"),
    "works_on": ("workson", "projects", "responsibilities", "focus"),
    "notes": ("notes", "note", "comments", "description"),
    "tags": ("tags", "categories", "labels", "groupmembership"),
    "type": ("type", "contacttype", "relationship", "category"),
    "slack_handle": ("slack", "slackhandle", "slackusername"),
}  # fmt: skip

FIELD_LABELS = {
    "display_name": "Display name", "first_name": "First name", "last_name": "Last name",
    "nickname": "Nickname", "email": "Email", "email2": "Email 2", "email3": "Email 3",
    "phone": "Phone", "phone2": "Phone 2", "phone3": "Phone 3", "company": "Company",
    "title": "Title", "department": "Department", "team": "Team", "location": "Location",
    "manager": "Manager (name)", "works_on": "Works on", "notes": "Notes", "tags": "Tags",
    "type": "Type", "slack_handle": "Slack handle",
}  # fmt: skip


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def guess_mapping(headers: Sequence[str]) -> dict[int, str]:
    """Column index -> target field, first match wins; unrecognised columns are ignored."""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for index, header in enumerate(headers):
        key = _norm(header)
        for target, spellings in FIELDS.items():
            if target not in used and key in spellings:
                mapping[index] = target
                used.add(target)
                break
    return mapping


def read_csv(data: bytes) -> tuple[list[str], list[list[str]]]:
    if len(data) > MAX_IMPORT_BYTES:
        raise ContactError("File is larger than 5 MB", "file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in row)]
    if not rows:
        raise ContactError("The file has no rows", "file")
    headers, body = rows[0], rows[1:]
    if len(body) > MAX_IMPORT_ROWS:
        raise ContactError(f"At most {MAX_IMPORT_ROWS} rows can be imported at once", "file")
    return [h.strip() for h in headers], body


def rows_from_csv(body: Sequence[Sequence[str]], mapping: dict[int, str]) -> list[dict[str, str]]:
    records = []
    for row in body:
        record: dict[str, str] = {}
        for index, target in mapping.items():
            if index < len(row) and row[index].strip():
                record[target] = row[index].strip()
        records.append(record)
    return records


def rows_from_vcards(cards: Sequence[ParsedCard]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for card in cards:
        record: dict[str, Any] = {
            k: v
            for k, v in {
                "display_name": card.display_name,
                "first_name": card.first_name,
                "last_name": card.last_name,
                "nickname": card.nickname,
                "company": card.company,
                "department": card.department,
                "title": card.title,
                "notes": card.notes,
                "tags": "; ".join(card.tags),
            }.items()
            if v
        }
        record["_emails"] = card.emails
        record["_phones"] = card.phones
        records.append(record)
    return records


# ---------------------------------------------------------------- import: planning


@dataclass
class PlannedRow:
    number: int  # 1-based row number in the file
    data: dict[str, Any] = field(default_factory=dict)  # ContactCreate input
    manager_name: str | None = None
    tags: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duplicate_of: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


_TAG_SPLIT = re.compile(r"\s*(?:;|,|:::)\s*")


def _split_tags(raw: str) -> list[str]:
    tags = []
    for part in _TAG_SPLIT.split(raw):
        name = part.strip().lstrip("*").strip()
        if name and name.lower() not in {"mycontacts", "starred"}:
            tags.append(name)
    return tags


def plan_import(
    session: Session, records: Sequence[dict[str, Any]], default_type_id: int
) -> list[PlannedRow]:
    """Validate rows and flag duplicates (same email, or same name + company)."""
    types = {t.name.lower(): t.id for t in session.scalars(select(ContactType))}
    known_emails = {e.lower() for e in session.scalars(select(ContactEmail.email))}
    known_people = {
        (n.lower(), (c or "").lower())
        for n, c in session.execute(select(Contact.display_name, Contact.company)).all()
    }
    planned: list[PlannedRow] = []
    for number, record in enumerate(records, start=1):
        row = PlannedRow(number=number)
        name = record.get("display_name") or " ".join(
            p for p in (record.get("first_name"), record.get("last_name")) if p
        )
        emails = list(record.get("_emails", []))
        for key in ("email", "email2", "email3"):
            if record.get(key):
                emails.append((record[key], "work" if key == "email" else "", key == "email"))
        if not name and emails:
            name = emails[0][0].split("@")[0]
        phones = list(record.get("_phones", []))
        for key, label in (("phone", ""), ("phone2", "work"), ("phone3", "home")):
            if record.get(key):
                phones.append((record[key], label))
        type_name = (record.get("type") or "").lower()
        data: dict[str, Any] = {
            "display_name": name,
            "contact_type_id": types.get(type_name, default_type_id),
            **{
                k: record[k]
                for k in (
                    "first_name",
                    "last_name",
                    "nickname",
                    "company",
                    "title",
                    "team",
                    "department",
                    "location",
                    "works_on",
                    "notes",
                    "slack_handle",
                )
                if record.get(k)
            },
            "emails": [],
            "phones": [{"number": n, "label": label or None} for n, label in phones],
        }
        seen: set[str] = set()
        primary_set = False
        for email, label, pref in emails:
            key = email.strip().lower()
            if key and key not in seen:
                seen.add(key)
                primary = pref and not primary_set
                primary_set = primary_set or primary
                data["emails"].append(
                    {"email": email.strip(), "label": label or None, "is_primary": primary}
                )
        row.data = data
        row.manager_name = record.get("manager")
        row.tags = _split_tags(record.get("tags", ""))
        try:
            ContactCreate.model_validate(data)
        except ValidationError as exc:
            row.errors = [
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg'].removeprefix('Value error, ')}"
                if e["loc"]
                else e["msg"].removeprefix("Value error, ")
                for e in exc.errors()
            ]
        dup_email = next((e for e in seen if e in known_emails), None)
        person = (name.lower(), (data.get("company") or "").lower())
        if dup_email:
            row.duplicate_of = f"email {dup_email} already exists"
        elif name and person in known_people:
            row.duplicate_of = "same name and company already exists"
        known_emails |= seen
        if name:
            known_people.add(person)
        planned.append(row)
    return planned


@dataclass
class ImportResult:
    created: list[int] = field(default_factory=list)
    skipped_duplicates: int = 0
    skipped_errors: int = 0
    managers_linked: int = 0
    list_id: int | None = None


def run_import(
    session: Session,
    planned: Sequence[PlannedRow],
    *,
    include_duplicates: bool = False,
    list_name: str | None = None,
    phone_region: str = "US",
) -> ImportResult:
    """Create contacts; then link managers by name; optionally put them all in a list."""
    result = ImportResult()
    pending_managers: list[tuple[int, str]] = []
    tagged: dict[str, list[int]] = {}  # lower-cased tag -> contact ids
    spelling: dict[str, str] = {}  # lower-cased tag -> first spelling seen
    for row in planned:
        if not row.ok:
            result.skipped_errors += 1
            continue
        if row.duplicate_of and not include_duplicates:
            result.skipped_duplicates += 1
            continue
        data = dict(row.data)
        data["company"] = resolve_company(session, data.get("company"))
        # Bulk path: no per-row reload or search refresh; both happen once at the end.
        contact = create_contact(
            session, ContactCreate.model_validate(data), phone_region=phone_region, bulk=True
        )
        result.created.append(contact.id)
        for tag in row.tags:
            tagged.setdefault(tag.lower(), []).append(contact.id)
            spelling.setdefault(tag.lower(), tag)
        if row.manager_name:
            pending_managers.append((contact.id, row.manager_name))

    for key, ids in tagged.items():  # one call per tag, not per contact
        add_tag(session, ids, spelling[key])

    if pending_managers:
        by_name: dict[str, list[int]] = {}
        for cid, name in session.execute(select(Contact.id, Contact.display_name)).all():
            by_name.setdefault(name.lower(), []).append(cid)
        for contact_id, manager_name in pending_managers:
            matches = [m for m in by_name.get(manager_name.lower(), []) if m != contact_id]
            if len(matches) == 1:
                try:
                    check_manager(session, contact_id, matches[0])
                except ContactError:
                    continue  # would create a cycle: leave unlinked
                session.execute(
                    update(Contact).where(Contact.id == contact_id).values(manager_id=matches[0])
                )
                result.managers_linked += 1

    refresh_search(session, result.created)

    if list_name and list_name.strip() and result.created:
        contact_list = find_or_create_list(session, list_name)
        add_members(session, contact_list, result.created)
        result.list_id = contact_list.id
    return result
