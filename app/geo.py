"""Places for addresses: coordinates, IANA time zone and precision, from offline data
(C-22, ADR-0023), plus local time (C-23) and distances (S-14). No network, ever (N-04).

* US: the ``zipcodes`` package — ZIP first, then city + state, then the state itself.
* Elsewhere: ``app/data/world_cities.tsv.gz`` (GeoNames cities of 15,000+, CC BY 4.0) — city +
  country, then the country (its largest city).
"""

from __future__ import annotations

import gzip
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import zipcodes

Precision = Literal["zip", "city", "state", "country", "none"]
WORLD_CITIES = Path(__file__).parent / "data" / "world_cities.tsv.gz"
EARTH_MILES = 3958.8


@dataclass(frozen=True)
class Place:
    latitude: float
    longitude: float
    time_zone: str | None
    precision: Precision


def _key(text: str) -> str:
    """'St. Louis' -> 'saint louis'; 'Zürich' -> 'zurich'; accents and case don't count."""
    plain = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    words = re.sub(r"[.,'\-]", " ", plain.lower()).split()
    return " ".join("saint" if w in {"st", "ste"} else "fort" if w == "ft" else w for w in words)


# ---------------------------------------------------------------- the US


@dataclass(frozen=True)
class _Spot:
    lat: float
    lon: float
    zone: str | None


def _centre(spots: Iterable[_Spot]) -> _Spot:
    items = list(spots)
    zones = Counter(s.zone for s in items if s.zone)
    return _Spot(
        sum(s.lat for s in items) / len(items),
        sum(s.lon for s in items) / len(items),
        zones.most_common(1)[0][0] if zones else None,
    )


@dataclass(frozen=True)
class _UsIndex:
    zips: dict[str, _Spot]
    cities: dict[tuple[str, str], _Spot]  # (state, city key) -> centre of its ZIPs
    states: dict[str, _Spot]
    state_zones: dict[str, frozenset[str]]


@cache
def _us() -> _UsIndex:
    zips: dict[str, _Spot] = {}
    by_city: dict[tuple[str, str], list[_Spot]] = defaultdict(list)
    by_state: dict[str, list[_Spot]] = defaultdict(list)
    rows: list[dict[str, Any]] = zipcodes.list_all()  # type: ignore[no-untyped-call]
    for row in rows:
        try:
            spot = _Spot(float(row["lat"]), float(row["long"]), row.get("timezone") or None)
        except (TypeError, ValueError):
            continue
        zips[row["zip_code"]] = spot
        state = str(row["state"]).upper()
        by_state[state].append(spot)
        for name in {row["city"], *row.get("acceptable_cities", [])}:
            if name:
                by_city[(state, _key(str(name)))].append(spot)
    states = {s: _centre(v) for s, v in by_state.items()}
    # A ZIP without a zone takes its state's usual one.
    zips = {z: s if s.zone else _Spot(s.lat, s.lon, None) for z, s in zips.items()}
    return _UsIndex(
        zips=zips,
        cities={k: _centre(v) for k, v in by_city.items()},
        states=states,
        state_zones={s: frozenset(x.zone for x in v if x.zone) for s, v in by_state.items()},
    )


def _us_place(city: str | None, region: str | None, postal_code: str | None) -> Place | None:
    us = _us()
    state = (region or "").upper()
    zip5 = re.match(r"^\s*(\d{5})", postal_code or "")
    if zip5 and (spot := us.zips.get(zip5[1])):
        zone = spot.zone or (us.states[state].zone if state in us.states else None)
        return Place(spot.lat, spot.lon, zone, "zip")
    if city and state and (spot := us.cities.get((state, _key(city)))):
        return Place(spot.lat, spot.lon, spot.zone, "city")
    if city and not state:  # a city in exactly one state
        found = [v for (s, c), v in us.cities.items() if c == _key(city)]
        if len(found) == 1:
            return Place(found[0].lat, found[0].lon, found[0].zone, "city")
    if state in us.states:
        spot = us.states[state]
        return Place(spot.lat, spot.lon, spot.zone, "state")
    return None


# ---------------------------------------------------------------- the rest of the world


@dataclass(frozen=True)
class _City:
    lat: float
    lon: float
    population: int
    zone: str


@dataclass(frozen=True)
class _WorldIndex:
    cities: dict[tuple[str, str], _City]  # (country, city key) -> largest such city
    countries: dict[str, _City]  # country -> its largest city
    country_zones: dict[str, frozenset[str]]


