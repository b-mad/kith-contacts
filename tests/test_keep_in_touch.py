"""Keep-in-touch reminders: cadence, due dates, snooze, card control (C-15, C-16, ADR-0016)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.contacts import ContactError
from app.keep_in_touch import (
    Reminder,
    add_interval,
    due_column,
    due_date,
    reminder_for,
    set_cadence,
    snooze,
    snooze_until,
)
from app.models import Contact, ContactType

TODAY = date(2026, 10, 3)
TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


# ---------------------------------------------------------------- date math (pure)


@pytest.mark.req("C-15")
@pytest.mark.parametrize(
    ("start", "interval", "expected"),
    [
        (date(2026, 7, 1), "1m", date(2026, 8, 1)),
        (date(2026, 1, 31), "1m", date(2026, 2, 28)),  # clamped to the month's end
        (date(2028, 1, 31), "1m", date(2028, 2, 29)),  # leap year
        (date(2026, 8, 31), "6m", date(2027, 2, 28)),
        (date(2026, 11, 30), "3m", date(2027, 2, 28)),
        (date(2028, 2, 29), "1y", date(2029, 2, 28)),
        (date(2026, 12, 15), "1m", date(2027, 1, 15)),  # across a year end
        (date(2026, 9, 18), "2w", date(2026, 10, 2)),
    ],
)
def test_cadence_adds_calendar_months_or_two_weeks(
    start: date, interval: str, expected: date
) -> None:
    assert add_interval(start, interval) == expected


@pytest.mark.req("C-15", "C-16")
def test_due_counts_from_the_last_interaction_else_the_start_and_respects_a_snooze() -> None:
    kw: dict[str, Any] = {"started_on": date(2026, 9, 1), "snoozed_until": None}
    assert due_date(None, last_interaction=date(2026, 9, 3), **kw) is None
    assert due_date("1m", last_interaction=date(2026, 9, 3), **kw) == date(2026, 10, 3)
    assert due_date("1m", last_interaction=None, **kw) == date(2026, 10, 1)
    later = {**kw, "snoozed_until": date(2026, 10, 20)}
    assert due_date("1m", last_interaction=date(2026, 9, 3), **later) == date(2026, 10, 20)
    earlier = {**kw, "snoozed_until": date(2026, 9, 20)}
    assert due_date("1m", last_interaction=date(2026, 9, 3), **earlier) == date(2026, 10, 3)


@pytest.mark.req("C-15")
@pytest.mark.parametrize(
    ("due", "state", "text"),
    [
        (date(2026, 8, 1), "overdue", "Overdue by 63 days"),
        (date(2026, 10, 2), "overdue", "Overdue by 1 day"),
        (date(2026, 10, 3), "today", "Due today"),
        (date(2026, 10, 8), "soon", "Due in 5 days"),
        (date(2026, 10, 10), "soon", "Due in 7 days"),
        (date(2026, 11, 3), "later", "Due in 31 days"),
    ],
)
def test_reminder_states(due: date, state: str, text: str) -> None:
    reminder = Reminder("1m", due, TODAY, None, None)
    assert reminder.state == state
    assert reminder.describe == text


@pytest.mark.req("C-16")
def test_snooze_presets_and_dates() -> None:
    assert snooze_until("1w", "", today=TODAY) == date(2026, 10, 10)
    assert snooze_until("2w", "", today=TODAY) == date(2026, 10, 17)
    assert snooze_until("1m", "", today=TODAY) == date(2026, 11, 3)
    assert snooze_until("1w", "2026-12-01", today=TODAY) == date(2026, 12, 1)  # a date wins
    for choice, raw, message in [
        ("1w", "2026-10-03", "after today"),
        ("1w", "2027-12-01", "a year at most"),
        ("1w", "next week", "Enter a date"),
        ("9y", "", "how long"),
    ]:
        with pytest.raises(ContactError, match=message):
            snooze_until(choice, raw, today=TODAY)


# ---------------------------------------------------------------- database


def _types(session: Session) -> dict[str, int]:
    return {t.name: t.id for t in session.scalars(select(ContactType))}


def _new(client: TestClient, session: Session, name: str) -> Contact:
    body = {"display_name": name, "contact_type_id": _types(session)["Employee"]}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    contact = session.get(Contact, int(res.json()["id"]))
    assert contact is not None
    return contact


@pytest.mark.req("C-15", "C-16")
@pytest.mark.parametrize(
    ("interval", "logged", "started", "snoozed"),
    [
        ("1m", [("call", "2026-01-31")], "2025-12-01", None),
        ("1m", [("meeting", "2028-01-31")], "2025-12-01", None),
        ("2w", [("email", "2026-09-18"), ("note", "2026-10-01")], "2026-01-01", None),
        ("3m", [], "2026-08-31", None),
        ("6m", [("message", "2026-04-08")], "2026-01-01", "2026-12-24"),
        ("1y", [("call", "2026-05-01")], "2026-01-01", "2026-02-01"),  # past snooze ignored
    ],
)
def test_sql_due_date_matches_python(
    client: TestClient,
    db_session: Session,
    interval: str,
    logged: list[tuple[str, str]],
    started: str,
    snoozed: str | None,
) -> None:
    contact = _new(client, db_session, "Due Check")
    contact.kit_interval = interval
    contact.kit_started_on = date.fromisoformat(started)
    contact.kit_snoozed_until = date.fromisoformat(snoozed) if snoozed else None
    for kind, day in logged:
        add_activity(
            db_session, contact.id, kind=kind, summary="x", occurred_on=date.fromisoformat(day)
        )
    contact.kit_snoozed_until = date.fromisoformat(snoozed) if snoozed else None  # after logging
    db_session.flush()
    in_sql = db_session.scalar(select(due_column()).where(Contact.id == contact.id))
    reminder = reminder_for(db_session, contact, today=TODAY)
    assert reminder is not None
    assert in_sql == reminder.due


@pytest.mark.req("C-15")
def test_turning_on_starts_the_clock_changing_keeps_it_and_off_clears_everything(
    client: TestClient, db_session: Session
) -> None:
    contact = _new(client, db_session, "Cadence")
    set_cadence(db_session, [contact], "1m", today=TODAY)
    assert (contact.kit_interval, contact.kit_started_on) == ("1m", TODAY)
    set_cadence(db_session, [contact], "3m", today=TODAY + timedelta(days=5))
    assert (contact.kit_interval, contact.kit_started_on) == ("3m", TODAY)
    snooze(db_session, contact, date(2026, 12, 1))
    set_cadence(db_session, [contact], None, today=TODAY)
    assert (contact.kit_interval, contact.kit_started_on, contact.kit_snoozed_until) == (
        None,
        None,
        None,
    )
    with pytest.raises(ContactError, match="Turn on keep in touch first"):
        snooze(db_session, contact, date(2026, 12, 1))
    with pytest.raises(ContactError, match="how often"):
        set_cadence(db_session, [contact], "5d", today=TODAY)


@pytest.mark.req("C-16")
def test_logging_an_interaction_clears_a_snooze_but_a_note_does_not(
    client: TestClient, db_session: Session
) -> None:
    contact = _new(client, db_session, "Snoozy")
    set_cadence(db_session, [contact], "1m", today=TODAY)
    snooze(db_session, contact, date(2026, 12, 1))
    add_activity(db_session, contact.id, kind="note", summary="Prefers mornings")
    assert contact.kit_snoozed_until == date(2026, 12, 1)
    add_activity(db_session, contact.id, kind="call", summary="Caught up")
    assert contact.kit_snoozed_until is None


# ---------------------------------------------------------------- card (web)


def _csrf(client: TestClient, path: str) -> str:
    match = TOKEN.search(client.get(path).text)
    assert match
    return match.group(1)


def _post(client: TestClient, contact_id: int, action: str, **fields: str) -> Any:
    path = f"/contacts/{contact_id}"
    return client.post(
        f"{path}/keep-in-touch{action}",
        data={"csrf_token": _csrf(client, path), **fields},
        follow_redirects=False,
    )


@pytest.mark.req("C-15", "C-16")
def test_card_sets_cadence_snoozes_and_cancels(client: TestClient, db_session: Session) -> None:
    contact = _new(client, db_session, "Card Person")
    page = client.get(f"/contacts/{contact.id}").text
    assert 'data-testid="keep-in-touch"' in page
    assert "Off. Choose how often" in page
    assert 'data-testid="kit-line"' not in page

    response = _post(client, contact.id, "", interval="2w")
    assert response.status_code == 303
    assert response.headers["location"].endswith("notice=kit_saved#kit-h")
    page = client.get(f"/contacts/{contact.id}").text
    assert '<option value="2w" selected>Every 2 weeks</option>' in page
    assert "Due in 14 days" in page
    assert "counted from the day you turned this on" in page
    assert 'data-testid="kit-line"' in page

    assert _post(client, contact.id, "/snooze", snooze="1m", until="").status_code == 303
    page = client.get(f"/contacts/{contact.id}").text
    assert 'data-testid="kit-snoozed"' in page
    assert _post(client, contact.id, "/unsnooze").status_code == 303
    assert 'data-testid="kit-snoozed"' not in client.get(f"/contacts/{contact.id}").text

    assert (
        _post(client, contact.id, "", interval="")
        .headers["location"]
        .endswith("notice=kit_off#kit-h")
    )
    assert "Off. Choose how often" in client.get(f"/contacts/{contact.id}").text


@pytest.mark.req("C-15", "C-16")
def test_card_rejects_bad_input_and_missing_csrf(client: TestClient, db_session: Session) -> None:
    contact = _new(client, db_session, "Strict")
    assert _post(client, contact.id, "", interval="5d").status_code == 422
    assert _post(client, contact.id, "/snooze", snooze="1w", until="").status_code == 422
    forged = client.post(f"/contacts/{contact.id}/keep-in-touch", data={"interval": "1m"})
    assert forged.status_code == 403
    assert client.post("/contacts/999999/keep-in-touch", data={}).status_code in (403, 404)


@pytest.mark.req("C-15", "D-03")
def test_full_export_includes_the_cadence(client: TestClient, db_session: Session) -> None:
    contact = _new(client, db_session, "Exported")
    set_cadence(db_session, [contact], "6m", today=TODAY)
    db_session.flush()
    records = client.get("/export/contacts.json").json()["contacts"]
    assert next(r for r in records if r["display_name"] == "Exported")["keep_in_touch"] == "6m"
