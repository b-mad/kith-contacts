"""Export (D-03), vCard (D-02) and CSV import (D-01)."""

from __future__ import annotations

import csv
import io
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import ContactError, get_contact
from app.exchange import (
    CSV_COLUMNS,
    FORMAT,
    _cell,
    export_csv,
    export_json,
    guess_mapping,
    plan_import,
    read_csv,
    rows_from_csv,
    rows_from_vcards,
    run_import,
)
from app.lists import add_members, create_list
from app.models import Contact, ContactType
from app.tags import add_tag
from app.vcard import parse_vcards, to_vcard, to_vcards
from scripts.seed import seed


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def by_name(session: Session, name: str) -> Contact:
    return get_contact(
        session, session.scalars(select(Contact.id).where(Contact.display_name == name)).one()
    )


def employee_type(session: Session) -> int:
    return session.scalars(select(ContactType.id).where(ContactType.name == "Employee")).one()


# ---------------------------------------------------------------- export (D-03)


@pytest.mark.req("D-03")
def test_json_export_is_complete(seeded: Session) -> None:
    dev = by_name(seeded, "Dev Patel")
    add_tag(seeded, [dev.id], "HL7")
    project = create_list(seeded, "Q4 LIS")
    add_members(seeded, project, [dev.id], "tech lead")

    doc = export_json(seeded, "Business")

    assert doc["format"] == FORMAT
    assert len(doc["contacts"]) == 50
    exported = next(c for c in doc["contacts"] if c["display_name"] == "Dev Patel")
    assert exported["manager"] == "Maria Lopez"
    assert exported["type"] == "Employee"
    assert exported["tags"] == ["HL7"]
    assert exported["lists"] == [{"name": "Q4 LIS", "role_note": "tech lead"}]
    assert exported["emails"][0]["email"].endswith(".example")
    assert {t["name"] for t in doc["contact_types"]} >= {"Employee", "Customer", "Vendor"}
    assert doc["lists"] == [{"name": "Q4 LIS", "description": None, "status": "active", "tags": []}]
    assert exported["custom_fields"] == []
    assert exported["activities"] == []


@pytest.mark.req("D-03")
def test_csv_export_one_row_per_contact(seeded: Session) -> None:
    rows = list(csv.reader(io.StringIO(export_csv(seeded))))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 51
    maria = dict(zip(rows[0], next(r for r in rows if r[0] == "Maria Lopez"), strict=True))
    assert maria["manager"] == "Priya Raman"
    assert maria["phones"] == "+14045550102 (work)"
    assert maria["primary_email"] == "maria.lopez@acmehealth.example"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("=HYPERLINK(1)", "'=HYPERLINK(1)"), ("@SUM", "'@SUM"), ("-x", "'-x"),
     ("+14045550100", "+14045550100"), ("-5", "-5"), ("plain", "plain"), (None, "")],
)  # fmt: skip
def test_csv_cells_cannot_become_formulas(value: object, expected: str) -> None:
    assert _cell(value) == expected


# ---------------------------------------------------------------- vCard (D-02)


@pytest.mark.req("D-02")
def test_vcard_round_trip(seeded: Session) -> None:
    maria = by_name(seeded, "Maria Lopez")
    add_tag(seeded, [maria.id], "HL7, v2")  # comma is escaped in vCard
    maria = by_name(seeded, "Maria Lopez")
    text = to_vcard(maria)

    assert text.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Maria Lopez\r\n")
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    card = parse_vcards(text)[0]
    assert card.display_name == "Maria Lopez"
    assert card.company == "Acme Health"
    assert card.department == "Engineering"
    assert card.title == "Engineering Manager"
    assert card.emails == [("maria.lopez@acmehealth.example", "work", True)]
    assert card.phones == [("+14045550102", "work")]
    assert "Works on: Lab results pipeline" in card.notes
    assert card.tags == ["HL7 v2"]


def test_multiple_vcards(seeded: Session) -> None:
    people = [by_name(seeded, n) for n in ("Dev Patel", "Robert Lin")]
    assert [c.display_name for c in parse_vcards(to_vcards(people))] == ["Dev Patel", "Robert Lin"]


