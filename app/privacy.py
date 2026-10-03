"""Presenting mode: keep private details off a shared screen (P-01 to P-07, ADR-0016).

While presenting, private data is never sent to the browser:

* Private *records* — contacts, tags, lists and extra fields marked private, and emails or
  phones with a personal label — are withheld at the database session: every ORM read in a
  GET request gets ``with_loader_criteria`` filters, so pages, counts, dropdowns, the org
  chart and the JSON API simply never see them.
* Private *fields* of a contact — notes, activity summaries, and optionally location, photo
  and last-contact dates — are removed by ``redact``, which keeps only an allowlist of public
  fields. A field added to ``ContactOut`` later is hidden until it is classified here.
* Pages that show raw data (import, duplicates, edit form, exports, backups) are blocked.

The state is per request (a context variable set by middleware from the ``cm_presenting``
cookie). Browsers don't separate cookies by port, so one cookie covers every instance on
localhost — switching tabs in a meeting stays safe.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from types import NoneType, UnionType
from typing import Any, Final, Union, get_args, get_origin

from sqlalchemy import event, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from starlette.datastructures import State

from app.links import contact_teams_url, mailto_url, tel_url
from app.models import (
    AppSetting,
    Contact,
    ContactEmail,
    ContactList,
    ContactPhone,
    ContactPhoto,
    CustomField,
    ListMember,
    Tag,
    contact_tag,
)
from app.schemas import ContactLinks, ContactOut

COOKIE: Final = "cm_presenting"

Choices = tuple[tuple[str, str, str], ...]  # (value, label, hint)
CATEGORY_CHOICES: Final[Choices] = (
    ("notes", "Notes", "Memory cues, how you met, anything personal"),
    ("activity", "Activity details", "The kind and date stay; what was said is hidden"),
    ("personal", "Personal emails and phones", "Any address or number with a personal label"),
    ("fields", "Extra fields marked private", "Birthday, family, anything you flag"),
    ("location", "Location", "City or office"),
    ("photo", "Photos", "Profile pictures"),
    ("last_contact", "Last contact dates", "Dates in results, on cards and on Reconnect"),
)
CATEGORIES: Final = tuple(value for value, _, _ in CATEGORY_CHOICES)
OFF_CHOICES: Final[Choices] = (
    ("browser", "When I close the browser", "Recommended"),
    ("2h", "After 2 hours", ""),
    ("manual", "Only when I turn it off", ""),
)
VIEW_CHOICES: Final[Choices] = (
    ("work", "Work details", "Everything not hidden above"),
    ("names", "Names and companies only", "For demos of the app itself"),
    ("locked", "Nothing — locked", "A lock screen; suggested for a personal instance"),
)
LOOK_CHOICES: Final[Choices] = (
    ("placeholder", "Show a “hidden” placeholder", ""),
    ("none", "Leave no trace", ""),
)
OFF_SECONDS: Final[dict[str, int | None]] = {"browser": None, "2h": 2 * 3600, "manual": 400 * 86400}
MAX_LABELS: Final = 20

# Pages that show raw data are unavailable while presenting (P-05).
BLOCKED_PREFIXES: Final = (
    "/import",
    "/duplicates",
    "/export/",
    "/settings/backups/",
    "/settings/privacy",
)
BLOCKED_SUFFIXES: Final = ("/edit", "/vcard", "/export.json")
UNLOCKED_PREFIXES: Final = ("/presenting", "/static/", "/instance.css", "/healthz")


@dataclass(frozen=True)
class PrivacySettings:
    hidden: frozenset[str] = frozenset({"notes", "activity", "personal", "fields"})
    labels: tuple[str, ...] = ("personal", "home", "mobile")
    fields: tuple[str, ...] = ()  # extra-field names marked private (lower case)
    look: str = "placeholder"
    off: str = "browser"
    start: bool = False
    view: str = "work"


DEFAULT: Final = PrivacySettings()
_PREFIX: Final = "privacy."


def parse_names(raw: str) -> tuple[str, ...]:
    """Comma-separated labels or names → unique, lower case, trimmed."""
    seen: list[str] = []
    for part in raw.split(","):
        name = " ".join(part.split()).lower()[:50]
        if name and name not in seen:
            seen.append(name)
    return tuple(seen[:MAX_LABELS])


def load_privacy(session: Session) -> PrivacySettings:
    rows = dict(
        session.execute(
            select(AppSetting.key, AppSetting.value).where(AppSetting.key.like(f"{_PREFIX}%"))
        )
        .tuples()
        .all()
    )

    def get(key: str) -> str | None:
        return rows.get(_PREFIX + key)

    hidden = get("hidden")
    labels = get("labels")
    fields = get("fields")
    look, off, view = get("look"), get("off"), get("view")
    return PrivacySettings(
        hidden=frozenset(h for h in hidden.split(",") if h in CATEGORIES)
        if hidden is not None
        else DEFAULT.hidden,
        labels=parse_names(labels) if labels is not None else DEFAULT.labels,
        fields=parse_names(fields) if fields is not None else DEFAULT.fields,
        look=look if look in {v for v, _, _ in LOOK_CHOICES} else DEFAULT.look,
        off=off if off in OFF_SECONDS else DEFAULT.off,
        start=get("start") == "1",
        view=view if view in {v for v, _, _ in VIEW_CHOICES} else DEFAULT.view,
    )


def save_privacy(session: Session, settings: PrivacySettings) -> PrivacySettings:
    values = {
        "hidden": ",".join(sorted(settings.hidden)),
        "labels": ",".join(settings.labels),
        "fields": ",".join(settings.fields),
        "look": settings.look,
        "off": settings.off,
        "start": "1" if settings.start else "0",
        "view": settings.view,
    }
    for key, value in values.items():
        stmt = insert(AppSetting).values(key=_PREFIX + key, value=value)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value, "updated_at": func.now()},
            )
        )
    session.flush()
    return load_privacy(session)


def current_privacy(state: State) -> PrivacySettings:
    cached: PrivacySettings | None = getattr(state, "privacy", None)
    if cached is not None:
        return cached
    try:
        with state.session_factory() as session:
            cached = load_privacy(session)
    except SQLAlchemyError:
        return DEFAULT
    state.privacy = cached
    return cached


def forget_privacy(state: State) -> None:
    state.privacy = None


# ---------------------------------------------------------------- per-request state


@dataclass(frozen=True)
class Presenting:
    settings: PrivacySettings
    filter_queries: bool = True  # GET requests: withhold private records at the session

    def hides(self, category: str) -> bool:
        return category in self.settings.hidden

    def personal(self, label: str | None) -> bool:
        return self.hides("personal") and (label or "").strip().lower() in self.settings.labels

    def private_field(self, name: str, flagged: bool) -> bool:
        return self.hides("fields") and (flagged or name.strip().lower() in self.settings.fields)

    @property
    def placeholders(self) -> bool:
        return self.settings.look == "placeholder"

    @property
    def names_only(self) -> bool:
        return self.settings.view == "names"

    @property
    def locked(self) -> bool:
        return self.settings.view == "locked"


PRESENTING: ContextVar[Presenting | None] = ContextVar("presenting", default=None)


def presenting() -> Presenting | None:
    return PRESENTING.get()


@contextlib.contextmanager
def unfiltered() -> Iterator[None]:
    """Read private records inside a presenting request (counts only — never render them)."""
    current = PRESENTING.get()
    token = PRESENTING.set(replace(current, filter_queries=False) if current else None)
    try:
        yield
    finally:
        PRESENTING.reset(token)


def is_presenting(cookies: Mapping[str, str], settings: PrivacySettings) -> bool:
    value = cookies.get(COOKIE)
    if value in ("1", "0"):
        return value == "1"
    return settings.start  # P-07: start every visit to this instance presenting


def is_blocked(path: str) -> bool:
    """P-05: pages that show raw data are unavailable while presenting."""
    if path.startswith(BLOCKED_PREFIXES):
        return True
    return path.startswith("/contacts/") and path.endswith(BLOCKED_SUFFIXES)


def is_unlocked(path: str) -> bool:
    """Paths that still work when presenting locks this instance (P-07)."""
    return path.startswith(UNLOCKED_PREFIXES)


@event.listens_for(Session, "do_orm_execute")
def _withhold_private_records(state: ORMExecuteState) -> None:
    """P-02: while presenting, ORM reads never return private records."""
    p = PRESENTING.get()
    if (
        p is None
        or not p.filter_queries
        or not state.is_select
        or state.is_column_load  # refreshing an object already loaded
        or state.execution_options.get("include_private")
    ):
        return
    options = [
        # Lambdas, so the criteria follow aliased tables too (e.g. a tag table joined twice).
        with_loader_criteria(Contact, lambda c: c.is_private.is_(False), include_aliases=True),
        with_loader_criteria(Tag, lambda t: t.is_private.is_(False), include_aliases=True),
        with_loader_criteria(
            ContactList, lambda cl: cl.is_private.is_(False), include_aliases=True
        ),
    ]
    if p.hides("fields"):
        names = tuple(p.settings.fields) or ("",)
        options.append(
            with_loader_criteria(
                CustomField,
                lambda f: f.is_private.is_(False) & func.lower(f.name).not_in(names),
                include_aliases=True,
            )
        )
    if p.hides("personal") and p.settings.labels:
        labels = tuple(p.settings.labels)
        options.append(
            with_loader_criteria(
                ContactEmail,
                lambda e: func.lower(func.coalesce(e.label, "")).not_in(labels),
                include_aliases=True,
            )
        )
        options.append(
            with_loader_criteria(
                ContactPhone,
                lambda ph: func.lower(func.coalesce(ph.label, "")).not_in(labels),
                include_aliases=True,
            )
        )
    if p.hides("photo"):
        options.append(
            with_loader_criteria(
                ContactPhoto, lambda ph: ph.contact_id.is_(None), include_aliases=True
            )
        )
    state.statement = state.statement.options(*options)


# ---------------------------------------------------------------- contact redaction

# Public fields of ContactOut while presenting (the allowlist). Everything else is blanked.
WORK_FIELDS: Final = frozenset(
    {
        "id", "display_name", "first_name", "last_name", "nickname", "contact_type", "company",
        "title", "team", "department", "location", "manager", "reports", "works_on",
        "slack_handle", "slack_url", "teams_url", "linkedin_url", "pronunciation", "is_favorite",
        "emails", "phones", "tags", "lists", "links", "archived", "has_photo", "custom_fields",
        "activities", "last_contact", "created_at", "updated_at",
    }
)  # fmt: skip
NAME_FIELDS: Final = frozenset(
    {
        "id",
        "display_name",
        "contact_type",
        "company",
        "links",
        "archived",
        "created_at",
        "updated_at",
    }
)
# Private fields, each shown only when Settings doesn't hide its category. Every ContactOut
# field is in WORK_FIELDS or here (a test checks), so a new field starts out hidden.
PRIVATE_FIELDS: Final = {"notes": "notes"}


def _blank(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin in (UnionType, Union) and NoneType in get_args(annotation):
        return None
    if origin is list:
        return []
    if annotation is bool or annotation == "bool":
        return False
    raise TypeError(f"no blank value for {annotation!r}; classify the field in app.privacy")


def redact(data: dict[str, Any], p: Presenting) -> dict[str, Any]:
    """Keep only the public fields of a contact (``to_out`` data, ORM objects inside)."""
    allowed = (
        NAME_FIELDS
        if p.names_only
        else WORK_FIELDS
        | {name for name, category in PRIVATE_FIELDS.items() if not p.hides(category)}
    )
    out: dict[str, Any] = {}
    for name, info in ContactOut.model_fields.items():
        if name in allowed and name in data:
            out[name] = data[name]
        elif not info.is_required():
            out[name] = info.get_default(call_default_factory=True)
        else:
            out[name] = _blank(info.annotation)
    out["emails"] = [e for e in out["emails"] if not p.personal(e.label)]
    out["phones"] = [ph for ph in out["phones"] if not p.personal(ph.label)]
    out["tags"] = [t for t in out["tags"] if not t.is_private]
    out["lists"] = [cl for cl in out["lists"] if not cl.is_private]
    if out.get("manager") is not None and out["manager"].is_private:
        out["manager"] = None
    out["reports"] = [r for r in out["reports"] if not r.is_private]
    if out.get("custom_fields") is not None:
        out["custom_fields"] = [
            f for f in out["custom_fields"] if not p.private_field(f.name, f.is_private)
        ]
    if out.get("activities") is not None and p.hides("activity"):
        out["activities"] = [
            {"id": a.id, "kind": a.kind, "occurred_on": a.occurred_on, "summary": ""}
            for a in out["activities"]
        ]
    if p.hides("location"):
        out["location"] = None
    if p.hides("photo"):
        out["has_photo"] = False
    if p.hides("last_contact"):
        out["last_contact"] = None
        if out.get("activities") is not None:
            out["activities"] = []  # every entry is dated
    out["links"] = public_links(out)
    return out


def public_links(data: Mapping[str, Any]) -> ContactLinks:
    """Card actions rebuilt from the redacted contact, so a hidden address never leaks."""
    emails = data["emails"]
    primary = next((e.email for e in emails if e.is_primary), emails[0].email if emails else None)
    phones = data["phones"]
    return ContactLinks(
        mailto=mailto_url([primary]) if primary else None,
        teams=contact_teams_url(data["teams_url"], primary),
        slack=data["slack_url"],
        tel=tel_url(phones[0].number) if phones else None,
    )


def shown_summary(summary: str) -> str:
    """An activity summary as it may be shown now (blank while presenting hides activity)."""
    p = PRESENTING.get()
    return "" if p is not None and p.hides("activity") else summary


def shows_dates() -> bool:
    """False while presenting hides last-contact dates."""
    p = PRESENTING.get()
    return p is None or not p.hides("last_contact")


def private_refs(session: Session) -> tuple[set[str], set[int], set[int]]:
    """Names of private tags, ids of private lists and ids of private contacts."""
    opts = {"include_private": True}
    tags = session.scalars(
        select(func.lower(Tag.name)).where(Tag.is_private.is_(True)).execution_options(**opts)
    )
    lists = session.scalars(
        select(ContactList.id).where(ContactList.is_private.is_(True)).execution_options(**opts)
    )
    contacts = session.scalars(
        select(Contact.id).where(Contact.is_private.is_(True)).execution_options(**opts)
    )
    return set(tags), set(lists), set(contacts)


def hidden_counts(session: Session, contact: Contact, p: Presenting | None) -> dict[str, int]:
    """How many private items a card leaves out, for "hidden while presenting" placeholders."""
    if p is None or not p.placeholders or p.names_only:
        return {}
    opts = {"include_private": True}

    def count(stmt: Any) -> int:
        return int(session.scalar(stmt.execution_options(**opts)) or 0)

    labels = list(p.settings.labels) or [""]
    counts = {
        "tags": count(
            select(func.count())
            .select_from(contact_tag.join(Tag, Tag.id == contact_tag.c.tag_id))
            .where(contact_tag.c.contact_id == contact.id, Tag.is_private.is_(True))
        ),
        "lists": count(
            select(func.count())
            .select_from(ListMember)
            .join(ContactList, ContactList.id == ListMember.list_id)
            .where(ListMember.contact_id == contact.id, ContactList.is_private.is_(True))
        ),
    }
    if p.hides("personal"):
        counts["personal"] = count(
            select(func.count())
            .select_from(ContactEmail)
            .where(
                ContactEmail.contact_id == contact.id,
                func.lower(func.coalesce(ContactEmail.label, "")).in_(labels),
            )
        ) + count(
            select(func.count())
            .select_from(ContactPhone)
            .where(
                ContactPhone.contact_id == contact.id,
                func.lower(func.coalesce(ContactPhone.label, "")).in_(labels),
            )
        )
    if p.hides("fields"):
        names = list(p.settings.fields) or [""]
        counts["fields"] = count(
            select(func.count())
            .select_from(CustomField)
            .where(
                CustomField.contact_id == contact.id,
                CustomField.is_private.is_(True) | func.lower(CustomField.name).in_(names),
            )
        )
    if contact.manager_id is not None:  # a private manager is left out of the card
        counts["manager"] = count(
            select(func.count())
            .select_from(Contact)
            .where(Contact.id == contact.manager_id, Contact.is_private.is_(True))
        )
    if p.hides("notes"):
        counts["notes"] = 1 if contact.notes else 0
    if p.hides("last_contact"):
        counts["activities"] = len(contact.activities)
    return {k: v for k, v in counts.items() if v}
