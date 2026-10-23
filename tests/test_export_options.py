"""D-09 and D-10: choose what leaves in an export, and keep a record of it (ADR-0034)."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

import pytest
import pyzipper
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exchange import CSV_COLUMNS
from app.exports import (
    DEFAULT_GROUPS,
    ExportError,
    ExportOptions,
    build_export,
    log_export,
    parse_options,
    recent_exports,
)
from app.lists import add_members, create_list
from app.models import Contact, ContactType, ExportLog
from app.privacy import is_blocked
from app.tags import add_tag


def _person(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    kind = fields.pop("kind", "Employee")
    body = {"display_name": name, "contact_type_id": types[kind], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _csv(session: Session, **kw: Any) -> tuple[list[str], dict[str, dict[str, str]]]:
    file = build_export(session, "Test", "test", ExportOptions(kind="csv", **kw))
    rows = list(csv.reader(io.StringIO(file.body.decode("utf-8-sig"))))
    return rows[0], {r[0]: dict(zip(rows[0], r, strict=True)) for r in rows[1:]}


@pytest.fixture
def world(client: TestClient, db_session: Session) -> dict[str, int]:
    ids = {}
    ids["boss"] = _person(client, db_session, "Bea Boss", title="Director", team="Blue")
    ids["ann"] = _person(
        client,
        db_session,
        "Ann Acme",
        manager_id=ids["boss"],
        company="Acme",
        notes="Mentioned a family matter",
        works_on="Lab feeds",
        birthday="1985-03-03",
        emails=[
            {"email": "ann@acme.example", "label": "work", "is_primary": True},
            {"email": "ann.home@mail.example", "label": "personal"},
        ],
        phones=[
            {"number": "+14045550101", "label": "work"},
            {"number": "+14045550102", "label": "mobile"},
        ],
        addresses=[
            {
                "label": "home",
                "street": "1 Peach Way",
                "city": "Atlanta",
                "region": "GA",
                "postal_code": "30303",
                "country": "US",
            }
        ],
        slack_handle="ann",
    )
    return ids


# ---------------------------------------------------------------- what the CSV carries


@pytest.mark.req("D-09")
def test_default_csv_is_the_minimal_one(db_session: Session, world: dict[str, int]) -> None:
    header, rows = _csv(db_session)
    for gone in ("notes", "works_on", "birthday", "street", "city", "postal_code", "address_label"):
        assert gone not in header
    assert {"time_zone", "L0"} <= set(header)
    assert header[-1] == "L0"  # the manager levels stay last (D-08)
    ann = rows["Ann Acme"]
    assert ann["emails"] == "ann@acme.example"  # the personal address is left out
    assert ann["phones"] == "+14045550101 (work)"  # so is the mobile number
    assert ann["time_zone"] == "America/New_York"  # from the home address, which is not exported
    assert "state" not in header
    assert "country" not in header
    assert ann["L0"] == "Bea Boss"
    assert "location" not in header


@pytest.mark.req("D-09")
def test_location_tiers(db_session: Session, world: dict[str, int]) -> None:
    def cols(tier: str) -> set[str]:
        header, _ = _csv(db_session, location=tier)
        return set(header) & {"time_zone", "location", "state", "country", "city", "street"}

    assert cols("none") == set()
    assert cols("timezone") == {"time_zone"}
    assert cols("region") == {"time_zone", "location", "state", "country"}
    assert cols("full") == {"time_zone", "location", "state", "country", "city", "street"}
    header, rows = _csv(db_session, location="region")
    assert rows["Ann Acme"]["state"] == "GA"
    assert rows["Ann Acme"]["country"] == "United States"
    assert "city" not in header


@pytest.mark.req("D-09")
def test_groups_add_their_columns_back(db_session: Session, world: dict[str, int]) -> None:
    _, rows = _csv(db_session, groups=DEFAULT_GROUPS | {"notes", "birthday", "personal_contact"})
    ann = rows["Ann Acme"]
    assert ann["notes"] == "Mentioned a family matter"
    assert ann["works_on"] == "Lab feeds"
    assert ann["birthday"] == "1985-03-03"
    assert set(ann["emails"].split("; ")) == {"ann@acme.example", "ann.home@mail.example"}
    assert ann["phones"] == "+14045550101 (work); +14045550102 (mobile)"
    without, _ = _csv(
        db_session, groups=DEFAULT_GROUPS - {"work_contact", "reporting", "tags_lists"}
    )
    assert not {"emails", "phones", "slack_handle", "tags", "lists", "L0"} & set(without)
    assert {"display_name", "type", "company", "manager"} <= set(without)  # the core stays


@pytest.mark.req("D-09")
def test_everything_on_is_the_full_csv(db_session: Session, world: dict[str, int]) -> None:
    all_groups = DEFAULT_GROUPS | {"notes", "birthday", "personal_contact"}
    header, _ = _csv(db_session, groups=all_groups, location="full")
    assert header[: len(CSV_COLUMNS)] == CSV_COLUMNS
    assert header[len(CSV_COLUMNS) :] == ["L0"]


@pytest.mark.req("D-09")
def test_a_missing_time_zone_is_blank(client: TestClient, db_session: Session) -> None:
    _person(client, db_session, "Zoe Nowhere")
    _, rows = _csv(db_session)
    assert rows["Zoe Nowhere"]["time_zone"] == ""


# ---------------------------------------------------------------- private data stays out


@pytest.fixture
def secrets(client: TestClient, db_session: Session, world: dict[str, int]) -> dict[str, int]:
    ids = {"vis": world["ann"]}
    ids["priv"] = _person(client, db_session, "Pat Private", manager_id=world["boss"])
    ids["typed"] = _person(client, db_session, "Tess Typed", kind="Customer")
    ids["boss"] = world["boss"]
    priv = db_session.get(Contact, ids["priv"])
    assert priv is not None
    priv.is_private = True
    kind = db_session.get(ContactType, db_session.get(Contact, ids["typed"]).contact_type_id)  # type: ignore[union-attr]
    assert kind is not None
    kind.is_private = True
    add_tag(db_session, [ids["vis"]], "open-tag")
    add_tag(db_session, [ids["vis"]], "secret-tag")
    from app.models import ContactList, Tag

    db_session.scalars(select(Tag).where(Tag.name == "secret-tag")).one().is_private = True
    lst = create_list(db_session, "Open list")
    hidden = create_list(db_session, "Hidden list")
    add_members(db_session, lst, [ids["vis"]])
    add_members(db_session, hidden, [ids["vis"]])
    hidden_row = db_session.get(ContactList, hidden.id)
    assert hidden_row is not None
    hidden_row.is_private = True
    db_session.flush()
    return ids


@pytest.mark.req("D-09", "P-03")
def test_private_records_are_left_out_unless_asked_for(
    db_session: Session, secrets: dict[str, int]
) -> None:
    _, rows = _csv(db_session)
    assert set(rows) == {"Bea Boss", "Ann Acme"}
    assert rows["Ann Acme"]["tags"] == "open-tag"
    assert rows["Ann Acme"]["lists"] == "Open list"
    _, everyone = _csv(db_session, include_private=True)
    assert set(everyone) == {"Bea Boss", "Ann Acme", "Pat Private", "Tess Typed"}
    assert everyone["Ann Acme"]["tags"] == "open-tag; secret-tag"
    assert everyone["Ann Acme"]["lists"] == "Open list; Hidden list"


@pytest.mark.req("D-09", "P-03")
def test_json_and_vcard_leave_private_records_out_too(
    db_session: Session, secrets: dict[str, int]
) -> None:
    doc = json.loads(build_export(db_session, "Test", "test", ExportOptions(kind="json")).body)
    assert {c["display_name"] for c in doc["contacts"]} == {"Bea Boss", "Ann Acme"}
    assert "secret-tag" not in json.dumps(doc)
    assert "Hidden list" not in json.dumps(doc)
    card = build_export(db_session, "Test", "test", ExportOptions(kind="vcf")).body.decode()
    assert "Pat Private" not in card
    assert "Ann Acme" in card
    full = build_export(
        db_session, "Test", "test", ExportOptions(kind="json", include_private=True)
    ).body.decode()
    assert "Pat Private" in full
    assert "secret-tag" in full


@pytest.mark.req("D-09")
def test_a_private_manager_is_not_named(db_session: Session, secrets: dict[str, int]) -> None:
    boss = db_session.get(Contact, secrets["boss"])
    assert boss is not None
    boss.is_private = True
    db_session.flush()
    header, rows = _csv(db_session)
    assert rows["Ann Acme"]["manager"] == ""
    assert "L0" not in header  # nobody has a visible manager left


# ---------------------------------------------------------------- password-protected zip


@pytest.mark.req("D-09")
def test_a_password_makes_an_aes_zip(db_session: Session, world: dict[str, int]) -> None:
    file = build_export(
        db_session, "Test", "test", ExportOptions(kind="csv", password="correct horse battery")
    )
    assert file.encrypted
    assert file.name.endswith(".csv.zip")
    assert file.media_type == "application/zip"
    with pyzipper.AESZipFile(io.BytesIO(file.body)) as archive:
        (inner,) = archive.namelist()
        assert inner.endswith(".csv")
        with pytest.raises(RuntimeError):
            archive.read(inner, pwd=b"wrong password!!")
        assert b"Ann Acme" in archive.read(inner, pwd=b"correct horse battery")
        assert archive.getinfo(inner).compress_type in (pyzipper.ZIP_DEFLATED, pyzipper.ZIP_STORED)
    assert b"Ann Acme" not in file.body  # nothing readable without the password


@pytest.mark.req("D-09")
def test_no_password_means_a_plain_file(db_session: Session, world: dict[str, int]) -> None:
    file = build_export(db_session, "Test", "test", ExportOptions(kind="csv"))
    assert not file.encrypted
    assert file.name.endswith(".csv")
    assert file.media_type.startswith("text/csv")


@pytest.mark.req("D-09")
def test_weak_passwords_are_refused() -> None:
    with pytest.raises(ExportError, match="at least 10"):
        parse_options("csv", {"encrypt": "1", "password": "short"})
    options = parse_options("csv", {"encrypt": "1", "password": "long enough password"})
    assert options.password == "long enough password"
    assert parse_options("csv", {"password": "ignored unless encrypt is ticked"}).password is None


# ---------------------------------------------------------------- notice, confirmation, log


@pytest.mark.req("D-10")
def test_sensitive_choices_need_a_confirmation() -> None:
    assert parse_options("csv", {}).sensitive == []
    assert parse_options("csv", {}).groups == DEFAULT_GROUPS  # no choice made: the defaults
    assert parse_options("csv", {"location": "region"}).sensitive == []
    form: dict[str, Any] = {"group": ["notes", "birthday", "personal_contact"], "location": "full"}
    reasons = parse_options("csv", form).sensitive
    assert len(reasons) == 4
    assert parse_options("json", {"include_private": "1"}).sensitive != []


@pytest.mark.req("D-09")
def test_parse_options_ignores_junk() -> None:
    options = parse_options("csv", {"group": ["notes", "bogus", "core"], "location": "elsewhere"})
    assert options.groups == {"notes"}  # only what was ticked; "core" is always there
    assert options.location == "timezone"
    with pytest.raises(ExportError):
        parse_options("pdf", {})


@pytest.mark.req("D-10")
def test_exports_are_logged_without_any_contact_data(
    db_session: Session, world: dict[str, int]
) -> None:
    options = ExportOptions(kind="csv", groups=DEFAULT_GROUPS | {"notes"}, location="region")
    file = build_export(db_session, "Test", "test", options)
    log_export(db_session, options, file)
    log_export(
        db_session,
        ExportOptions(kind="json", include_private=True, password="long enough password"),
        build_export(
            db_session,
            "Test",
            "test",
            ExportOptions(kind="json", include_private=True, password="long enough password"),
        ),
    )
    rows = recent_exports(db_session)
    assert [r.kind for r in rows] == ["json", "csv"]  # newest first
    assert rows[0].encrypted
    assert rows[0].include_private
    assert rows[1].contact_count == 2
    assert "notes" in rows[1].detail
    assert "region" in rows[1].detail
    stored = " ".join(
        str(v) for r in db_session.scalars(select(ExportLog)) for v in (r.kind, r.detail)
    )
    assert "Ann" not in stored
    assert "ann@acme" not in stored
    assert "long enough password" not in stored


# ---------------------------------------------------------------- the web page


def _csrf(client: TestClient) -> str:
    found = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/settings").text)
    assert found
    return found.group(1)


@pytest.mark.req("D-09", "D-10")
def test_settings_page_offers_the_choices_and_a_warning(
    client: TestClient, world: dict[str, int]
) -> None:
    html = client.get("/settings").text
    assert 'data-testid="export-form"' in html
    assert "personal data about other people" in html
    for group in (
        "work_contact",
        "reporting",
        "tags_lists",
        "notes",
        "birthday",
        "personal_contact",
    ):
        assert f'name="group" value="{group}"' in html
    for tier in ("none", "timezone", "region", "full"):
        assert f'name="location" value="{tier}"' in html
    assert re.search(r'name="location" value="timezone"[^>]*checked', html)
    assert re.search(r'name="group" value="notes"(?![^>]*checked)', html)
    assert 'name="include_private"' in html
    assert 'name="password"' in html


@pytest.mark.req("D-09", "D-10")
def test_download_applies_the_choices_and_logs_them(
    client: TestClient, db_session: Session, world: dict[str, int]
) -> None:
    res = client.post(
        "/export/download",
        data={
            "csrf_token": _csrf(client),
            "format": "csv",
            "group": ["work_contact", "reporting"],
            "location": "none",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-disposition"].endswith('.csv"')
    header = next(csv.reader(io.StringIO(res.text.lstrip("﻿"))))
    assert "time_zone" not in header
    assert "notes" not in header
    log = client.get("/settings").text
    assert 'data-testid="export-log"' in log
    assert "CSV" in log


@pytest.mark.req("D-10")
def test_sensitive_choices_are_refused_without_confirmation(
    client: TestClient, world: dict[str, int]
) -> None:
    data = {
        "csrf_token": _csrf(client),
        "format": "csv",
        "group": ["notes"],
        "location": "timezone",
    }
    refused = client.post("/export/download", data=data, follow_redirects=False)
    assert refused.status_code == 303
    assert (
        "confirm" in refused.headers["location"].lower() or "error" in refused.headers["location"]
    )
    allowed = client.post("/export/download", data={**data, "confirm": "1"})
    assert allowed.status_code == 200
    assert "Mentioned a family matter" in allowed.text


@pytest.mark.req("D-09")
def test_download_needs_the_csrf_token_and_a_good_password(
    client: TestClient, world: dict[str, int]
) -> None:
    assert client.post("/export/download", data={"format": "csv"}).status_code == 403
    bad = client.post(
        "/export/download",
        data={"csrf_token": _csrf(client), "format": "csv", "encrypt": "1", "password": "short"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    good = client.post(
        "/export/download",
        data={
            "csrf_token": _csrf(client),
            "format": "csv",
            "encrypt": "1",
            "password": "long enough password",
        },
    )
    assert good.headers["content-type"] == "application/zip"
    assert good.content[:2] == b"PK"


@pytest.mark.req("D-09")
def test_the_old_links_keep_working_with_the_safe_defaults(
    client: TestClient, secrets: dict[str, int]
) -> None:
    text = client.get("/export/contacts.csv").text
    assert "Pat Private" not in text
    assert "Mentioned a family matter" not in text
    assert "Pat Private" not in client.get("/export/contacts.json").text
    assert "Pat Private" not in client.get("/export/contacts.vcf").text


@pytest.mark.req("D-09", "P-05")
def test_the_download_route_is_blocked_while_presenting() -> None:
    assert is_blocked("/export/download")
