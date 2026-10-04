"""Birthdays (C-20) and birthday reminders on Reconnect (C-21), ADR-0022."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anonymize import anonymize
from app.birthdays import Birthday, describe, parse_birthday, upcoming_keys
from app.contacts import create_contact, get_contact
from app.exchange import (
    contact_record,
    export_csv,
    guess_mapping,
    plan_import,
    read_csv,
    rows_from_csv,
    rows_from_vcards,
)
from app.keep_in_touch import upcoming_birthdays
from app.models import Contact, ContactType
from app.privacy import COOKIE
from app.schemas import ContactCreate
from app.vcard import parse_vcards, to_vcard

# ---------------------------------------------------------------- reading dates (pure)


@pytest.mark.req("C-20")
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1980-03-14", "1980-03-14"), ("--03-14", "--03-14"),  # Google
        ("19800314", "1980-03-14"), ("--0314", "--03-14"),  # vCard
        ("1604-03-14", "--03-14"),  # Apple's "no year"
        ("1980-03-14T00:00:00Z", "1980-03-14"),
        ("3/14/1980", "1980-03-14"), ("0/0/00", None),  # Outlook
        ("3/14", "--03-14"), ("3/14/80", "1980-03-14"),
        ("March 14", "--03-14"), ("Mar 14, 1980", "1980-03-14"), ("14 March 1980", "1980-03-14"),
        ("Sept 3", "--09-03"), ("2/29", "--02-29"), ("", None),
    ],
)  # fmt: skip
def test_birthdays_are_read_in_common_forms(text: str, expected: str | None) -> None:
    assert parse_birthday(text) == expected


@pytest.mark.req("C-20")
def test_slashed_dates_follow_the_instance_and_nonsense_is_refused() -> None:
    assert parse_birthday("14/3/1980", month_first=False) == "1980-03-14"
    assert parse_birthday("3/4", month_first=False) == "--04-03"
    for bad in ("13/14/1980", "hello", "2/30", "2100-01-01", "March 1980"):
        with pytest.raises(ValueError, match=r"date|year|day"):
            parse_birthday(bad)


@pytest.mark.req("C-20", "C-21")
def test_next_birthday_age_and_29_february() -> None:
    leap = Birthday.of("2000-02-29")
    assert leap.next_on(date(2027, 2, 1)) == date(2027, 2, 28)  # not a leap year
    assert leap.next_on(date(2028, 2, 1)) == date(2028, 2, 29)
    assert leap.age_on(date(2027, 2, 28)) == 26
    assert Birthday.of("1980-03-14").age_on(date(2026, 3, 13)) == 45
    assert Birthday.of("--03-14").age_on(date(2026, 3, 14)) is None
    assert "02-29" in upcoming_keys(date(2027, 2, 20))
    assert "02-29" not in upcoming_keys(date(2028, 3, 1))
    assert describe("1980-03-14", date(2026, 10, 4)) == "March 14, 1980 · age 46"
    assert describe("--03-14", date(2026, 10, 4)) == "March 14"


# ---------------------------------------------------------------- storing and showing


def _type_id(session: Session) -> int:
    found = session.scalars(select(ContactType.id).order_by(ContactType.sort_order)).first()
    if found is not None:
        return found
    created = ContactType(name="Friend")
    session.add(created)
    session.flush()
    return created.id


def _contact(session: Session, name: str, **fields: Any) -> Contact:
    data = ContactCreate.model_validate(
        {"display_name": name, "contact_type_id": _type_id(session), **fields}
    )
    return create_contact(session, data)


@pytest.mark.req("C-20")
def test_the_api_normalises_a_birthday_and_refuses_a_bad_one(db_session: Session) -> None:
    assert _contact(db_session, "Ana", birthday="March 14").birthday == "--03-14"
    with pytest.raises(ValidationError, match="use a date like"):
        ContactCreate.model_validate(
            {"display_name": "X", "contact_type_id": 1, "birthday": "soon"}
        )


TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.mark.req("C-20")
def test_form_card_and_edit_show_the_birthday(client: TestClient, db_session: Session) -> None:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    response = client.post(
        "/contacts",
        data={
            "csrf_token": token.group(1),
            "display_name": "Ana Birth",
            "contact_type_id": str(_type_id(db_session)),
            "birthday": "3/14/1980",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    path = response.headers["location"].split("?")[0]
    age = describe("1980-03-14", date.today()).split("age ")[1]
    assert f'data-testid="birthday">March 14, 1980 · age {age}</dd>' in client.get(path).text
    assert (
        'id="birthday" name="birthday" type="text" value="March 14, 1980"'
        in client.get(path + "/edit").text
    )

    bad = client.post(
        path + "/edit",
        data={
            "csrf_token": token.group(1),
            "display_name": "Ana Birth",
            "contact_type_id": str(_type_id(db_session)),
            "birthday": "someday",
        },
    )
    assert bad.status_code == 422
    assert "use a date like" in bad.text


# ---------------------------------------------------------------- import and export


@pytest.mark.req("C-20", "D-01")
def test_google_and_outlook_birthdays_import(db_session: Session) -> None:
    text = "First Name,Birthday\nAna,1980-03-14\nBea,--06-21\nCal,0/0/00\nDee,not a date\n"
    headers, body = read_csv(text.encode())
    assert guess_mapping(headers) == {0: "first_name", 1: "birthday"}
    planned = plan_import(db_session, rows_from_csv(body, guess_mapping(headers)), 1)
    assert [r.data["birthday"] for r in planned] == ["1980-03-14", "--06-21", None, None]
    assert all(r.ok for r in planned)  # an unreadable birthday is left out, not an error
    day_first = plan_import(db_session, [{"first_name": "Eve", "birthday": "4/3/1990"}], 1,
                            month_first=False)  # fmt: skip
    assert day_first[0].data["birthday"] == "1990-03-04"


@pytest.mark.req("C-20", "D-02", "D-03", "I-09")
def test_vcard_csv_and_json_carry_the_birthday(db_session: Session) -> None:
    ana = _contact(db_session, "Ana", birthday="--03-14")
    assert "BDAY:--03-14\r\n" in to_vcard(ana)
    apple = "BEGIN:VCARD\nFN:Bea\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-06-21\nEND:VCARD\n"
    record = rows_from_vcards(parse_vcards(apple))[0]
    assert plan_import(db_session, [record], _type_id(db_session))[0].data["birthday"] == (
        "--06-21"
    )
    assert contact_record(get_contact(db_session, ana.id))["birthday"] == "--03-14"
    row = next(
        r for r in csv.DictReader(io.StringIO(export_csv(db_session))) if r["display_name"] == "Ana"
    )
    assert row["birthday"] == "'--03-14"  # the CSV formula guard (D-03) ...
    assert parse_birthday(row["birthday"]) == "--03-14"  # ... which the import reads back


@pytest.mark.req("C-20", "I-07")
def test_anonymized_copies_drop_birthdays(db_session: Session) -> None:
    _contact(db_session, "Ana", birthday="1980-03-14")
    anonymize(db_session)
    db_session.expire_all()
    assert (
        db_session.scalars(select(Contact.birthday).where(Contact.birthday.is_not(None))).first()
        is None
    )


# ---------------------------------------------------------------- Reconnect (C-21)


def _on(offset: int, year: int | None = 1990) -> str:
    when = date.today() + timedelta(days=offset)
    return f"{year:04d}-{when:%m-%d}" if year else f"--{when:%m-%d}"


@pytest.mark.req("C-21")
def test_upcoming_birthdays_are_the_next_two_weeks_soonest_first(db_session: Session) -> None:
    _contact(db_session, "Later", birthday=_on(5, None))
    _contact(db_session, "Today", birthday=_on(0))
    _contact(db_session, "Too far", birthday=_on(20))
    _contact(db_session, "Gone", birthday=_on(1)).archived_at = date.today()  # type: ignore[assignment]
    db_session.flush()
    found = upcoming_birthdays(db_session, today=date.today())
    assert [(c.display_name, soon.days) for c, soon in found] == [("Today", 0), ("Later", 5)]
    assert found[0][1].turns == date.today().year - 1990
    assert found[1][1].turns is None


@pytest.mark.req("C-21")
def test_reconnect_lists_birthdays_unless_presenting_hides_them(
    client: TestClient, db_session: Session
) -> None:
    _contact(db_session, "Bday Person", birthday=_on(0), emails=[{"email": "b@example.com"}])
    page = client.get("/reconnect").text
    assert 'data-testid="birthday-row"' in page
    assert "<strong>Today</strong>" in page
    assert f"turns {date.today().year - 1990}" in page
    client.cookies.set(COOKIE, "1")  # presenting hides personal details by default
    assert 'data-testid="birthday-row"' not in client.get("/reconnect").text
