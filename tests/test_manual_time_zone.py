"""C-26: a time zone set by hand, used only when no address gives one (ADR-0035)."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import to_out
from app.exchange import export_csv
from app.exports import ExportOptions, build_export
from app.geo import local_time_for, normalize_zone
from app.models import Contact, ContactType
from app.privacy import PRESENTING, Presenting, PrivacySettings

NOON_UTC = datetime(2026, 7, 6, 17, 0, tzinfo=ZoneInfo("UTC"))


class _A:
    def __init__(self, zone: str | None, precision: str = "zip") -> None:
        self.time_zone, self.place_precision, self.region, self.country_code = (
            zone, precision, "KS", "US",
        )  # fmt: skip


# ---------------------------------------------------------------- the zone itself (pure)


@pytest.mark.req("C-26")
@pytest.mark.parametrize(
    ("typed", "zone"),
    [
        ("America/Chicago", "America/Chicago"),
        ("america/chicago", "America/Chicago"),
        ("  Europe/London ", "Europe/London"),
        ("Central", "America/Chicago"),
        ("eastern", "America/New_York"),
        ("ET", "America/New_York"),
        ("Mountain Time", "America/Denver"),
        ("pacific", "America/Los_Angeles"),
        ("UTC", "UTC"),
        ("", None),
        (None, None),
    ],
)  # fmt: skip
def test_zones_are_normalised(typed: str | None, zone: str | None) -> None:
    assert normalize_zone(typed) == zone


@pytest.mark.req("C-26")
@pytest.mark.parametrize("typed", ["Mars/Base", "Chicago", "../etc/passwd", "America/", "x" * 80])
def test_unknown_zones_are_refused(typed: str) -> None:
    with pytest.raises(ValueError, match="time zone"):
        normalize_zone(typed)


@pytest.mark.req("C-26", "C-23")
def test_an_address_zone_wins_and_the_hand_set_one_fills_the_gap() -> None:
    by_hand = local_time_for([], manual="America/Chicago", now=NOON_UTC)
    assert by_hand is not None
    assert (by_hand.text, by_hand.abbreviation) == ("12:00 PM", "CDT")
    assert by_hand.manual
    assert not by_hand.approximate  # the person said so; no "approx."
    unplaced = local_time_for([_A(None)], manual="America/Chicago", now=NOON_UTC)
    assert unplaced is not None
    assert unplaced.manual
    wins = local_time_for([_A("America/New_York")], manual="Asia/Tokyo", now=NOON_UTC)
    assert wins is not None
    assert (wins.zone, wins.manual) == ("America/New_York", False)
    # An address that only knows the state (Kansas spans two zones) gives way to a zone chosen by hand.
    guess = local_time_for([_A("America/Chicago", "state")], now=NOON_UTC)
    assert guess is not None
    assert guess.approximate
    assert not guess.manual
    chosen = local_time_for([_A("America/Chicago", "state")], manual="America/Denver", now=NOON_UTC)
    assert chosen is not None
    assert (chosen.zone, chosen.manual, chosen.approximate) == ("America/Denver", True, False)
    assert local_time_for([], manual=None) is None
    assert local_time_for([], manual="Not/AZone") is None  # a stale value never breaks a page


# ---------------------------------------------------------------- saving it


def _type_id(session: Session) -> int:
    return int(
        session.scalars(select(ContactType.id).order_by(ContactType.sort_order)).first() or 0
    )


def _make(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    res = client.post(
        "/api/contacts",
        json={"display_name": name, "contact_type_id": _type_id(session), **fields},
    )
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


@pytest.mark.req("C-26")
def test_the_api_saves_normalises_and_clears_it(client: TestClient, db_session: Session) -> None:
    cid = _make(client, db_session, "Zed Zone", time_zone="central")
    assert client.get(f"/api/contacts/{cid}").json()["time_zone"] == "America/Chicago"
    bad = client.post(
        "/api/contacts",
        json={
            "display_name": "Bad Zone",
            "contact_type_id": _type_id(db_session),
            "time_zone": "Mars/Base",
        },
    )
    assert bad.status_code == 422
    cleared = client.patch(f"/api/contacts/{cid}", json={"time_zone": None})
    assert cleared.status_code == 200
    assert cleared.json()["time_zone"] is None
    other = _make(client, db_session, "Plain Contact")
    assert client.get(f"/api/contacts/{other}").json()["time_zone"] is None


@pytest.mark.req("C-26")
def test_the_form_offers_the_field_and_keeps_the_choice(
    client: TestClient, db_session: Session
) -> None:
    page = client.get("/contacts/new").text
    assert 'name="time_zone"' in page
    assert 'list="time-zones"' in page
    assert '<option value="America/Chicago"' in page
    assert "takes the place of this one" in page  # the hint says an address wins
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert token
    form = {
        "csrf_token": token.group(1),
        "display_name": "Form Zone",
        "contact_type_id": str(_type_id(db_session)),
        "time_zone": "Pacific",
    }
    saved = client.post("/contacts", data=form, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    contact = db_session.scalars(select(Contact).where(Contact.display_name == "Form Zone")).one()
    assert contact.time_zone == "America/Los_Angeles"
    edit = client.get(f"/contacts/{contact.id}/edit").text
    assert re.search(r'name="time_zone"[^>]*value="America/Los_Angeles"', edit)
    wrong = client.post(
        "/contacts", data={**form, "display_name": "Wrong Zone", "time_zone": "Narnia"}
    )
    assert wrong.status_code == 422
    assert "time zone" in wrong.text.lower()
    assert "Narnia" in wrong.text  # what was typed is kept


# ---------------------------------------------------------------- showing it


@pytest.mark.req("C-26", "C-23")
def test_the_card_and_results_show_local_time_marked_as_set_by_hand(
    client: TestClient, db_session: Session
) -> None:
    by_hand = _make(client, db_session, "Hand Zone", time_zone="America/Chicago")
    derived = _make(
        client,
        db_session,
        "Derived Zone",
        time_zone="Asia/Tokyo",
        addresses=[{"city": "Olathe", "region": "KS", "postal_code": "66061", "country": "US"}],
    )
    none = _make(client, db_session, "No Zone")
    card = client.get(f"/contacts/{by_hand}").text
    assert 'data-tz="America/Chicago"' in card
    assert "set by hand" in card
    card = client.get(f"/contacts/{derived}").text
    assert 'data-tz="America/Chicago"' in card  # Olathe's, not Tokyo's
    assert (
        "Asia/Tokyo" not in card.split('data-testid="local-time"')[0] or "set by hand" not in card
    )
    assert "set by hand" not in card
    assert 'data-testid="local-time"' not in client.get(f"/contacts/{none}").text
    results = client.get("/contacts/results?q=zone").text
    assert 'data-tz="America/Chicago"' in results


@pytest.mark.req("C-26", "P-03")
def test_presenting_hides_it_with_the_location(client: TestClient, db_session: Session) -> None:
    cid = _make(client, db_session, "Hidden Zone", time_zone="America/Chicago")
    contact = db_session.get(Contact, cid)
    assert contact is not None

    def shown(hidden: set[str]) -> str | None:
        token = PRESENTING.set(Presenting(PrivacySettings(hidden=frozenset(hidden))))
        try:
            return to_out(contact, detail=True).time_zone
        finally:
            PRESENTING.reset(token)

    assert shown({"notes"}) == "America/Chicago"
    assert shown({"notes", "location"}) is None


# ---------------------------------------------------------------- leaving the app


def _csv_zone(db_session: Session, name: str) -> str:
    rows = list(csv.DictReader(io.StringIO(export_csv(db_session))))
    return next(r["time_zone"] for r in rows if r["display_name"] == name)


@pytest.mark.req("C-26", "D-09")
def test_exports_carry_the_effective_zone(client: TestClient, db_session: Session) -> None:
    _make(client, db_session, "Hand Zone", time_zone="America/Denver")
    _make(
        client,
        db_session,
        "Derived Zone",
        time_zone="Asia/Tokyo",
        addresses=[{"city": "Olathe", "region": "KS", "postal_code": "66061", "country": "US"}],
    )
    _make(client, db_session, "No Zone")
    assert _csv_zone(db_session, "Hand Zone") == "America/Denver"
    assert _csv_zone(db_session, "Derived Zone") == "America/Chicago"
    assert _csv_zone(db_session, "No Zone") == ""
    doc = json.loads(build_export(db_session, "Test", "test", ExportOptions(kind="json")).body)
    zones = {c["display_name"]: c.get("time_zone") for c in doc["contacts"]}
    assert zones["Hand Zone"] == "America/Denver"
    assert zones["Derived Zone"] == "Asia/Tokyo"  # the hand-set value is kept as entered
    assert zones["No Zone"] is None


@pytest.mark.req("C-26", "I-09")
def test_a_json_export_restores_the_zone_on_import(client: TestClient, db_session: Session) -> None:
    from app.exchange import plan_import, rows_from_json, run_import

    _make(client, db_session, "Hand Zone", time_zone="America/Denver")
    raw = build_export(db_session, "Test", "test", ExportOptions(kind="json")).body.decode()
    contact = db_session.scalars(select(Contact).where(Contact.display_name == "Hand Zone")).one()
    db_session.delete(contact)
    db_session.flush()
    planned = plan_import(db_session, rows_from_json(raw), _type_id(db_session))
    run_import(db_session, planned)
    again = db_session.scalars(select(Contact).where(Contact.display_name == "Hand Zone")).one()
    assert again.time_zone == "America/Denver"
