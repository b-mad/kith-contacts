"""D-09 and D-10: choose what leaves in an export, protect it, and keep a record of it.

``build_export`` is the one place an export file is made. By default it leaves out private
contacts, types, tags and lists (P-03), and a CSV leaves out personal contact details, notes,
birthdays and street-level location. A password wraps the file in an AES-256 zip. Every
download from the settings page writes an ``ExportLog`` row that says what was chosen and how
many contacts went, never who or what they contained.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pyzipper
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exchange import (
    LOCATION_TIERS,
    PERSONAL_LABELS,
    CsvPlan,
    _all_contacts,
    export_csv,
    export_json,
)
from app.models import ExportLog
from app.privacy import private_withheld
from app.vcard import to_vcards

KINDS: Final = ("csv", "json", "vcf")
#: The groups a CSV lets you add or drop. ``core`` (name, type, company, title, team, ...) stays.
OPTIONAL_GROUPS: Final = (
    "work_contact", "reporting", "tags_lists", "notes", "birthday", "personal_contact",
)  # fmt: skip
#: Ticked when the form opens: what a colleague needs to reach and place someone at work.
DEFAULT_GROUPS: Final = frozenset({"work_contact", "reporting", "tags_lists"})
DEFAULT_LOCATION: Final = "timezone"
MIN_PASSWORD: Final = 10
_MEDIA: Final = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "vcf": "text/vcard; charset=utf-8",
}
_GROUP_NOTES: Final = {
    "notes": "free-text notes and 'works on'",
    "birthday": "birthdays",
    "personal_contact": "personal email addresses and phone numbers",
}


class ExportError(ValueError):
    """The export form asked for something that cannot be made."""


@dataclass(frozen=True)
class ExportOptions:
    kind: str
    groups: frozenset[str] = DEFAULT_GROUPS
    location: str = DEFAULT_LOCATION
    include_private: bool = False
    password: str | None = None

    @property
    def encrypted(self) -> bool:
        return bool(self.password)

    @property
    def sensitive(self) -> list[str]:
        """D-10: the choices that need an explicit confirmation, in plain words."""
        reasons = []
        if self.kind == "csv":
            reasons += [
                f"includes {text}" for key, text in _GROUP_NOTES.items() if key in self.groups
            ]
            if self.location == "full":
                reasons.append("includes street addresses")
        elif self.kind == "json":
            reasons.append(
                "a JSON file holds every field, including notes, birthdays and addresses"
            )
        else:
            reasons.append("a vCard file holds personal numbers, home addresses and birthdays")
        if self.include_private:
            reasons.append("includes records you marked private")
        return reasons

    def csv_plan(self) -> CsvPlan:
        return CsvPlan(
            groups=frozenset(self.groups | {"core"}),
            location=self.location,
            personal_labels=PERSONAL_LABELS,
        )

    def detail(self) -> str:
        """What was chosen, for the log (no contact data)."""
        if self.kind != "csv":
            return "complete file" + ("; with private records" if self.include_private else "")
        picked = ", ".join(sorted(self.groups)) or "core only"
        extra = "; with private records" if self.include_private else ""
        return f"columns: {picked}; location: {self.location}{extra}"[:300]


@dataclass(frozen=True)
class ExportFile:
    body: bytes
    name: str
    media_type: str
    encrypted: bool
    count: int


def _many(form: Any, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(v) for v in form.getlist(key)]
    value = form.get(key)
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list | tuple) else [str(value)]


def parse_options(kind: str, form: Mapping[str, Any] | Any) -> ExportOptions:
    """Read the settings form. Unknown values are ignored; a weak password is an error."""
    if kind not in KINDS:
        raise ExportError(f"Unknown export format: {kind}")
    chosen = _many(form, "group")
    groups = frozenset(g for g in chosen if g in OPTIONAL_GROUPS) if chosen else DEFAULT_GROUPS
    location = str(form.get("location") or DEFAULT_LOCATION)
    if location not in LOCATION_TIERS:
        location = DEFAULT_LOCATION
    password = None
    if form.get("encrypt"):
        password = str(form.get("password") or "")
        if len(password) < MIN_PASSWORD:
            raise ExportError(f"Use a password of at least {MIN_PASSWORD} characters.")
    return ExportOptions(
        kind=kind,
        groups=groups,
        location=location,
        include_private=bool(form.get("include_private")),
        password=password,
    )


@contextlib.contextmanager
def _scope(options: ExportOptions) -> Iterator[None]:
    if options.include_private:
        yield
    else:
        with private_withheld():
            yield


def _zip(body: bytes, inner: str, password: str) -> bytes:
    buffer = io.BytesIO()
    with pyzipper.AESZipFile(
        buffer, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as archive:
        archive.setpassword(password.encode("utf-8"))
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        archive.writestr(inner, body)
    return buffer.getvalue()


def build_export(
    session: Session, instance_name: str, slug: str, options: ExportOptions
) -> ExportFile:
    with _scope(options):
        if options.kind == "csv":
            body = ("﻿" + export_csv(session, options.csv_plan())).encode("utf-8")
            count = len(_all_contacts(session))
        elif options.kind == "json":
            doc = export_json(session, instance_name)
            body = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
            count = len(doc["contacts"])
        else:
            people = [c for c in _all_contacts(session) if c.archived_at is None]
            body = to_vcards(people).encode("utf-8")
            count = len(people)
    name = f"{slug}-contacts-{datetime.now(UTC):%Y%m%d}.{options.kind}"
    media = _MEDIA[options.kind]
    if options.password:
        return ExportFile(
            _zip(body, name, options.password), f"{name}.zip", "application/zip", True, count
        )
    return ExportFile(body, name, media, False, count)


def log_export(session: Session, options: ExportOptions, file: ExportFile) -> None:
    session.add(
        ExportLog(
            kind=options.kind,
            contact_count=file.count,
            include_private=options.include_private,
            encrypted=file.encrypted,
            detail=options.detail(),
        )
    )
    session.flush()


def recent_exports(session: Session, limit: int = 10) -> list[ExportLog]:
    return list(
        session.scalars(
            select(ExportLog)
            .order_by(ExportLog.created_at.desc(), ExportLog.id.desc())
            .limit(limit)
        )
    )


def log_single(session: Session, kind: str) -> None:
    """A one-contact export (a vCard or JSON file from the card) is logged too."""
    session.add(
        ExportLog(
            kind=kind, contact_count=1, include_private=False, encrypted=False, detail="one contact"
        )
    )
    session.flush()
