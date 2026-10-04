"""Places, local time, the map, "near" and directions (C-22, C-23, S-13, S-14, M-06; ADR-0023)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import create_contact, place_missing
from app.geo import find_place, local_time_for, miles_between, place_of, reach_at
from app.maps import directions_url
from app.models import Contact, ContactAddress, ContactType
from app.privacy import COOKIE
from app.schemas import ContactCreate
from app.search import SearchFilters, search

# ---------------------------------------------------------------- placing an address (pure)


@pytest.mark.req("C-22")
@pytest.mark.parametrize(
    ("city", "region", "postal", "country", "precision", "zone"),
    [
        ("Olathe", "KS", "66061", "US", "zip", "America/Chicago"),
        ("Goodland", "KS", None, "US", "city", "America/Denver"),  # western Kansas: Mountain
        ("St. Louis", "MO", None, "US", "city", "America/Chicago"),
        (None, "KS", None, "US", "state", "America/Chicago"),
        ("Toronto", "ON", None, "CA", "city", "America/Toronto"),
        ("München", None, None, "DE", "city", "Europe/Berlin"),
        ("Cologne", None, None, "DE", "city", "Europe/Berlin"),
        (None, None, None, "GB", "country", "Europe/London"),
    ],
)  # fmt: skip
def test_addresses_are_placed_from_offline_data(
    city: str | None, region: str | None, postal: str | None, country: str,
    precision: str, zone: str,
) -> None:  # fmt: skip
    found = place_of(city=city, region=region, postal_code=postal, country_code=country)
    assert found is not None
    assert (found.precision, found.time_zone) == (precision, zone)


@pytest.mark.req("C-22", "S-14")
def test_unknown_places_and_typed_places() -> None:
    assert place_of(city="Nowhere", region="ZZ", postal_code=None, country_code="US") is None
    assert find_place("Denver, CO") is not None
    assert find_place("66061") is not None
    assert find_place("Kansas") is not None
    assert find_place("Atlantis, XX") is None
    olathe, denver = find_place("66061"), find_place("Denver, CO")
    assert olathe is not None
    assert denver is not None
    assert (
        540
        < miles_between(olathe.latitude, olathe.longitude, denver.latitude, denver.longitude)
        < 560
    )


# ---------------------------------------------------------------- local time (pure)


@pytest.mark.req("C-23")
@pytest.mark.parametrize(
    ("when", "reach"),
    [
        ("2026-10-05 10:00", "work"), ("2026-10-05 08:30", "edge"), ("2026-10-05 17:30", "edge"),
        ("2026-10-05 22:00", "night"), ("2026-10-04 12:00", "weekend"), ("2026-10-04 23:00", "night"),
    ],
)  # fmt: skip
def test_good_time_to_reach(when: str, reach: str) -> None:
    assert reach_at(datetime.fromisoformat(when)) == reach


class _A:
    def __init__(self, zone: str | None, precision: str, region: str, country: str) -> None:
        self.time_zone, self.place_precision, self.region, self.country_code = (
            zone, precision, region, country,
        )  # fmt: skip


@pytest.mark.req("C-23")
def test_local_time_uses_the_first_placed_address_and_flags_split_states() -> None:
    noon_utc = datetime(2026, 7, 6, 17, 0, tzinfo=ZoneInfo("UTC"))
    exact = local_time_for([_A(None, "none", "", "US"), _A("America/Chicago", "zip", "KS", "US")],
                           now=noon_utc)  # fmt: skip
    assert exact is not None
    assert (exact.text, exact.abbreviation, exact.approximate) == ("12:00 PM", "CDT", False)
    rough = local_time_for([_A("America/Chicago", "state", "KS", "US")], now=noon_utc)
    assert rough is not None
    assert rough.approximate  # Kansas spans two zones
    assert local_time_for([]) is None


# ---------------------------------------------------------------- directions (pure)


@pytest.mark.req("M-06")
def test_directions_links() -> None:
    def q(url: str | None) -> dict[str, list[str]]:
        assert url
        return parse_qs(urlsplit(url).query)

    one = directions_url(["12 Elm St, Olathe, KS 66061"])
    assert one is not None
    assert one.startswith("https://www.google.com/maps/dir/?api=1&")
    assert "origin" not in q(one)  # Google starts from the device's location
    two = q(directions_url(["A", "B"]))
    assert (two["origin"], two["destination"], two["travelmode"]) == (["A"], ["B"], ["driving"])
    route = q(directions_url(["A", "B", "C", "D"]))
    assert route["waypoints"] == ["B|C"]
    assert len(q(directions_url([str(i) for i in range(20)]))["waypoints"][0].split("|")) == 9
    assert directions_url(["A"], "apple") == "https://maps.apple.com/?daddr=A&dirflg=d"
    assert directions_url(["A", "B"], "apple") == "https://maps.apple.com/?saddr=A&daddr=B&dirflg=d"
    assert (directions_url(["A", "B", "C"], "apple") or "").startswith("https://www.google.com/")
    assert directions_url([]) is None


# ---------------------------------------------------------------- stored, searched, shown


def _type_id(session: Session) -> int:
    found = session.scalars(select(ContactType.id).order_by(ContactType.sort_order)).first()
    if found is not None:
        return found
    created = ContactType(name="Friend")
    session.add(created)
    session.flush()
    return created.id


def _contact(session: Session, name: str, **fields: Any) -> Contact:
    return create_contact(
        session,
        ContactCreate.model_validate(
            {"display_name": name, "contact_type_id": _type_id(session), **fields}
        ),
    )


OLATHE = {"label": "home", "street": "12 Elm St", "city": "Olathe", "region": "KS",
          "postal_code": "66061"}  # fmt: skip
OVERLAND = {"label": "work", "street": "1 Office Rd", "city": "Overland Park", "region": "KS",
            "postal_code": "66210"}  # fmt: skip
DENVER = {"label": "work", "city": "Denver", "region": "CO"}


@pytest.mark.req("C-22")
def test_saving_places_an_address_and_old_ones_are_filled_in(db_session: Session) -> None:
    ana = _contact(db_session, "Ana", addresses=[OLATHE])
    stored = ana.addresses[0]
    assert (stored.place_precision, stored.time_zone) == ("zip", "America/Chicago")
    old = ContactAddress(contact_id=ana.id, city="Denver", region="CO", country_code="US")
    db_session.add(old)
    db_session.flush()
    assert place_missing(db_session) == 1
    assert (old.place_precision, old.time_zone) == ("city", "America/Denver")
    assert place_missing(db_session) == 0  # done once


@pytest.mark.req("S-14", "S-13")
def test_near_ids_and_unplaced_filters(db_session: Session) -> None:
    ana = _contact(db_session, "Ana", addresses=[OLATHE])
    bo = _contact(db_session, "Bo", addresses=[OVERLAND])
    _contact(db_session, "Cy", addresses=[DENVER])
    nobody = _contact(db_session, "Dee")
    olathe = find_place("Olathe, KS")
    assert olathe
    near = SearchFilters(near_lat=olathe.latitude, near_lon=olathe.longitude, near_miles=25)
    assert {h.contact.display_name for h in search(db_session, "", near)} == {"Ana", "Bo"}
    picked = SearchFilters(ids=(ana.id, bo.id))
    assert {h.contact.display_name for h in search(db_session, "", picked)} == {"Ana", "Bo"}
    lost = SearchFilters(unplaced=True)
    assert [h.contact.id for h in search(db_session, "", lost)] == [nobody.id]


TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.mark.req("C-23", "M-06", "S-14")
def test_card_and_results_show_local_time_directions_and_distance(
    client: TestClient, db_session: Session
) -> None:
    ana = _contact(db_session, "Ana Place", addresses=[OLATHE])
    _contact(db_session, "Cy Place", addresses=[DENVER])
    card = client.get(f"/contacts/{ana.id}").text
    assert 'data-tz="America/Chicago"' in card
    assert 'data-testid="action-directions"' in card
    assert "destination=12+Elm+St%2C+Olathe%2C+KS+66061%2C+United+States" in card
    assert f'href="/?near=contact:{ana.id}&amp;within=50"' in card

    near = client.get("/?near=Olathe%2C+KS&within=25").text
    assert "Within 25 mi of Olathe, KS" in near
    assert 'data-testid="distance">' in near
    assert "Cy Place" not in near
    missing = client.get("/?near=Atlantis%2C+XX").text
    assert "find “Atlantis, XX”" in missing
    assert "Ana Place" not in missing
    from_card = client.get(f"/?near=contact:{ana.id}&within=10").text
    assert "Within 10 mi of Ana Place" in from_card


@pytest.mark.req("M-06")
def test_apple_maps_can_be_chosen(client: TestClient, db_session: Session) -> None:
    ana = _contact(db_session, "Ana Place", addresses=[OLATHE])
    token = TOKEN.search(client.get("/settings").text)
    assert token
    saved = client.post(
        "/settings/maps", data={"csrf_token": token.group(1), "provider": "apple"},
        follow_redirects=False,
    )  # fmt: skip
    assert saved.status_code == 303
    assert "https://maps.apple.com/?daddr=" in client.get(f"/contacts/{ana.id}").text
    assert 'data-maps-provider="apple"' in client.get("/").text
    bad = client.post("/settings/maps", data={"csrf_token": token.group(1), "provider": "x"})
    assert bad.status_code == 422


@pytest.mark.req("S-13", "P-02")
def test_map_data_counts_states_and_respects_presenting(
    client: TestClient, db_session: Session
) -> None:
    _contact(db_session, "Ana Place", addresses=[OLATHE, OVERLAND])
    _contact(db_session, "Cy Place", addresses=[DENVER])
    _contact(db_session, "Dee Place")
    _contact(db_session, "Eve Abroad", addresses=[{"city": "Toronto", "country": "Canada"}])
    data = client.get("/map/data?q=place").json()
    assert data["people"] == 3  # "place" matches the three with it in their name
    assert data["states"] == {"Kansas": 1, "Colorado": 1}  # Ana counts once
    assert data["unplaced"] == 1
    assert len(data["points"]) == 3
    assert {p["name"] for p in data["points"]} == {"Ana Place", "Cy Place"}
    everyone = client.get("/map/data").json()
    assert everyone["countries"] == {"840": 2, "124": 1}  # ISO numeric: US, Canada
    work = client.get("/map/data?q=place&addr=work").json()
    assert {p["label"] for p in work["points"]} == {"work"}
    assert work["points"][0]["directions"].startswith("https://www.google.com/maps/dir/")

    client.cookies.set(COOKIE, "1")  # presenting hides personal (home) addresses by default
    shown = client.get("/map/data?q=place").json()
    assert {p["label"] for p in shown["points"]} == {"work"}
    page = client.get("/?view=map").text
    assert 'data-testid="contact-map"' in page
    assert "vendor/leaflet/leaflet.js" in page
