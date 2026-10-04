"""Postal addresses: country and state normalisation and display (C-19, ADR-0021).

Pure functions. Countries are matched to ISO 3166-1 alpha-2 codes and states/provinces
to ISO 3166-2 subdivisions using ``pycountry``'s bundled data (no network, N-04), so a
later map or time-zone feature can rely on codes rather than free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import Protocol

import pycountry

# Everyday names pycountry doesn't list (it knows "United States of America", "USA", "US").
_COUNTRY_ALIASES = {
    "uk": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "great britain": "GB",
    "britain": "GB", "northern ireland": "GB", "america": "US", "united states": "US",
    "u s": "US", "u s a": "US", "deutschland": "DE", "holland": "NL", "the netherlands": "NL",
    "south korea": "KR", "korea": "KR", "russia": "RU", "vietnam": "VN", "taiwan": "TW",
    "czech republic": "CZ", "ivory coast": "CI", "uae": "AE", "méxico": "MX", "españa": "ES",
}  # fmt: skip

# AP-style and other common US state abbreviations ("Kan.", "Calif.") -> USPS code.
_US_ABBREVIATIONS = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA", "colo": "CO",
    "conn": "CT", "del": "DE", "fla": "FL", "ill": "IL", "ind": "IN", "kan": "KS",
    "kans": "KS", "ky": "KY", "la": "LA", "md": "MD", "mass": "MA", "mich": "MI",
    "minn": "MN", "miss": "MS", "mont": "MT", "neb": "NE", "nebr": "NE", "nev": "NV",
    "okla": "OK", "ore": "OR", "oreg": "OR", "pa": "PA", "penn": "PA", "penna": "PA",
    "tenn": "TN", "tex": "TX", "vt": "VT", "va": "VA", "wash": "WA", "wis": "WI",
    "wisc": "WI", "wyo": "WY", "ga": "GA", "mo": "MO", "n h": "NH", "n j": "NJ",
    "n m": "NM", "n y": "NY", "n c": "NC", "n d": "ND", "s c": "SC", "s d": "SD",
    "r i": "RI", "w va": "WV", "d c": "DC",
}  # fmt: skip


def _key(value: str) -> str:
    """'U.S.A.' -> 'u s a', '  Kan. ' -> 'kan'."""
    return " ".join(re.sub(r"[.\-_,]", " ", value).lower().split())


@dataclass(frozen=True)
class Country:
    code: str  # ISO 3166-1 alpha-2
    name: str  # display name, e.g. "United States"


@cache
def find_country(value: str) -> Country | None:
    """The country a typed name or code means, or None."""
    text = value.strip()
    if not text:
        return None
    code = _COUNTRY_ALIASES.get(_key(text))
    if code is None:
        compact = _key(text).replace(" ", "")
        candidates = [text, compact.upper()] if len(compact) in {2, 3} else [text]
        for candidate in candidates:
            try:
                code = pycountry.countries.lookup(candidate).alpha_2
                break
            except LookupError:
                continue
    if code is None:
        return None
    record = pycountry.countries.lookup(code)
    name = getattr(record, "common_name", None) or record.name
    return Country(code=code, name=str(name))


@cache
def _subdivisions(country_code: str) -> dict[str, str]:
    """Lower-cased code suffix or name -> stored region for one country."""
    out: dict[str, str] = {}
    for sub in pycountry.subdivisions:  # once per country (cached)
        if sub.country_code != country_code:
            continue
        suffix = sub.code.split("-", 1)[1]
        # Letters ("KS", "ON") read well; numeric codes ("FR-75") would not, so keep the name.
        stored = suffix if suffix.isalpha() else str(sub.name)
        out[suffix.lower()] = stored
        out[_key(str(sub.name))] = stored
    if country_code == "US":
        out.update({k: v for k, v in _US_ABBREVIATIONS.items() if k not in out})
    return out


def find_region(value: str, country_code: str) -> str | None:
    """The stored form of a state or province within a country, or None."""
    key = _key(value)
    return _subdivisions(country_code).get(key) if key else None


@dataclass(frozen=True)
class NormalAddress:
    street: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    country_code: str | None


def _split_city(value: str, country_code: str) -> tuple[str, str] | None:
    """'Shawnee Mission KS' -> ('Shawnee Mission', 'KS'): a city typed into the region."""
    words = [w for w in re.split(r"[,\s]+", value) if w]
    for n in (1, 2, 3):
        if len(words) > n and (stored := find_region(" ".join(words[-n:]), country_code)):
            return " ".join(words[:-n]), stored
    return None


def normalize_address(
    *,
    street: str | None,
    city: str | None,
    region: str | None,
    postal_code: str | None,
    country: str | None,
    home_region: str,
) -> NormalAddress:
    """Tidy one address as it is saved (ADR-0021).

    * Country -> its standard name and ISO code when recognised, else kept as typed.
    * Region -> the subdivision code ("Kansas", "Kan." -> "KS") when recognised.
    * A city typed into the region ("Raymore, MO") is split out when the city is empty.
    * No country, but a region of the home country -> the home country.
    """

    def clean(value: str | None) -> str | None:
        if value is None:
            return None
        lines = [" ".join(line.split()) for line in value.splitlines()]
        text = "\n".join(line for line in lines if line)
        return text or None

    street, city, region, postal_code, country = (
        clean(v) for v in (street, city, region, postal_code, country)
    )
    found = find_country(country) if country else None
    code = found.code if found else None
    lookup = code or (None if country else home_region.upper())
    if region and lookup:
        stored = find_region(region, lookup)
        if stored is None and not city and (split := _split_city(region, lookup)):
            city, stored = split
        if stored is not None:
            region = stored
            if code is None and not country:  # the state belongs to the home country
                found = find_country(lookup)
                code = found.code if found else None
    return NormalAddress(
        street=street,
        city=city,
        region=region,
        postal_code=postal_code.upper() if postal_code else None,
        country=found.name if found else country,
        country_code=code,
    )


def address_lines(
    *,
    street: str | None,
    city: str | None,
    region: str | None,
    postal_code: str | None,
    country: str | None,
    country_code: str | None,
    home_region: str,
) -> list[str]:
    """Display lines, e.g. ["12 Elm St", "Olathe, KS 66061"]; the home country is left out."""
    lines = (street or "").splitlines()
    place = ", ".join(p for p in (city, " ".join(filter(None, [region, postal_code]))) if p)
    if place:
        lines.append(place)
    if country and (country_code or "").upper() != home_region.upper():
        lines.append(country)
    return [line for line in lines if line.strip()]


class AddressLike(Protocol):
    @property
    def street(self) -> str | None: ...
    @property
    def city(self) -> str | None: ...
    @property
    def region(self) -> str | None: ...
    @property
    def postal_code(self) -> str | None: ...
    @property
    def country(self) -> str | None: ...
    @property
    def country_code(self) -> str | None: ...


def lines_of(address: AddressLike, home_region: str) -> list[str]:
    """Display lines of a stored address (card, preview, exports)."""
    return address_lines(
        street=address.street,
        city=address.city,
        region=address.region,
        postal_code=address.postal_code,
        country=address.country,
        country_code=address.country_code,
        home_region=home_region,
    )


def country_name(code: str) -> str:
    """'US' -> 'United States' (the code itself when unknown)."""
    found = find_country(code)
    return found.name if found else code


def state_name(code: str | None) -> str | None:
    """'KS' -> 'Kansas' (US states, for the map's outlines)."""
    if not code:
        return None
    return {v: k for k, v in _us_state_names().items()}.get(code.upper())


@cache
def _us_state_names() -> dict[str, str]:
    return {
        str(sub.name): sub.code.split("-", 1)[1]
        for sub in pycountry.subdivisions
        if sub.country_code == "US"
    }


def country_number(code: str | None) -> str | None:
    """'CA' -> '124': ISO 3166-1 numeric, as the world map's outlines are keyed."""
    if not code:
        return None
    try:
        return str(pycountry.countries.lookup(code).numeric)
    except LookupError:
        return None


def one_line(lines: list[str]) -> str:
    return ", ".join(lines)
