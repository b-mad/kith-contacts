"""Compare an incoming contact with a stored one (D-07, ADR-0026).

An import row that looks like a duplicate is compared, field by field, with the contact it
matched (or with the earlier row of the same file it repeats). The result says whether the
two are a *full match* and, when not, exactly which values differ so the person can decide
before importing. Both sides are first turned into the same plain "profile" so a phone
number typed ``(404) 555-0123`` equals the stored ``+14045550123`` and ``Kansas`` equals
``KS``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.links import normalize_phone
from app.models import Contact

#: same = equal; changed = both have a value and they differ; added = only the file has it;
#: missing = only the stored contact has it.
Status = Literal["same", "changed", "added", "missing"]
ItemState = Literal["same", "added", "missing"]

SCALARS: tuple[tuple[str, str], ...] = (
    ("display_name", "Name"),
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("nickname", "Nickname"),
    ("type", "Type"),
    ("company", "Company"),
    ("title", "Title"),
    ("department", "Department"),
    ("team", "Team"),
    ("location", "Location"),
    ("manager", "Manager"),
    ("birthday", "Birthday"),
    ("slack_handle", "Slack handle"),
    ("slack_url", "Slack link"),
    ("teams_url", "Teams link"),
    ("linkedin_url", "LinkedIn"),
    ("pronunciation", "Pronunciation"),
    ("works_on", "Works on"),
    ("notes", "Notes"),
    ("is_favorite", "Favorite"),
    ("photo", "Photo"),
)
COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("emails", "Email addresses"),
    ("phones", "Phone numbers"),
    ("addresses", "Addresses"),
    ("tags", "Tags"),
    ("lists", "Lists"),
    ("custom_fields", "Extra fields"),
    ("activities", "Activity"),
)
ALL_FIELDS = frozenset(k for k, _ in (*SCALARS, *COLLECTIONS))
#: Free text is compared as written (apart from spacing); everything else ignores case too.
_CASE_SENSITIVE = {"notes", "works_on", "slack_url", "teams_url", "linkedin_url"}
#: Shown in the review so nobody assumes more was compared than was.
COMPARED_SUMMARY = (
    "name, work details, emails, phone numbers, addresses, tags, lists, extra fields, "
    "activity and whether there is a photo"
)


@dataclass(frozen=True)
class Item:
    text: str
    state: ItemState


@dataclass
class FieldDiff:
    key: str
    label: str
    status: Status
    collection: bool = False
    stored: str = ""  # scalars: the value on the stored contact
    incoming: str = ""  # scalars: the value in the file
    items: list[Item] = field(default_factory=list)  # collections, stored order first


@dataclass
class DuplicateInfo:
    """What a duplicate row matched and how the two compare."""

    contact_id: int | None  # a stored contact...
    contact_name: str
    row_number: int | None  # ...or an earlier row of the same file
    diffs: list[FieldDiff] = field(default_factory=list)

    @property
    def differences(self) -> list[FieldDiff]:
        return [d for d in self.diffs if d.status != "same"]

    @property
    def unchanged(self) -> list[FieldDiff]:
        return [d for d in self.diffs if d.status == "same"]

    @property
    def full_match(self) -> bool:
        return not self.differences

    @property
    def in_file(self) -> bool:
        return self.row_number is not None


Profile = dict[str, Any]  # scalars -> str; collections -> {match key: display text}


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _text(value: object) -> str:
    return "" if value is None else _collapse(str(value))


def _place_key(street: object, city: object, postal_code: object) -> str:
    return "|".join(_text(v).casefold() for v in (street, city, postal_code))


def _address_text(label: object, *parts: object) -> str:
    lines = [
        ", ".join(_text(line) for line in str(p).splitlines() if _text(line)) for p in parts if p
    ]
    body = ", ".join(line for line in lines if line)
    name = _text(label)
    return f"{name}: {body}" if name and body else body


def _contact_line(address: Any) -> tuple[str, str]:
    key = _place_key(address.street, address.city, address.postal_code)
    return key, _address_text(
        address.label, address.street, address.city, address.region, address.postal_code,
        address.country,
    )  # fmt: skip


def _phone_key(number: str, region: str) -> str:
    return re.sub(r"\D", "", normalize_phone(number, region))


def _label_suffix(label: object) -> str:
    text = _text(label)
    return f" ({text})" if text else ""


def _clip(value: str, size: int = 90) -> str:
    return value if len(value) <= size else value[: size - 1] + "…"


def profile_of_contact(contact: Contact, phone_region: str = "US") -> Profile:
    """The comparable view of a stored contact (relationships must be loaded)."""
    c = contact
    profile: Profile = {
        "display_name": _text(c.display_name),
        "first_name": _text(c.first_name),
        "last_name": _text(c.last_name),
        "nickname": _text(c.nickname),
        "type": _text(c.contact_type.name),
        "company": _text(c.company),
        "title": _text(c.title),
        "department": _text(c.department),
        "team": _text(c.team),
        "location": _text(c.location),
        "manager": _text(c.manager.display_name if c.manager else ""),
        "birthday": _text(c.birthday),
        "slack_handle": _text(c.slack_handle),
        "slack_url": _text(c.slack_url),
        "teams_url": _text(c.teams_url),
        "linkedin_url": _text(c.linkedin_url),
        "pronunciation": _text(c.pronunciation),
        "works_on": _text(c.works_on),
        "notes": _text(c.notes),
        "is_favorite": "Yes" if c.is_favorite else "",
        "photo": "Yes" if c.photo is not None else "",
        "emails": {
            e.email.lower(): f"{e.email}{_label_suffix(e.label)}" for e in c.emails
        },
        "phones": {
            _phone_key(p.number, phone_region): f"{p.number}{_label_suffix(p.label)}"
            for p in c.phones
        },
        "addresses": dict(_contact_line(a) for a in c.addresses if _contact_line(a)[0].strip("|")),
        "tags": {t.name.casefold(): t.name for t in c.tags},
        "lists": {
            m.contact_list.name.casefold(): m.contact_list.name
            + (f" ({m.role_note})" if m.role_note else "")
            for m in c.memberships
        },
        "custom_fields": {
            f"{f.name.casefold()}\x00{_text(f.value)}": f"{f.name}: {_text(f.value)}"
            for f in c.custom_fields
        },
        "activities": {
            f"{a.kind}|{a.occurred_on.isoformat()}|{_text(a.summary)}": _clip(
                f"{a.occurred_on.isoformat()} · {a.kind} · {_text(a.summary)}"
            )
            for a in c.activities
        },
    }  # fmt: skip
    return profile


def profile_of_row(
    data: Mapping[str, Any],
    *,
    tags: Sequence[str],
    manager_name: str | None,
    type_name: str | None,
    extra: Mapping[str, Any],
    phone_region: str = "US",
) -> Profile:
    """The comparable view of an import row (``PlannedRow.data`` and friends)."""
    d = data
    profile: Profile = {
        key: _text(d.get(key))
        for key, _ in SCALARS
        if key not in {"type", "manager", "is_favorite", "photo"}
    }
    profile["type"] = _text(type_name)
    profile["manager"] = _text(manager_name)
    profile["is_favorite"] = "Yes" if d.get("is_favorite") else ""
    profile["photo"] = "Yes" if extra.get("photo") else ""
    profile["emails"] = {
        _text(e.get("email")).lower(): f"{_text(e.get('email'))}{_label_suffix(e.get('label'))}"
        for e in d.get("emails") or []
        if _text(e.get("email"))
    }
    profile["phones"] = {
        _phone_key(str(p["number"]), phone_region): (
            f"{_text(p['number'])}{_label_suffix(p.get('label'))}"
        )
        for p in d.get("phones") or []
        if _text(p.get("number"))
    }
    addresses: dict[str, str] = {}
    for a in d.get("addresses") or []:
        key = _place_key(a.get("street"), a.get("city"), a.get("postal_code"))
        if key.strip("|"):
            addresses[key] = _address_text(
                a.get("label"), a.get("street"), a.get("city"), a.get("region"),
                a.get("postal_code"), a.get("country"),
            )  # fmt: skip
    profile["addresses"] = addresses
    profile["tags"] = {t.casefold(): t for t in tags if t}
    profile["lists"] = {
        str(name).casefold(): str(name) + (f" ({role})" if role else "")
        for name, role, _private in extra.get("lists") or []
    }
    profile["custom_fields"] = {
        f"{_text(f.get('name')).casefold()}\x00{_text(f.get('value'))}": (
            f"{_text(f.get('name'))}: {_text(f.get('value'))}"
        )
        for f in d.get("custom_fields") or []
        if _text(f.get("name"))
    }
    activities: dict[str, str] = {}
    for a in extra.get("activities") or []:
        when, kind, summary = (
            _text(a.get("occurred_on")),
            _text(a.get("kind")),
            _text(a.get("summary")),
        )
        activities[f"{kind}|{when}|{summary}"] = _clip(f"{when} · {kind} · {summary}")
    profile["activities"] = activities
    return profile


def _same(key: str, a: str, b: str) -> bool:
    if key in _CASE_SENSITIVE:
        return a == b
    return a.casefold() == b.casefold()


def _scalar(key: str, label: str, stored: str, incoming: str) -> FieldDiff | None:
    if not stored and not incoming:
        return None
    if _same(key, stored, incoming):
        status: Status = "same"
    elif stored and incoming:
        status = "changed"
    else:
        status = "added" if incoming else "missing"
    return FieldDiff(key, label, status, stored=stored, incoming=incoming)


def _collection(
    key: str, label: str, stored: Mapping[str, str], incoming: Mapping[str, str]
) -> FieldDiff | None:
    if not stored and not incoming:
        return None
    items = [Item(text, "same" if k in incoming else "missing") for k, text in stored.items()]
    items += [Item(text, "added") for k, text in incoming.items() if k not in stored]
    states = {i.state for i in items}
    if states == {"same"}:
        status: Status = "same"
    elif not stored:
        status = "added"
    elif not incoming:
        status = "missing"
    else:
        status = "changed"
    return FieldDiff(key, label, status, collection=True, items=items)


def diff_profiles(
    stored: Profile, incoming: Profile, carried: Collection[str] | None = None
) -> list[FieldDiff]:
    """Every field either side has, in display order; ``carried`` limits it to the fields
    the file can hold at all (a CSV without a Tags column says nothing about tags)."""
    out: list[FieldDiff] = []
    for key, label in SCALARS:
        if carried is not None and key not in carried:
            continue
        diff = _scalar(key, label, str(stored.get(key, "")), str(incoming.get(key, "")))
        if diff:
            out.append(diff)
    for key, label in COLLECTIONS:
        if carried is not None and key not in carried:
            continue
        coll = _collection(key, label, stored.get(key) or {}, incoming.get(key) or {})
        if coll:
            out.append(coll)
    return out