@cache
def _world() -> _WorldIndex:
    cities: dict[tuple[str, str], _City] = {}
    countries: dict[str, _City] = {}
    zones: dict[str, set[str]] = defaultdict(set)
    with gzip.open(WORLD_CITIES, "rt", encoding="utf-8") as handle:
        for line in handle:
            name, alternates, country, lat, lon, population, zone = line.rstrip("\n").split("\t")
            city = _City(float(lat), float(lon), int(population), zone)
            zones[country].add(zone)
            if country not in countries or city.population > countries[country].population:
                countries[country] = city
            for label in (name, *filter(None, alternates.split(";"))):
                key = (country, _key(label))
                if key not in cities or city.population > cities[key].population:
                    cities[key] = city
    return _WorldIndex(cities, countries, {c: frozenset(z) for c, z in zones.items()})


def _world_place(city: str | None, country_code: str) -> Place | None:
    world = _world()
    if city and (found := world.cities.get((country_code, _key(city)))):
        return Place(found.lat, found.lon, found.zone, "city")
    if found := world.countries.get(country_code):
        return Place(found.lat, found.lon, found.zone, "country")
    return None


# ---------------------------------------------------------------- public


def place_of(
    *,
    city: str | None,
    region: str | None,
    postal_code: str | None,
    country_code: str | None,
) -> Place | None:
    """Where an (already normalised, ADR-0021) address is, as precisely as the data allows."""
    if country_code in (None, "US"):
        found = _us_place(city, region, postal_code)
        if found or country_code == "US":
            return found
        return None
    return _world_place(city, country_code)


def zone_is_approximate(
    precision: str | None, region: str | None, country_code: str | None
) -> bool:
    """A state- or country-level zone where that state or country spans several zones."""
    if precision == "state" and region:
        return len(_us().state_zones.get(region.upper(), frozenset())) > 1
    if precision == "country" and country_code:
        return len(_world().country_zones.get(country_code, frozenset())) > 1
    return False


def find_place(text: str) -> Place | None:
    """S-14: a place typed in a "near" box — a ZIP, "City, ST", "City, Country" or a state."""
    raw = " ".join(text.split())
    if re.fullmatch(r"\d{5}(-\d{4})?", raw):
        return _us_place(None, None, raw)
    from app.addresses import find_country, find_region  # app.addresses is pure; no cycle

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        city, rest = ", ".join(parts[:-1]), parts[-1]
        state = find_region(rest, "US")
        if state:
            return _us_place(city, state, None)
        country = find_country(rest)
        if country:
            return place_of(city=city, region=None, postal_code=None, country_code=country.code)
        return None
    if state := find_region(raw, "US"):
        return _us_place(None, state, None)
    return _us_place(raw, None, None) or _world_place_by_name(raw)


def _world_place_by_name(city: str) -> Place | None:
    world = _world()
    best = max(
        (c for (_, name), c in world.cities.items() if name == _key(city)),
        key=lambda c: c.population,
        default=None,
    )
    return Place(best.lat, best.lon, best.zone, "city") if best else None


def miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- local time (C-23)

Reach = Literal["work", "edge", "weekend", "night"]
REACH_LABELS: dict[Reach, str] = {
    "work": "Working hours",
    "edge": "Early or late",
    "weekend": "Weekend",
    "night": "Night",
}


def reach_at(local: datetime) -> Reach:
    """Weekdays 9-17 work, 8-9 and 17-21 the edges; weekends 9-21; otherwise night."""
    hour = local.hour
    if local.weekday() >= 5:
        return "weekend" if 9 <= hour < 21 else "night"
    if 9 <= hour < 17:
        return "work"
    return "edge" if 8 <= hour < 9 or 17 <= hour < 21 else "night"


@dataclass(frozen=True)
class LocalTime:
    zone: str
    text: str  # "2:41 PM"
    abbreviation: str  # "CDT"
    reach: Reach
    approximate: bool

    @property
    def reach_label(self) -> str:
        return REACH_LABELS[self.reach]


class _AddressPlace(Protocol):
    @property
    def time_zone(self) -> str | None: ...
    @property
    def place_precision(self) -> str | None: ...
    @property
    def region(self) -> str | None: ...
    @property
    def country_code(self) -> str | None: ...


def local_time_for(
    addresses: Iterable[_AddressPlace], *, now: datetime | None = None
) -> LocalTime | None:
    """C-23: the local time at the first address that has a time zone."""
    for address in addresses:
        if address.time_zone:
            approximate = zone_is_approximate(
                address.place_precision, address.region, address.country_code
            )
            return local_time(address.time_zone, now=now, approximate=approximate)
    return None


def local_time(
    zone: str, *, now: datetime | None = None, approximate: bool = False
) -> LocalTime | None:
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = (now or datetime.now(tz)).astimezone(tz)
    text = local.strftime("%I:%M %p").lstrip("0")
    return LocalTime(zone, text, local.tzname() or "", reach_at(local), approximate)
