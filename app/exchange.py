"""Export (D-03) and import (D-01, D-02) of contacts.

Exports: CSV (one row per contact), JSON (lossless, ``format: contacts-app/1``)
and vCard. Imports: CSV with column mapping, or vCard; both go through
``plan_import`` (preview, duplicates, errors) and ``run_import``.
"""

from __future__ import annotations

import base64
import contextlib
import csv
import io
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.contacts import ContactError, check_manager, create_contact, resolve_company
from app.links import normalize_linkedin
from app.lists import add_members, find_or_create_list
from app.models import (
    Contact,
    ContactEmail,
    ContactList,
    ContactType,
    CustomField,
    ListMember,
    Tag,
)
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
                selectinload(Contact.custom_fields),
                selectinload(Contact.activities),
            )
            .order_by(func.lower(Contact.display_name), Contact.id)
            .execution_options(populate_existing=True)  # always export what is stored now
        ).all()
    )


# ---------------------------------------------------------------- export (D-03)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def contact_record(contact: Contact, *, include_photo: bool = False) -> dict[str, Any]:
    """One contact in the ``contacts-app/1`` format (D-03, I-09, C-12 merge snapshots)."""
    c = contact
    record: dict[str, Any] = {
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
        "linkedin_url": c.linkedin_url,  # C-18
        "pronunciation": c.pronunciation,
        "is_favorite": c.is_favorite,
        "keep_in_touch": c.kit_interval,  # C-15
        "keep_in_touch_started_on": c.kit_started_on.isoformat() if c.kit_started_on else None,
        "keep_in_touch_snoozed_until": (
            c.kit_snoozed_until.isoformat() if c.kit_snoozed_until else None
        ),  # C-16
        "is_private": c.is_private,  # P-03
        "archived_at": _iso(c.archived_at),
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
        "emails": [
            {"email": e.email, "label": e.label, "is_primary": e.is_primary} for e in c.emails
        ],
        "phones": [{"number": p.number, "label": p.label} for p in c.phones],
        "tags": [t.name for t in c.tags],
        "private_tags": [t.name for t in c.tags if t.is_private],  # P-03
        "lists": [
            {
                "name": m.contact_list.name,
                "role_note": m.role_note,
                "private": m.contact_list.is_private,
            }
            for m in c.memberships
        ],
        "custom_fields": [
            {"name": f.name, "value": f.value, "private": f.is_private} for f in c.custom_fields
        ],
        "activities": [
            {"kind": a.kind, "occurred_on": a.occurred_on.isoformat(), "summary": a.summary}
            for a in c.activities
        ],
    }
    if include_photo and c.photo is not None:
        record["photo"] = {
            "content_type": c.photo.content_type,
            "data_base64": base64.b64encode(c.photo.data).decode("ascii"),
        }
    return record


def export_json(session: Session, instance_name: str) -> dict[str, Any]:
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
            {"name": t.name, "color": t.color, "private": t.is_private}
            for t in session.scalars(select(Tag).order_by(Tag.name))
        ],
        "lists": [
            {
                "name": cl.name,
                "description": cl.description,
                "status": cl.status,
                "private": cl.is_private,
                "tags": [t.name for t in cl.tags],
            }
            for cl in session.scalars(
                select(ContactList)
                .options(selectinload(ContactList.tags))
                .order_by(ContactList.name)
            )
        ],
        "contacts": [contact_record(c) for c in contacts],
    }


def export_contact_json(contact: Contact, instance_name: str) -> dict[str, Any]:
    """I-09: one contact, with its photo, for copying into another instance."""
    return {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(),
        "instance": instance_name,
        "contacts": [contact_record(contact, include_photo=True)],
    }


CSV_COLUMNS = [
    "display_name", "first_name", "last_name", "nickname", "type", "company", "title", "team",
    "department", "location", "manager", "primary_email", "emails", "phones", "slack_handle",
    "slack_url", "teams_url", "works_on", "notes", "tags", "lists", "favorite", "archived",
    "linkedin",
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
                    c.linkedin_url,
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
    # C-18: LinkedIn's own Connections.csv calls the profile link "URL".
    "linkedin_url": ("linkedin", "linkedinurl", "linkedinprofile", "linkedinprofileurl",
                     "profileurl", "url"),
}  # fmt: skip

