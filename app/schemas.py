"""Validated input and output shapes for contacts (C-01 to C-08)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.appearance import Density, Palette, Theme
from app.birthdays import parse_birthday
from app.links import normalize_linkedin


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _https_only(value: str | None) -> str | None:
    # Only https links are rendered as hrefs — blocks javascript: and other schemes.
    if value is not None and not value.lower().startswith("https://"):
        raise ValueError("must be an https:// link")
    return value


def _linkedin(value: str | None) -> str | None:
    return normalize_linkedin(value) if value is not None else None


def _birthday(value: str | None) -> str | None:
    """C-20: any common form -> "YYYY-MM-DD" or "--MM-DD". Slashed dates are read month
    first here; the form and the import convert day-first dates for their region first."""
    if value is None:
        return None
    try:
        return parse_birthday(value)
    except ValueError:
        raise ValueError("use a date like March 14, 1980-03-14 or 3/14") from None


def _strip_at(value: str | None) -> str | None:
    return value.lstrip("@") or None if value else value


# Optional strings: blank input becomes None; length/pattern constraints apply to the str only.
_Blank = BeforeValidator(_blank_to_none)
Text200 = Annotated[Annotated[str, StringConstraints(max_length=200)] | None, _Blank]
Text100 = Annotated[Annotated[str, StringConstraints(max_length=100)] | None, _Blank]
Label = Annotated[Annotated[str, StringConstraints(max_length=50)] | None, _Blank]
LongText = Annotated[Annotated[str, StringConstraints(max_length=10_000)] | None, _Blank]
HttpsUrl = Annotated[
    Annotated[str, StringConstraints(max_length=500)] | None,
    _Blank,
    AfterValidator(_https_only),
]
LinkedInUrl = Annotated[
    Annotated[str, StringConstraints(max_length=300)] | None,
    _Blank,
    AfterValidator(_linkedin),
]
BirthdayText = Annotated[
    Annotated[str, StringConstraints(max_length=40)] | None, _Blank, AfterValidator(_birthday)
]
SlackHandle = Annotated[
    Annotated[str, StringConstraints(max_length=100, pattern=r"^@?[\w.\-]+$")] | None,
    _Blank,
    AfterValidator(_strip_at),
]


class _Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AppearanceIn(_Input):
    """A-01 to A-05: theme, palette and/or density from Settings or the header (ADR-0015)."""

    theme: Theme | None = None
    palette: Palette | None = None
    density: Density | None = None


class EmailIn(_Input):
    email: EmailStr = Field(max_length=320)
    label: Label = None
    is_primary: bool = False


class PhoneIn(_Input):
    number: str = Field(min_length=3, max_length=50)
    label: Label = None


Text20 = Annotated[Annotated[str, StringConstraints(max_length=20)] | None, _Blank]
Text300 = Annotated[Annotated[str, StringConstraints(max_length=300)] | None, _Blank]


class AddressIn(_Input):
    """C-19: a postal address; country and region are normalised on save (ADR-0021)."""

    label: Label = None
    street: Text300 = None
    city: Text100 = None
    region: Text100 = None
    postal_code: Text20 = None
    country: Text100 = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not any((self.street, self.city, self.region, self.postal_code, self.country)):
            raise ValueError("an address needs a street, city, state, postal code or country")
        return self


class CustomFieldIn(_Input):
    """C-11: one key/value pair, e.g. ("Epic role", "Beaker analyst")."""

    name: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=500)


def _check_custom_fields(fields: list[CustomFieldIn]) -> list[CustomFieldIn]:
    seen: set[str] = set()
    for item in fields:
        key = item.name.lower()
        if key in seen:
            raise ValueError(f"field “{item.name}” is listed twice")
        seen.add(key)
    return fields


def _check_emails(emails: list[EmailIn]) -> list[EmailIn]:
    """C-02: no duplicates (case-insensitive); exactly one primary when any exist."""
    seen: set[str] = set()
    for item in emails:
        key = str(item.email).lower()
        if key in seen:
            raise ValueError(f"email {item.email} is listed twice")
        seen.add(key)
    primaries = sum(1 for e in emails if e.is_primary)
    if primaries > 1:
        raise ValueError("only one email can be primary")
    if emails and primaries == 0:
        emails[0].is_primary = True
    return emails


class ContactFields(_Input):
    first_name: Text100 = None
    last_name: Text100 = None
    nickname: Text100 = None
    company: Text200 = None
    title: Text200 = None
    team: Text200 = None
    department: Text200 = None
    location: Text200 = None
    manager_id: int | None = None
    works_on: LongText = None
    notes: LongText = None
    slack_handle: SlackHandle = None
    slack_url: HttpsUrl = None
    teams_url: HttpsUrl = None
    linkedin_url: LinkedInUrl = None  # C-18
    pronunciation: Text200 = None
    birthday: BirthdayText = None  # C-20
    is_favorite: bool = False


class ContactCreate(ContactFields):
    display_name: str = Field(min_length=1, max_length=200)
    contact_type_id: int
    emails: list[EmailIn] = Field(default_factory=list, max_length=20)
    phones: list[PhoneIn] = Field(default_factory=list, max_length=20)
    addresses: list[AddressIn] = Field(default_factory=list, max_length=10)  # C-19
    custom_fields: list[CustomFieldIn] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _emails_valid(self) -> Self:
        _check_emails(self.emails)
        _check_custom_fields(self.custom_fields)
        return self


class ContactUpdate(ContactFields):
    """PATCH body: only fields that are sent are changed; lists replace the stored list."""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_type_id: int | None = None
    emails: list[EmailIn] | None = Field(default=None, max_length=20)
    phones: list[PhoneIn] | None = Field(default=None, max_length=20)
    addresses: list[AddressIn] | None = Field(default=None, max_length=10)  # C-19
    custom_fields: list[CustomFieldIn] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def _emails_valid(self) -> Self:
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be empty")
        if "contact_type_id" in self.model_fields_set and self.contact_type_id is None:
            raise ValueError("contact_type_id cannot be empty")
        if self.emails is not None:
            _check_emails(self.emails)
        if self.custom_fields is not None:
            _check_custom_fields(self.custom_fields)
        return self


# ---------------------------------------------------------------- output


class _Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ContactTypeOut(_Output):
    id: int
    name: str


class ContactRef(_Output):
    id: int
    display_name: str
    title: str | None
    team: str | None
    company: str | None


class EmailOut(_Output):
    email: str
    label: str | None
    is_primary: bool


class PhoneOut(_Output):
    number: str
    label: str | None


class AddressOut(_Output):
    label: str | None
    street: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    country_code: str | None


class TagOut(_Output):
    id: int
    name: str
    color: str | None = None


class ListRef(_Output):
    id: int
    name: str


class CustomFieldOut(_Output):
    name: str
    value: str


class ActivityOut(_Output):
    id: int
    kind: str
    occurred_on: date
    summary: str


class ContactLinks(BaseModel):
    """M-04: one-click actions for the card."""

    mailto: str | None
    teams: str | None
    slack: str | None
    tel: str | None


class ContactOut(_Output):
    id: int
    display_name: str
    first_name: str | None
    last_name: str | None
    nickname: str | None
    contact_type: ContactTypeOut
    company: str | None
    title: str | None
    team: str | None
    department: str | None
    location: str | None
    manager: ContactRef | None
    reports: list[ContactRef]
    works_on: str | None
    notes: str | None
    slack_handle: str | None
    slack_url: str | None
    teams_url: str | None
    linkedin_url: str | None = None  # C-18
    pronunciation: str | None
    birthday: str | None = None  # C-20
    is_favorite: bool
    emails: list[EmailOut]
    phones: list[PhoneOut]
    addresses: list[AddressOut] = []  # C-19
    tags: list[TagOut]
    lists: list[ListRef]
    links: ContactLinks
    archived: bool
    has_photo: bool = False
    # Detail views only (card, single-contact API); None in lists and search results.
    custom_fields: list[CustomFieldOut] | None = None
    activities: list[ActivityOut] | None = None
    last_contact: date | None = None
    created_at: datetime
    updated_at: datetime