@pytest.mark.req("D-02")
def test_parse_vcards_from_other_apps() -> None:
    apple = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Nguyen;Tom;;;\r\nFN:Tom Nguyen\r\n"
        "ORG:Acme Health;Engineering;\r\nTITLE:Frontend Engineer\r\n"
        "item1.EMAIL;type=INTERNET;type=pref:tom@acme.example\r\n"
        "TEL;type=CELL;type=VOICE;type=pref:(404) 555-0199\r\n"
        "NOTE:Met at the\\, uh\\, offsite\\nLikes tea\r\nEND:VCARD\r\n"
    )
    outlook_21 = (
        "BEGIN:VCARD\nVERSION:2.1\nN:Okafor;Ben\nFN:Ben Okafor\n"
        "EMAIL;PREF;INTERNET:ben@acme.example\nTEL;WORK;VOICE:404-555-0111\n"
        "NOTE;ENCODING=QUOTED-PRINTABLE:Security=20lead=0D=0ASOC 2\nEND:VCARD\n"
    )
    folded_40 = (
        "BEGIN:VCARD\nVERSION:4.0\nFN:Priscilla\n  Adams\nEMAIL:p@x.example\n"
        "TEL;VALUE=uri;TYPE=home:tel:+1-770-555-0100\nCATEGORIES:Procurement,Buyers\nEND:VCARD\n"
    )
    nameless = "BEGIN:VCARD\nVERSION:3.0\nN:Solo;Han;;;\nEND:VCARD\n"
    cards = parse_vcards(apple + outlook_21 + folded_40 + nameless + "garbage line\n")

    assert [c.display_name for c in cards] == [
        "Tom Nguyen",
        "Ben Okafor",
        "Priscilla Adams",
        "Han Solo",
    ]
    tom, ben, priscilla, _ = cards
    assert (tom.first_name, tom.last_name, tom.company, tom.department) == (
        "Tom", "Nguyen", "Acme Health", "Engineering",
    )  # fmt: skip
    assert tom.emails == [("tom@acme.example", "", True)]
    assert tom.phones == [("(404) 555-0199", "mobile")]
    assert tom.notes == "Met at the, uh, offsite\nLikes tea"
    assert ben.emails == [("ben@acme.example", "", True)]
    assert ben.phones == [("404-555-0111", "work")]
    assert ben.notes == "Security lead\r\nSOC 2"
    assert priscilla.phones == [("+1-770-555-0100", "home")]
    assert priscilla.tags == ["Procurement", "Buyers"]


# ---------------------------------------------------------------- CSV import (D-01)

OUTLOOK_CSV = (
    "First Name,Last Name,E-mail Address,Mobile Phone,Company,Job Title,Department,Manager's Name,Categories\r\n"
    "Grace,Hopper,grace@navy.example,555-0100,US Navy,Rear Admiral,Computing,,Pioneers;Compilers\r\n"
    "Ada,Lovelace,ada@engine.example,,Analytical Engines,Analyst,,Grace Hopper,Pioneers\r\n"
)
GOOGLE_CSV = (
    "Name,Given Name,Family Name,E-mail 1 - Value,Phone 1 - Value,Organization 1 - Name,"
    "Organization 1 - Title,Group Membership\n"
    "Linus Torvalds,Linus,Torvalds,linus@kernel.example,+1 503 555 0100,Linux Foundation,Fellow,"
    "* myContacts ::: Kernel\n"
)


def test_mapping_recognises_outlook_and_google_headers() -> None:
    outlook_headers, _ = read_csv(OUTLOOK_CSV.encode())
    google_headers, _ = read_csv(GOOGLE_CSV.encode())
    assert [guess_mapping(outlook_headers).get(i) for i in range(len(outlook_headers))] == [
        "first_name", "last_name", "email", "phone", "company", "title", "department",
        "manager", "tags",
    ]  # fmt: skip
    google = guess_mapping(google_headers)
    assert [google.get(i) for i in range(len(google_headers))] == [
        "display_name", "first_name", "last_name", "email", "phone", "company", "title", "tags",
    ]  # fmt: skip


def test_read_csv_handles_semicolons_bom_and_latin1() -> None:
    headers, body = read_csv("﻿Name;Company\nJosé;Café Ltd\n".encode())
    assert headers == ["Name", "Company"]
    assert body == [["José", "Café Ltd"]]
    headers, body = read_csv("Name,Company\nJos\xe9,Caf\xe9\n".encode("cp1252"))
    assert body == [["José", "Café"]]
    with pytest.raises(ContactError):
        read_csv(b"\n\n")
    with pytest.raises(ContactError, match="5 MB"):
        read_csv(b"x" * (5 * 1024 * 1024 + 1))