FIELD_LABELS = {
    "display_name": "Display name", "first_name": "First name", "last_name": "Last name",
    "nickname": "Nickname", "email": "Email", "email2": "Email 2", "email3": "Email 3",
    "phone": "Phone", "phone2": "Phone 2", "phone3": "Phone 3", "company": "Company",
    "title": "Title", "department": "Department", "team": "Team", "location": "Location",
    "manager": "Manager (name)", "works_on": "Works on", "notes": "Notes", "tags": "Tags",
    "type": "Type", "slack_handle": "Slack handle", "linkedin_url": "LinkedIn profile",
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
    text = _skip_preamble(text)
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


def _skip_preamble(text: str) -> str:
    """LinkedIn's Connections.csv starts with a "Notes:" paragraph before the header row."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip().lower().rstrip(":") != "notes":
        return text
    for index, line in enumerate(lines):
        if line.lower().startswith("first name,"):
            return "".join(lines[index:])
    return text


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
                "linkedin_url": card.linkedin_url,
            }.items()
            if v
        }
        record["_emails"] = card.emails
        record["_phones"] = card.phones
        records.append(record)
    return records


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def rows_from_json(raw: str) -> list[dict[str, Any]]:
    """Records from a ``contacts-app/1`` JSON export — one contact or a whole instance (I-09)."""
    if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ContactError("File is larger than 5 MB", "file")
    try:
        doc = json.loads(raw)
    except ValueError:
        raise ContactError("That file is not valid JSON", "file") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ContactError("That JSON file is not an export from this app", "file")
    contacts = doc.get("contacts")
    if not isinstance(contacts, list) or not contacts:
        raise ContactError("The file has no contacts", "file")
    if len(contacts) > MAX_IMPORT_ROWS:
        raise ContactError(f"At most {MAX_IMPORT_ROWS} rows can be imported at once", "file")
    records: list[dict[str, Any]] = []
    for item in contacts:
        c = item if isinstance(item, dict) else {}
        record: dict[str, Any] = {
            key: value
            for key in (
                "display_name", "first_name", "last_name", "nickname", "type", "company",
                "title", "team", "department", "location", "manager", "works_on", "notes",
                "slack_handle", "slack_url", "teams_url", "pronunciation", "linkedin_url",
            )
            if (value := _text(c.get(key)))
        }  # fmt: skip
        record["tags"] = "; ".join(t for t in c.get("tags") or [] if isinstance(t, str))
        record["_emails"] = [
            (e["email"], _text(e.get("label")) or "", bool(e.get("is_primary")))
            for e in c.get("emails") or []
            if isinstance(e, dict) and _text(e.get("email"))
        ]
        record["_phones"] = [
            (p["number"], _text(p.get("label")) or "")
            for p in c.get("phones") or []
            if isinstance(p, dict) and _text(p.get("number"))
        ]
        record["_custom_fields"] = [
            {"name": f.get("name"), "value": f.get("value")}
            for f in c.get("custom_fields") or []
            if isinstance(f, dict)
        ]
        record["is_favorite"] = c.get("is_favorite") is True
        record["_extra"] = {
            "lists": [
                (m["name"], _text(m.get("role_note")), m.get("private") is True)
                for m in c.get("lists") or []
                if isinstance(m, dict) and _text(m.get("name"))
            ],
            # C-15, C-16, P-03: keep-in-touch and private flags travel with the contact.
            "kit": {
                "interval": _text(c.get("keep_in_touch")),
                "started_on": _text(c.get("keep_in_touch_started_on")),
                "snoozed_until": _text(c.get("keep_in_touch_snoozed_until")),
            },
            "private": c.get("is_private") is True,
            "private_tags": [t for t in c.get("private_tags") or [] if isinstance(t, str)],
            "private_fields": [
                f["name"]
                for f in c.get("custom_fields") or []
                if isinstance(f, dict) and f.get("private") is True and _text(f.get("name"))
            ],
            "activities": [a for a in c.get("activities") or [] if isinstance(a, dict)],
            "photo": c.get("photo") if isinstance(c.get("photo"), dict) else None,
            "archived": bool(c.get("archived_at")),
        }
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
    extra: dict[str, Any] = field(default_factory=dict)  # JSON imports (I-09)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def extras_summary(self) -> str:
        """E.g. '2 fields · 3 activities · 1 list · photo' for the preview."""
        parts = []
        counts = (
            (len(self.data.get("custom_fields") or []), "field"),
            (len(self.extra.get("activities") or []), "activity"),
            (len(self.extra.get("lists") or []), "list"),
        )
        for n, noun in counts:
            if n:
                plural = "activities" if noun == "activity" else f"{noun}s"
                parts.append(f"{n} {noun if n == 1 else plural}")
        if self.extra.get("photo"):
            parts.append("photo")
        if (self.extra.get("kit") or {}).get("interval"):
            parts.append("keep in touch")
        if self.extra.get("private"):
            parts.append("private")
        if self.extra.get("archived"):
            parts.append("archived")
        return " · ".join(parts)


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
                    "slack_url",
                    "teams_url",
                    "pronunciation",
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
        if record.get("linkedin_url"):  # C-18: not a LinkedIn profile -> left out, not an error
            with contextlib.suppress(ValueError):
                data["linkedin_url"] = normalize_linkedin(str(record["linkedin_url"]))
        if record.get("is_favorite") is True:
            data["is_favorite"] = True
        if record.get("_custom_fields"):
            data["custom_fields"] = record["_custom_fields"]
        row.data = data
        row.extra = dict(record.get("_extra") or {})
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
    extras: list[tuple[int, dict[str, Any]]] = []
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
        if row.extra:
            extras.append((contact.id, row.extra))
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

    _apply_extras(session, extras)
    refresh_search(session, result.created)

    if list_name and list_name.strip() and result.created:
        contact_list = find_or_create_list(session, list_name)
        add_members(session, contact_list, result.created)
        result.list_id = contact_list.id
    return result


def _apply_extras(session: Session, extras: Sequence[tuple[int, dict[str, Any]]]) -> None:
    """I-09: list memberships (with roles), activities, photo and archived state from JSON.

    Anything malformed is skipped rather than failing the whole import.
    """
    from app.activity import add_activity
    from app.photos import set_photo

    memberships: dict[str, tuple[str, list[tuple[int, str | None]]]] = {}
    private_lists: set[str] = set()
    private_tags: set[str] = set()
    for contact_id, extra in extras:
        for name, role, private in extra.get("lists") or []:
            memberships.setdefault(name.lower(), (name, []))[1].append((contact_id, role))
            if private:
                private_lists.add(name.lower())
        private_tags.update(t.lower() for t in extra.get("private_tags") or [])
        _apply_flags(session, contact_id, extra)
        for activity in extra.get("activities") or []:
            try:
                occurred = date.fromisoformat(str(activity.get("occurred_on", "")))
                add_activity(
                    session,
                    contact_id,
                    kind=str(activity.get("kind", "")),
                    summary=str(activity.get("summary", "")),
                    occurred_on=occurred,
                    refresh=False,
                )
            except (ContactError, ValueError):
                continue
        photo = extra.get("photo")
        if photo:
            with contextlib.suppress(ContactError, ValueError):
                set_photo(session, contact_id, base64.b64decode(str(photo.get("data_base64", ""))))
        if extra.get("archived"):
            session.execute(
                update(Contact)
                .where(Contact.id == contact_id)
                .values(archived_at=datetime.now(UTC))
            )
    if private_tags:  # private in the source stays private here (never the reverse)
        session.execute(
            update(Tag).where(func.lower(Tag.name).in_(private_tags)).values(is_private=True)
        )
    for name, members in memberships.values():
        try:
            contact_list = find_or_create_list(session, name)
        except ContactError:
            continue
        if name.lower() in private_lists:
            contact_list.is_private = True
        current = {m.contact_id for m in contact_list.members}
        for contact_id, role in members:
            if contact_id not in current:
                contact_list.members.append(
                    ListMember(contact_id=contact_id, role_note=(role or "")[:200] or None)
                )
                current.add(contact_id)
    session.flush()


def _apply_flags(session: Session, contact_id: int, extra: dict[str, Any]) -> None:
    """C-15, C-16, P-03: keep-in-touch cadence and private flags from a JSON import."""
    from app.keep_in_touch import INTERVALS

    values: dict[str, Any] = {}
    kit = extra.get("kit") or {}
    if kit.get("interval") in INTERVALS:
        values["kit_interval"] = kit["interval"]
        values["kit_started_on"] = _date(kit.get("started_on")) or date.today()
        values["kit_snoozed_until"] = _date(kit.get("snoozed_until"))
    if extra.get("private"):
        values["is_private"] = True
    if values:
        session.execute(update(Contact).where(Contact.id == contact_id).values(**values))
    names = [n.lower() for n in extra.get("private_fields") or []]
    if names:
        session.execute(
            update(CustomField)
            .where(CustomField.contact_id == contact_id, func.lower(CustomField.name).in_(names))
            .values(is_private=True)
        )


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
