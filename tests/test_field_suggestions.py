"""Suggestions of existing values, and reuse of their spelling (C-25, ADR-0031)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import create_contact, field_suggestions, update_contact
from app.models import Contact, ContactType
from app.privacy import PrivacySettings
from app.schemas import ContactCreate, ContactUpdate
from tests.test_phase3_web import post
from tests.test_presenting import fresh, present, use_settings


def make(session: Session, name: str, **fields: object) -> Contact:
    kind = session.scalars(select(ContactType.id).order_by(ContactType.id)).first()
    if kind is None:
        created = ContactType(name="Employee")
        session.add(created)
        session.flush()
        kind = created.id
    data = ContactCreate.model_validate({"display_name": name, "contact_type_id": kind, **fields})
    return create_contact(session, data)


def options(html: str, list_id: str) -> list[str]:
    block = re.search(rf'<datalist id="{list_id}">(.*?)</datalist>', html, re.S)
    assert block, f"no datalist {list_id}"
    return re.findall(r'<option value="([^"]*)">', block.group(1))


# ---------------------------------------------------------------- the lists


@pytest.mark.req("C-25")
def test_suggestions_fold_case_and_prefer_the_most_used_spelling(db_session: Session) -> None:
    make(db_session, "A", team="Data Platform", department="Eng", location="Boston, MA")
    make(db_session, "B", team="Data Platform")
    make(db_session, "C", team="data platform")  # a stray spelling: kept out of the list
    make(db_session, "D", team="Apps")
    suggestions = field_suggestions(db_session)
    assert suggestions["team"] == ["Apps", "Data Platform"]
    assert suggestions["department"] == ["Eng"]
    assert suggestions["location"] == ["Boston, MA"]


@pytest.mark.req("C-25")
def test_label_suggestions_are_shared_and_most_used_first(db_session: Session) -> None:
    make(
        db_session,
        "A",
        emails=[
            {"email": "a@x.example", "label": "work"},
            {"email": "a2@x.example", "label": "personal"},
        ],
        phones=[
            {"number": "404 555 0100", "label": "mobile"},
            {"number": "404 555 0101", "label": "work"},
        ],
        addresses=[{"label": "home", "city": "Boston", "region": "MA"}],
    )
    make(db_session, "B", phones=[{"number": "404 555 0102", "label": "Work"}])
    labels = field_suggestions(db_session)["label"]
    assert labels[0] == "work"  # used three times across email and phone
    assert sorted(labels[1:]) == ["home", "mobile", "personal"]


# ---------------------------------------------------------------- saving reuses the spelling


@pytest.mark.req("C-25")
def test_create_reuses_an_existing_spelling(db_session: Session) -> None:
    make(db_session, "A", team="Data Platform", department="Engineering", location="Boston, MA")
    b = make(
        db_session, "B", team="  data   platform ", department="ENGINEERING", location="boston, ma"
    )
    assert (b.team, b.department, b.location) == ("Data Platform", "Engineering", "Boston, MA")
    c = make(db_session, "C", team="Quality")
    assert c.team == "Quality"  # nothing to reuse: kept as typed


@pytest.mark.req("C-25")
def test_update_reuses_a_spelling_but_can_fix_its_own_case(db_session: Session) -> None:
    make(db_session, "A", team="Data Platform")
    b = make(db_session, "B", team="Apps")
    b = update_contact(db_session, b, ContactUpdate.model_validate({"team": "DATA PLATFORM"}))
    assert b.team == "Data Platform"
    solo = make(db_session, "Solo", team="web apps")
    solo = update_contact(db_session, solo, ContactUpdate.model_validate({"team": "Web Apps"}))
    assert solo.team == "Web Apps"  # nobody else uses it, so the case can be corrected


@pytest.mark.req("C-25")
def test_labels_reuse_spelling_across_kinds_and_within_one_save(db_session: Session) -> None:
    make(db_session, "A", emails=[{"email": "a@x.example", "label": "work"}])
    b = make(
        db_session,
        "B",
        phones=[{"number": "404 555 0100", "label": "WORK"}],
        addresses=[{"label": "Work", "city": "Boston", "region": "MA"}],
    )
    assert [p.label for p in b.phones] == ["work"]
    assert [a.label for a in b.addresses] == ["work"]
    c = make(
        db_session,
        "C",
        emails=[{"email": "c@x.example", "label": "Cell"}],
        phones=[{"number": "404 555 0101", "label": "cell"}],
    )
    assert [e.label for e in c.emails] == ["Cell"]
    assert [p.label for p in c.phones] == ["Cell"]  # the first spelling in one save wins


@pytest.mark.req("C-25")
def test_blank_values_stay_blank(db_session: Session) -> None:
    a = make(db_session, "A", team="Data Platform", phones=[{"number": "404 555 0100"}])
    assert make(db_session, "B", team="   ").team is None
    assert a.phones[0].label is None


# ---------------------------------------------------------------- the forms


@pytest.mark.req("C-25")
def test_forms_offer_the_lists(client: TestClient, db_session: Session) -> None:
    make(
        db_session,
        "A",
        team="Data Platform",
        department="Engineering",
        location="Boston, MA",
        emails=[{"email": "a@x.example", "label": "work"}],
        phones=[{"number": "404 555 0100", "label": "mobile"}],
    )
    for url in (
        "/contacts/new",
        f"/contacts/{db_session.scalars(select(Contact.id)).first()}/edit",
    ):
        html = client.get(url).text
        assert options(html, "team-names") == ["Data Platform"]
        assert options(html, "department-names") == ["Engineering"]
        assert options(html, "location-names") == ["Boston, MA"]
        assert options(html, "label-names") == ["mobile", "work"]  # equally used: alphabetical
        for name in ("team", "department", "location"):
            assert re.search(rf'<input id="{name}" name="{name}"[^>]*list="{name}-names"', html), (
                name
            )
        for name in ("email_label", "phone_label", "address_label"):
            assert f'name="{name}"' in html
            assert re.search(rf'name="{name}"[^>]*list="label-names"', html), name
        # the "add another row" templates carry the list too
        template = re.search(r'<template id="phone-row">(.*?)</template>', html, re.S)
        assert template
        assert 'list="label-names"' in template.group(1)


@pytest.mark.req("C-25")
def test_saving_the_form_reuses_spelling(client: TestClient, db_session: Session) -> None:
    make(
        db_session,
        "Existing",
        team="Data Platform",
        phones=[{"number": "404 555 0100", "label": "work"}],
    )
    kind = str(db_session.scalars(select(ContactType.id)).first())
    done = post(
        client,
        "/contacts",
        display_name="Newbie",
        contact_type_id=kind,
        team="data platform",
        phone_number=["404 555 0199"],
        phone_label=["Work"],
    )
    assert done.status_code == 303
    saved = db_session.scalars(select(Contact).where(Contact.display_name == "Newbie")).one()
    assert saved.team == "Data Platform"
    assert [p.label for p in saved.phones] == ["work"]


# ---------------------------------------------------------------- presenting mode (P-02, P-03)


@pytest.mark.req("C-25", "P-02")
def test_presenting_keeps_private_values_out_of_the_lists(
    client: TestClient, db_session: Session
) -> None:
    secret = make(db_session, "Zqxsecret Person", team="Zqxcanaryteam", location="Zqxcanarycity")
    secret.is_private = True
    make(
        db_session,
        "Visible",
        team="Platform",
        location="Boston, MA",
        phones=[{"number": "404 555 0100", "label": "Zqxcanaryhome"}],
    )
    use_settings(
        client,
        db_session,
        PrivacySettings(hidden=frozenset({"location", "personal"}), labels=("zqxcanaryhome",)),
    )
    fresh(db_session)
    present(client)
    html = client.get("/contacts/new").text
    assert "zqxcanary" not in html.lower()
    assert options(html, "team-names") == ["Platform"]
    assert options(html, "location-names") == []  # Location is hidden while presenting
    assert "Boston" not in html
    assert options(html, "label-names") == []  # the personal label's row is withheld


@pytest.mark.req("C-25", "P-03")
def test_names_only_offers_no_suggestions(client: TestClient, db_session: Session) -> None:
    make(db_session, "Visible", team="Zqxplatform", department="Zqxdept", location="Zqxcity")
    use_settings(client, db_session, PrivacySettings(view="names"))
    fresh(db_session)
    present(client)
    html = client.get("/contacts/new").text
    assert "zqx" not in html.lower()
    for name in ("team", "department", "location", "label"):
        assert options(html, f"{name}-names") == []
