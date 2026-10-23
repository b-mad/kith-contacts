"""D-08: the CSV export ends with one column per management level (L0, L1, ...)."""

from __future__ import annotations

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import archive_contact
from app.exchange import (
    CSV_COLUMNS,
    export_csv,
    guess_mapping,
    plan_import,
    read_csv,
    rows_from_csv,
)
from app.models import Contact, ContactType


def _person(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    types = {t.name: t.id for t in session.scalars(select(ContactType))}
    body = {"display_name": name, "contact_type_id": types["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _table(session: Session) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = list(csv.reader(io.StringIO(export_csv(session))))
    header = rows[0]
    return header, {r[0]: dict(zip(header, r, strict=True)) for r in rows[1:]}


@pytest.fixture
def org(client: TestClient, db_session: Session) -> dict[str, int]:
    """Ceo Top > Vp One > Dir Deep > Ic Three, and Solo Alone with no manager."""
    ids: dict[str, int] = {}
    for key, name, boss in (
        ("ceo", "Ceo Top", None),
        ("vp", "Vp One", "ceo"),
        ("dir", "Dir Deep", "vp"),
        ("ic", "Ic Three", "dir"),
        ("solo", "Solo Alone", None),
    ):
        ids[key] = _person(client, db_session, name, manager_id=ids[boss] if boss else None)
    return ids


@pytest.mark.req("D-08", "D-03")
def test_last_columns_are_the_managers_by_level(db_session: Session, org: dict[str, int]) -> None:
    header, rows = _table(db_session)
    assert header[: len(CSV_COLUMNS)] == CSV_COLUMNS  # nothing moves; the levels come last
    assert header[len(CSV_COLUMNS) :] == ["L0", "L1", "L2"]
    levels = {name: [r["L0"], r["L1"], r["L2"]] for name, r in rows.items()}
    assert levels == {
        "Ceo Top": ["", "", ""],  # nobody above
        "Vp One": ["Ceo Top", "", ""],
        "Dir Deep": ["Ceo Top", "Vp One", ""],
        "Ic Three": ["Ceo Top", "Vp One", "Dir Deep"],
        "Solo Alone": ["", "", ""],
    }
    assert rows["Ic Three"]["manager"] == "Dir Deep"  # the direct manager column is unchanged


@pytest.mark.req("D-08")
def test_no_level_columns_when_nobody_has_a_manager(
    client: TestClient, db_session: Session
) -> None:
    _person(client, db_session, "Solo One")
    header, _ = _table(db_session)
    assert header == CSV_COLUMNS


@pytest.mark.req("D-08", "S-18")
def test_level_columns_use_the_same_numbers_as_the_manager_tiers(
    db_session: Session, org: dict[str, int]
) -> None:
    from app.tiers import manager_tiers

    tiers = manager_tiers(db_session)
    _, rows = _table(db_session)
    for key, name in (("ceo", "Ceo Top"), ("vp", "Vp One"), ("dir", "Dir Deep")):
        assert rows["Ic Three"][f"L{tiers[org[key]]}"] == name


@pytest.mark.req("D-08", "S-18")
def test_an_archived_manager_ends_the_chain_like_the_tiers_do(
    db_session: Session, org: dict[str, int]
) -> None:
    vp = db_session.get(Contact, org["vp"])
    assert vp is not None
    archive_contact(db_session, vp)
    header, rows = _table(db_session)
    assert header[len(CSV_COLUMNS) :] == ["L0"]  # the longest chain is now one manager
    # Dir Deep now heads a line of its own (same rule as the org chart and the tier filter)
    assert rows["Dir Deep"]["L0"] == ""
    assert rows["Ic Three"]["L0"] == "Dir Deep"
    # the archived person is still exported, with the manager above them
    assert rows["Vp One"]["L0"] == "Ceo Top"
    assert rows["Vp One"]["archived"] == "yes"


@pytest.mark.req("D-08")
def test_level_cells_cannot_become_formulas(client: TestClient, db_session: Session) -> None:
    boss = _person(client, db_session, "=HYPERLINK(1)")
    _person(client, db_session, "Report One", manager_id=boss)
    _, rows = _table(db_session)
    assert rows["Report One"]["L0"] == "'=HYPERLINK(1)"


@pytest.mark.req("D-08", "D-01")
def test_importing_the_export_again_ignores_the_level_columns(
    db_session: Session, org: dict[str, int]
) -> None:
    headers, body = read_csv(export_csv(db_session).encode())
    mapping = guess_mapping(headers)
    assert not {headers[i] for i in mapping} & {"L0", "L1", "L2"}
    records = rows_from_csv(body, mapping, headers)
    types = {t.name: t.id for t in db_session.scalars(select(ContactType))}
    planned = plan_import(db_session, records, types["Employee"])
    assert len(planned) == 5
    assert not [row for row in planned if row.errors]


@pytest.mark.req("D-08", "D-03")
def test_download_has_the_level_columns(client: TestClient, org: dict[str, int]) -> None:
    res = client.get("/export/contacts.csv")
    assert res.status_code == 200
    first_line = res.text.lstrip("﻿").splitlines()[0]
    assert first_line.endswith(",L0,L1,L2")
