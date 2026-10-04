"""Postal addresses (C-19, ADR-0021) and the Google import details that came with them
(D-01): per-value labels, fax numbers, ``:::`` cells, address columns."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.addresses import address_lines, find_country, normalize_address
from app.anonymize import anonymize
from app.contacts import create_contact, get_contact, to_out, update_contact
from app.duplicates import merge_contacts
from app.exchange import (
    export_csv,
    export_json,
    guess_mapping,
    plan_import,
    read_csv,
    rows_from_csv,
    rows_from_json,
    rows_from_vcards,
    run_import,
)
from app.models import Contact, ContactAddress, ContactType
from app.privacy import DEFAULT, PRESENTING, Presenting, PrivacySettings
from app.schemas import ContactCreate, ContactUpdate
from app.search import search
from app.vcard import parse_vcards, to_vcard

# ---------------------------------------------------------------- normalising (pure)


@pytest.mark.req("C-19")
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # region, country typed -> (city, region, country, code)
        ({"city": "Olathe", "region": "Kan"}, ("Olathe", "KS", "United States", "US")),
        ({"city": "Olathe", "region": "Kansas", "country": "USA"},
         ("Olathe", "KS", "United States", "US")),
        ({"city": "Duluth", "region": "ga", "country": "United States of America"},
         ("Duluth", "GA", "United States", "US")),
        ({"region": "Raymore, MO"}, ("Raymore", "MO", "United States", "US")),
        ({"region": "Shawnee Mission KS"}, ("Shawnee Mission", "KS", "United States", "US")),
        ({"city": "Toronto", "region": "Ontario", "country": "Canada"},
         ("Toronto", "ON", "Canada", "CA")),
        ({"city": "Leeds", "country": "UK"}, ("Leeds", None, "United Kingdom", "GB")),
        ({"city": "Paris", "region": "Paris", "country": "France"},
         ("Paris", "Paris", "France", "FR")),  # numeric subdivision codes keep the name
        ({"city": "Springfield"}, ("Springfield", None, None, None)),  # nothing to go on
        ({"city": "Nowhere", "region": "ZZ", "country": "Atlantis"},
         ("Nowhere", "ZZ", "Atlantis", None)),  # unknown: kept as typed
    ],
)  # fmt: skip
def test_country_and_region_are_normalised(
    given: dict[str, str], expected: tuple[str | None, ...]
) -> None:
    parts: dict[str, Any] = {k: None for k in ("street", "city", "region", "postal_code")}
    parts["country"] = None
    norm = normalize_address(**{**parts, **given}, home_region="US")
    assert (norm.city, norm.region, norm.country, norm.country_code) == expected


@pytest.mark.req("C-19")
def test_street_lines_are_tidied_and_the_home_country_is_not_shown() -> None:
    norm = normalize_address(
        street="  12 Elm St \n\n  Apt 4 ", city="Olathe", region="KS", postal_code="66061",
        country=None, home_region="US",
    )  # fmt: skip
    assert norm.street == "12 Elm St\nApt 4"
    assert address_lines(**vars(norm), home_region="US") == [
        "12 Elm St", "Apt 4", "Olathe, KS 66061",
    ]  # fmt: skip
    assert address_lines(**vars(norm), home_region="CA")[-1] == "United States"
    assert find_country("u.s.a.") is not None


# ---------------------------------------------------------------- storing and showing


def _type_id(session: Session) -> int:
    found = session.scalars(select(ContactType.id)).first()
    if found is not None:
        return found
    t = ContactType(name="Friend")
    session.add(t)
    session.flush()
    return t.id


def _contact(session: Session, name: str, **fields: Any) -> Contact:
    data = ContactCreate.model_validate(
        {"display_name": name, "contact_type_id": _type_id(session), **fields}
    )
    return create_contact(session, data)


HOME = {"label": "home", "street": "12 Elm St", "city": "Olathe", "region": "Kansas",
        "postal_code": "66061"}  # fmt: skip
WORK = {"label": "work", "street": "900 Office Rd", "city": "Overland Park", "region": "KS",
        "postal_code": "66210", "country": "US"}  # fmt: skip


@pytest.mark.req("C-19")
def test_addresses_are_stored_normalised_and_replaced_on_update(db_session: Session) -> None:
    dana = _contact(db_session, "Dana Reyes", addresses=[HOME, WORK])
    out = to_out(dana)
    assert [(a.label, a.city, a.region, a.country_code) for a in out.addresses] == [
        ("home", "Olathe", "KS", "US"), ("work", "Overland Park", "KS", "US"),
    ]  # fmt: skip
    updated = update_contact(db_session, dana, ContactUpdate(addresses=[WORK]))
    assert [a.label for a in updated.addresses] == ["work"]
    unchanged = update_contact(db_session, updated, ContactUpdate(nickname="Dee"))
    assert len(unchanged.addresses) == 1  # not sent, not touched


@pytest.mark.req("C-19")
def test_an_empty_address_is_rejected() -> None:
    with pytest.raises(ValueError, match="needs a street, city"):
        ContactCreate.model_validate(
            {"display_name": "X", "contact_type_id": 1, "addresses": [{"label": "home"}]}
        )


@pytest.mark.req("C-19", "S-01")
def test_search_finds_people_by_city_state_and_zip(db_session: Session) -> None:
    _contact(db_session, "Dana Reyes", addresses=[HOME])
    _contact(db_session, "Sam Okafor", addresses=[{"city": "Toronto", "country": "Canada"}])
    for query, name in (("olathe", "Dana Reyes"), ("66061", "Dana Reyes"),
                        ("canada", "Sam Okafor")):  # fmt: skip
        hits = search(db_session, query)
        assert [h.contact.display_name for h in hits] == [name], query
    hit = search(db_session, "66061")[0]
    assert ("address", "Olathe KS 66061 United States") in hit.matched


TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _form(client: TestClient, **fields: Any) -> dict[str, Any]:
    found = TOKEN.search(client.get("/contacts/new").text)
    assert found
    return {"csrf_token": found.group(1), **fields}


@pytest.mark.req("C-19")
def test_form_card_and_edit_round_trip(client: TestClient, db_session: Session) -> None:
    type_id = _type_id(db_session)
    response = client.post(
        "/contacts",
        data=_form(
            client,
            display_name="Dana Reyes",
            contact_type_id=str(type_id),
            address_label=["home", "work"],
            address_street=["12 Elm St\r\nApt 4", ""],
            address_city=["Olathe", "Toronto"],
            address_region=["Kan", "Ontario"],
            address_postal_code=["66061", ""],
            address_country=["", "Canada"],
        ),
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    card = client.get(response.headers["location"]).text
    assert "<dt>Home address</dt>" in card
    assert "12 Elm St<br>Apt 4<br>Olathe, KS 66061</dd>" in card  # home country left out
    assert "Toronto, ON<br>Canada</dd>" in card
    edit = client.get(response.headers["location"].split("?")[0] + "/edit").text
    assert 'name="address_region" value="KS"' in edit
    assert edit.count('name="address_city"') == 3  # two rows + the template


@pytest.mark.req("C-19", "P-02")
def test_presenting_withholds_home_addresses_and_location_hides_all(
    db_session: Session,
) -> None:
    dana = _contact(db_session, "Dana Reyes", addresses=[HOME, WORK])
    db_session.expire_all()
    hide_location = PrivacySettings(hidden=frozenset({"location"}))
    for settings, labels in ((DEFAULT, ["work"]), (hide_location, [])):
        token = PRESENTING.set(Presenting(settings))
        try:
            out = to_out(get_contact(db_session, dana.id))
        finally:
            PRESENTING.reset(token)
        db_session.expire_all()
        assert [a.label for a in out.addresses] == labels


@pytest.mark.req("C-19", "C-12")
def test_merge_adds_the_other_contacts_new_addresses(db_session: Session) -> None:
    keep = _contact(db_session, "Dana Reyes", addresses=[HOME])
    other = _contact(db_session, "Dana R.", addresses=[HOME, WORK])
    merged = merge_contacts(db_session, keep.id, other.id)
    assert sorted(a.label or "" for a in merged.addresses) == ["home", "work"]


@pytest.mark.req("C-19", "I-07")
def test_anonymized_copies_drop_addresses(db_session: Session) -> None:
    _contact(db_session, "Dana Reyes", addresses=[HOME])
    anonymize(db_session)
    assert db_session.scalars(select(ContactAddress)).first() is None


# ---------------------------------------------------------------- import and export

GOOGLE = (
    "First Name,Last Name,Organization Name,Labels,E-mail 1 - Label,E-mail 1 - Value,"
    "E-mail 2 - Label,E-mail 2 - Value,Phone 1 - Label,Phone 1 - Value,Phone 2 - Label,"
    "Phone 2 - Value,Address 1 - Label,Address 1 - Street,Address 1 - City,"
    "Address 1 - Region,Address 1 - Postal Code,Address 1 - Country\n"
    "Dana,Reyes,,* myContacts ::: 2013 K Soccer,Work,dana@work.example,* Home,"
    "dana@home.example,Mobile,(913) 555-0101 ::: (913) 555-0102,Work Fax,(913) 555-0199,"
    '"Home ::: Work","12 Elm St\nApt 4 ::: 900 Office Rd",Olathe ::: Overland Park,'
    "Kan ::: KS,66061 ::: 66210, ::: United States\n"
    ",,Leawood Pediatrics,* myContacts,* Work,front@leawood.example,,,Work,913-555-0150,,,"
    "Work,1 Clinic Way,Leawood,Kansas,66211,United States of America\n"
)


@pytest.mark.req("D-01", "C-19")
def test_google_labels_faxes_multi_values_and_addresses(db_session: Session) -> None:
    headers, body = read_csv(GOOGLE.encode())
    mapping = guess_mapping(headers)
    planned = plan_import(db_session, rows_from_csv(body, mapping, headers), _type_id(db_session))
    assert all(r.ok for r in planned), [r.errors for r in planned]
    dana, clinic = (r.data for r in planned)
    assert dana["emails"] == [
        {"email": "dana@work.example", "label": "work", "is_primary": False},
        {"email": "dana@home.example", "label": "home", "is_primary": True},  # the * one
    ]
    assert dana["phones"] == [
        {"number": "(913) 555-0101", "label": "mobile"},
        {"number": "(913) 555-0102", "label": "mobile"},
    ]  # the fax is left out
    assert [(a["label"], a["city"]) for a in dana["addresses"]] == [
        ("home", "Olathe"), ("work", "Overland Park"),
    ]  # fmt: skip
    assert dana["addresses"][0]["street"] == "12 Elm St\nApt 4"
    assert clinic["display_name"] == "Leawood Pediatrics"

    run_import(db_session, planned)
    stored = db_session.scalars(select(ContactAddress).order_by(ContactAddress.id)).all()
    assert [(a.city, a.region, a.country_code) for a in stored] == [
        ("Olathe", "KS", "US"), ("Overland Park", "KS", "US"), ("Leawood", "KS", "US"),
    ]  # fmt: skip


@pytest.mark.req("D-01", "C-19")
def test_outlook_home_and_business_columns_imply_the_label(db_session: Session) -> None:
    text = (
        "First Name,Business Street,Business City,Business State,Home Street,Home City,"
        "Home State,Home Postal Code\n"
        "Ola,1 Work Pl,Atlanta,GA,5 Home Ln,Buford,GA,30518\n"
    )
    headers, body = read_csv(text.encode())
    record = rows_from_csv(body, guess_mapping(headers), headers)[0]
    planned = plan_import(db_session, [record], _type_id(db_session))
    assert [(a["label"], a["city"]) for a in planned[0].data["addresses"]] == [
        ("work", "Atlanta"), ("home", "Buford"),
    ]  # fmt: skip


@pytest.mark.req("D-02", "C-19")
def test_vcard_carries_addresses(db_session: Session) -> None:
    dana = _contact(db_session, "Dana Reyes", addresses=[{**HOME, "street": "12 Elm St\nApt 4"}])
    text = to_vcard(dana)
    assert "ADR;TYPE=HOME:;;12 Elm St\\nApt 4;Olathe;KS;66061;United States\r\n" in text
    card = parse_vcards(text)[0]
    assert card.addresses == [{
        "label": "home", "street": "12 Elm St\nApt 4", "city": "Olathe", "region": "KS",
        "postal_code": "66061", "country": "United States",
    }]  # fmt: skip
    apple = (
        "BEGIN:VCARD\nFN:Ann\nADR;TYPE=WORK,PREF:;Suite 2;1 Main St;Austin;TX;78701;\nEND:VCARD\n"
    )
    record = rows_from_vcards(parse_vcards(apple))[0]
    assert record["_addresses"][0]["street"] == "1 Main St\nSuite 2"
    assert record["_addresses"][0]["label"] == "work"


@pytest.mark.req("D-03", "I-09", "C-19")
def test_json_and_csv_exports_carry_addresses(db_session: Session) -> None:
    _contact(db_session, "Dana Reyes", addresses=[HOME, WORK])
    doc = export_json(db_session, "test")
    dana = next(c for c in doc["contacts"] if c["display_name"] == "Dana Reyes")
    assert [a["country_code"] for a in dana["addresses"]] == ["US", "US"]
    records = rows_from_json(json.dumps({**doc, "contacts": [dana]}))
    assert [a["city"] for a in records[0]["_addresses"]] == ["Olathe", "Overland Park"]

    rows = list(csv.DictReader(io.StringIO(export_csv(db_session))))
    row = next(r for r in rows if r["display_name"] == "Dana Reyes")
    assert (row["address_label"], row["city"], row["state"], row["postal_code"]) == (
        "home", "Olathe", "KS", "66061",
    )  # fmt: skip
    assert row["more_addresses"] == "work: 900 Office Rd, Overland Park, KS 66210, United States"
    # the exported columns map straight back to the first address
    mapped = set(guess_mapping(list(rows[0])).values())
    assert {"address_label", "address_street", "address_city", "address_region",
            "address_postal_code", "address_country"} <= mapped  # fmt: skip