@pytest.mark.req("D-01")
def test_import_outlook_csv_with_managers_tags_and_list(seeded: Session) -> None:
    headers, body = read_csv(OUTLOOK_CSV.encode())
    planned = plan_import(
        seeded, rows_from_csv(body, guess_mapping(headers)), employee_type(seeded)
    )

    assert [(r.data["display_name"], r.ok, r.duplicate_of) for r in planned] == [
        ("Grace Hopper", True, None),
        ("Ada Lovelace", True, None),
    ]
    result = run_import(seeded, planned, list_name="Imported from Outlook")

    ada = by_name(seeded, "Ada Lovelace")
    grace = by_name(seeded, "Grace Hopper")
    assert len(result.created) == 2
    assert result.managers_linked == 1
    assert ada.manager_id == grace.id
    assert sorted(t.name for t in grace.tags) == ["Compilers", "Pioneers"]
    assert grace.phones[0].number == "555-0100"  # not a full number: kept as typed
    assert [m.contact_list.name for m in ada.memberships] == ["Imported from Outlook"]
    assert result.list_id is not None


@pytest.mark.req("D-01", "D-02")
def test_duplicates_and_errors_are_flagged_and_skipped(seeded: Session) -> None:
    records = [
        {"display_name": "Somebody New", "email": "maria.lopez@acmehealth.example"},  # email dup
        {"display_name": "Robert Lin", "company": "peachtree labs"},  # name + company dup
        {"display_name": "In File Twice", "email": "twice@x.example"},
        {"display_name": "In File Again", "email": "TWICE@x.example"},  # dup within the file
        {"display_name": "Bad Email", "email": "not-an-email"},
        {"email": "noname@x.example"},  # name from email
        {"first_name": "Only", "last_name": "Names", "type": "customer"},
    ]
    planned = plan_import(seeded, records, employee_type(seeded))

    assert [bool(r.duplicate_of) for r in planned] == [True, True, False, True, False, False, False]
    assert not planned[4].ok
    assert "email" in planned[4].errors[0]
    assert planned[5].data["display_name"] == "noname"
    customer = seeded.scalars(select(ContactType.id).where(ContactType.name == "Customer")).one()
    assert planned[6].data["contact_type_id"] == customer

    result = run_import(seeded, planned)
    assert (len(result.created), result.skipped_duplicates, result.skipped_errors) == (3, 3, 1)
    again = run_import(
        seeded, plan_import(seeded, records[:1], employee_type(seeded)), include_duplicates=True
    )
    assert len(again.created) == 1


def test_vcard_rows_import(seeded: Session) -> None:
    cards = parse_vcards(
        "BEGIN:VCARD\nVERSION:3.0\nFN:Katherine Johnson\nORG:NASA\nEMAIL;TYPE=WORK:kj@nasa.example\n"
        "TEL;TYPE=CELL:+1 757 555 0100\nCATEGORIES:Math\nEND:VCARD\n"
    )
    planned = plan_import(seeded, rows_from_vcards(cards), employee_type(seeded))
    run_import(seeded, planned)
    kj = by_name(seeded, "Katherine Johnson")
    assert kj.company == "NASA"
    assert kj.phones[0].number == "+17575550100"
    assert kj.phones[0].label == "mobile"
    assert [t.name for t in kj.tags] == ["Math"]


def test_manager_link_skips_ambiguous_names(seeded: Session) -> None:
    records = [
        {"display_name": "Twin", "company": "A"},
        {"display_name": "Twin", "company": "B"},
        {"display_name": "Kid", "manager": "Twin"},
        {"display_name": "Orphan", "manager": "Nobody Here"},
    ]
    result = run_import(seeded, plan_import(seeded, records, employee_type(seeded)))
    assert result.managers_linked == 0
    assert by_name(seeded, "Kid").manager_id is None


@pytest.mark.req("D-01")
def test_five_hundred_rows_import_in_under_ten_seconds(db_session: Session) -> None:
    contact_type = ContactType(name="Bulk", sort_order=1)
    db_session.add(contact_type)
    db_session.flush()
    lines = ["Name,Email,Company,Team,Title,Tags,Manager"]
    lines += [
        f"Person {i},p{i}@bulk.example,Company {i % 20},Team {i % 10},Engineer,Tag{i % 5},"
        + ("" if i < 10 else f"Person {i % 10}")
        for i in range(500)
    ]
    start = time.perf_counter()
    headers, body = read_csv("\n".join(lines).encode())
    planned = plan_import(db_session, rows_from_csv(body, guess_mapping(headers)), contact_type.id)
    result = run_import(db_session, planned)
    elapsed = time.perf_counter() - start

    assert len(result.created) == 500
    assert result.managers_linked == 490
    assert elapsed < 10, f"import took {elapsed:.1f}s"
