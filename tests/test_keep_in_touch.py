"""Keep-in-touch reminders: cadence, due dates, snooze, card control (C-15, C-16, ADR-0016)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
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
    count_due,
    due_column,
    due_date,
    due_reminders,
    reminder_for,
    set_cadence,
    snooze,
    snooze_until,
)
from app.models import Contact, ContactType
from app.saved_searches import clean_query, describe_query

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


# ---------------------------------------------------------------- Reconnect (S-11, C-17)


def _person(
    client: TestClient,
    session: Session,
    name: str,
    interval: str | None,
    *,
    called_days_ago: int | None = None,
    email: str | None = None,
) -> Contact:
    body: dict[str, Any] = {"display_name": name, "contact_type_id": _types(session)["Employee"]}
    if email:
        body["emails"] = [{"email": email, "label": "work", "is_primary": True}]
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    contact = session.get(Contact, int(res.json()["id"]))
    assert contact is not None
    today = date.today()
    if interval:
        set_cadence(session, [contact], interval, today=today - timedelta(days=400))
    if called_days_ago is not None:
        add_activity(
            session,
            contact.id,
            kind="call",
            summary="Caught up on the rollout",
            occurred_on=today - timedelta(days=called_days_ago),
        )
    session.flush()
    return contact


@pytest.fixture
def due_people(client: TestClient, db_session: Session) -> dict[str, Contact]:
    people = {
        # monthly, last call 70 days ago -> overdue by about 40 days
        "very": _person(
            client, db_session, "Vera Overdue", "1m", called_days_ago=70, email="v@x.example"
        ),
        # every 2 weeks, last call 15 days ago -> overdue by 1 day
        "just": _person(client, db_session, "Justin Late", "2w", called_days_ago=15),
        # every 2 weeks, last call 10 days ago -> due in 4 days
        "soon": _person(client, db_session, "Sunny Soon", "2w", called_days_ago=10),
        # monthly, last call 5 days ago -> not due for weeks
        "later": _person(client, db_session, "Larry Later", "1m", called_days_ago=5),
        "off": _person(client, db_session, "Olive Off", None, called_days_ago=300),
        "archived": _person(client, db_session, "Archie Archived", "1m", called_days_ago=90),
        "snoozed": _person(client, db_session, "Snow Snoozed", "1m", called_days_ago=90),
    }
    people["archived"].archived_at = datetime.now(UTC)
    snooze(db_session, people["snoozed"], date.today() + timedelta(days=20))
    db_session.flush()
    return people


@pytest.mark.req("S-11")
def test_due_list_is_most_overdue_first_and_skips_off_archived_snoozed_and_later(
    db_session: Session, due_people: dict[str, Contact]
) -> None:
    rows = due_reminders(db_session, today=date.today())
    assert [c.display_name for c, _ in rows] == ["Vera Overdue", "Justin Late", "Sunny Soon"]
    assert [r.state for _, r in rows] == ["overdue", "overdue", "soon"]
    assert rows[1][1].describe == "Overdue by 1 day"
    assert rows[2][1].describe == "Due in 4 days"
    assert count_due(db_session, today=date.today()) == 3


@pytest.mark.req("S-11")
def test_reconnect_page_groups_people_and_offers_actions(
    client: TestClient, due_people: dict[str, Contact]
) -> None:
    page = client.get("/reconnect").text
    assert 'id="overdue-h">Overdue <span class="muted">· 2</span>' in page
    assert 'id="week-h">Due this week <span class="muted">· 1</span>' in page
    names = re.findall(r'class="reconnect-name">([^<]+)<', page)
    assert names == ["Vera Overdue", "Justin Late", "Sunny Soon"]
    assert "Last:</span> Call ·" in page
    assert 'href="mailto:v@x.example" data-log-kind="email"' in page
    assert 'aria-label="Snooze Justin Late for 2 weeks"' in page


@pytest.mark.req("S-11")
def test_reconnect_page_when_nobody_is_due_names_the_next_one(
    client: TestClient, db_session: Session
) -> None:
    _person(client, db_session, "Larry Later", "1m", called_days_ago=5)
    page = client.get("/reconnect").text
    assert 'data-testid="reconnect-empty"' in page
    assert "Next up:" in page
    assert "Larry Later" in page


@pytest.mark.req("S-11", "C-16")
def test_logging_or_snoozing_from_reconnect_returns_there_and_clears_the_row(
    client: TestClient, due_people: dict[str, Contact]
) -> None:
    vera, justin = due_people["very"], due_people["just"]
    token = _csrf(client, "/reconnect")
    logged = client.post(
        f"/contacts/{vera.id}/activities",
        data={"csrf_token": token, "kind": "call", "summary": "Checked in", "next": "/reconnect"},
        follow_redirects=False,
    )
    assert logged.status_code == 303
    assert logged.headers["location"].startswith("/reconnect?notice=logged")
    snoozed = client.post(
        f"/contacts/{justin.id}/keep-in-touch/snooze",
        data={"csrf_token": token, "snooze": "2w", "next": "/reconnect"},
        follow_redirects=False,
    )
    assert snoozed.headers["location"].startswith("/reconnect?notice=snoozed")
    names = re.findall(r'class="reconnect-name">([^<]+)<', client.get("/reconnect").text)
    assert names == ["Sunny Soon"]


@pytest.mark.req("C-15")
def test_bulk_keep_in_touch_sets_and_clears_the_cadence(
    client: TestClient, db_session: Session
) -> None:
    a = _person(client, db_session, "Bulk A", None)
    b = _person(client, db_session, "Bulk B", None)
    token = _csrf(client, "/")
    data = {"csrf_token": token, "interval": "3m", "next": "/?q=Bulk", "contact_ids": [a.id, b.id]}
    response = client.post("/selection/keep-in-touch", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/?q=Bulk&notice=kit_bulk&n=2")
    assert (a.kit_interval, b.kit_interval) == ("3m", "3m")
    off = {**data, "interval": ""}
    assert (
        "notice=kit_bulk_off"
        in client.post("/selection/keep-in-touch", data=off, follow_redirects=False).headers[
            "location"
        ]
    )
    assert (a.kit_interval, b.kit_interval) == (None, None)
    assert 'data-testid="kit-menu"' in client.get("/").text


@pytest.mark.req("S-11")
def test_due_filter_on_people_with_chip_and_saved_search(
    client: TestClient, due_people: dict[str, Contact]
) -> None:
    page = client.get("/?due=1").text
    rows = re.findall(r'data-name="([^"]+)" data-testid="result-row"', page)
    assert sorted(rows) == ["Justin Late", "Sunny Soon", "Vera Overdue"]
    assert 'name="due" value="1" checked' in page  # the filled "Due to reconnect" chip
    assert clean_query({"due": "1", "sort": "name"}) == "due=1"
    assert describe_query("due=1") == "due to reconnect"


@pytest.mark.req("C-17")
def test_email_and_call_links_offer_the_log_prompt(client: TestClient, db_session: Session) -> None:
    contact = _person(client, db_session, "Prompt Me", None, email="p@x.example")
    page = client.get(f"/contacts/{contact.id}").text
    assert f'data-log-kind="email" data-log-contact="{contact.id}"' in page
    assert 'data-testid="log-prompt"' in page
    assert re.search(r'<form class="log-prompt"[^>]*hidden', page)


# ---------------------------------------------------------------- Undo, overdue marker, speed (ADR-0017)


@pytest.mark.req("S-11", "C-16")
def test_undo_after_logging_removes_the_activity_and_restores_the_snooze(
    client: TestClient, db_session: Session, due_people: dict[str, Contact]
) -> None:
    snowy = due_people["snoozed"]
    before = snowy.kit_snoozed_until
    token = _csrf(client, "/reconnect")
    logged = client.post(
        f"/contacts/{snowy.id}/activities",
        data={"csrf_token": token, "kind": "call", "summary": "Quick call", "next": "/reconnect"},
        follow_redirects=False,
    )
    page = client.get(logged.headers["location"]).text
    assert 'data-testid="undo"' in page
    activity_id = re.search(r'name="activity_id" value="(\d+)"', page)
    assert activity_id
    assert f'name="previous_snooze" value="{before.isoformat()}"' in page  # type: ignore[union-attr]
    undone = client.post(
        f"/contacts/{snowy.id}/undo",
        data={
            "csrf_token": token,
            "activity_id": activity_id.group(1),
            "previous_snooze": before.isoformat(),  # type: ignore[union-attr]
            "next": "/reconnect",
        },
        follow_redirects=False,
    )
    assert undone.headers["location"] == "/reconnect?notice=undone"
    db_session.expire_all()
    assert snowy.kit_snoozed_until == before
    assert "Quick call" not in [a.summary for a in snowy.activities]


@pytest.mark.req("S-11", "C-16")
def test_undo_after_snoozing_puts_the_reminder_back(
    client: TestClient, db_session: Session, due_people: dict[str, Contact]
) -> None:
    justin = due_people["just"]
    token = _csrf(client, "/reconnect")
    snoozed = client.post(
        f"/contacts/{justin.id}/keep-in-touch/snooze",
        data={"csrf_token": token, "snooze": "2w", "next": "/reconnect"},
        follow_redirects=False,
    )
    page = client.get(snoozed.headers["location"]).text
    assert 'name="previous_snooze" value=""' in page
    assert "activity_id" not in page.split('data-testid="flash"', 1)[1].split("</div>", 1)[0]
    client.post(
        f"/contacts/{justin.id}/undo",
        data={"csrf_token": token, "previous_snooze": "", "next": "/reconnect"},
    )
    names = re.findall(r'class="reconnect-name">([^<]+)<', client.get("/reconnect").text)
    assert "Justin Late" in names


@pytest.mark.req("S-11")
def test_undo_rejects_a_bad_date_or_someone_elses_activity(
    client: TestClient, due_people: dict[str, Contact]
) -> None:
    vera, justin = due_people["very"], due_people["just"]
    token = _csrf(client, "/reconnect")
    bad = client.post(
        f"/contacts/{vera.id}/undo", data={"csrf_token": token, "previous_snooze": "soon"}
    )
    assert bad.status_code == 422
    other = justin.activities[0].id
    wrong = client.post(
        f"/contacts/{vera.id}/undo", data={"csrf_token": token, "activity_id": str(other)}
    )
    assert wrong.status_code == 404
    assert client.post(f"/contacts/{vera.id}/undo", data={}).status_code == 403


@pytest.mark.req("S-11")
def test_no_undo_without_a_valid_offer(client: TestClient) -> None:
    assert 'data-testid="undo"' not in client.get("/?notice=logged&undo=x").text
    assert 'data-testid="undo"' not in client.get("/?notice=saved&undo=3&ps=").text
    assert 'data-testid="undo"' not in client.get("/?notice=logged&undo=3&ps=nope").text


@pytest.mark.req("S-11")
def test_search_results_mark_overdue_people_in_words(
    client: TestClient, due_people: dict[str, Contact]
) -> None:
    html = client.get("/contacts/results").text
    vera = html.split('data-name="Vera Overdue"', 1)[1].split("</li>", 1)[0]
    assert 'data-testid="overdue"' in vera
    assert "overdue to reconnect" in vera
    sunny = html.split('data-name="Sunny Soon"', 1)[1].split("</li>", 1)[0]
    assert 'data-testid="overdue"' not in sunny


@pytest.mark.req("S-11", "N-03")
def test_reconnect_is_fast_with_ten_thousand_contacts(
    client: TestClient, db_session: Session
) -> None:
    from sqlalchemy import text

    type_id = _types(db_session)["Employee"]
    db_session.execute(
        text(
            """
            INSERT INTO contact (display_name, contact_type_id, kit_interval, kit_started_on)
            SELECT 'Person ' || g, :type_id,
                   (ARRAY['2w', '1m', '3m', '6m', '1y'])[1 + g % 5],
                   CURRENT_DATE - (g % 400)
            FROM generate_series(1, 10000) AS g
            """
        ),
        {"type_id": type_id},
    )
    db_session.execute(
        text(
            """
            INSERT INTO activity (contact_id, kind, summary, occurred_on)
            SELECT id, 'call', 'Caught up', CURRENT_DATE - (id % 120)
            FROM contact WHERE display_name LIKE 'Person %'
            """
        )
    )
    db_session.execute(text("ANALYZE contact"))
    db_session.execute(text("ANALYZE activity"))
    import time

    start = time.perf_counter()
    page = client.get("/reconnect")
    elapsed = time.perf_counter() - start
    assert page.status_code == 200
    assert "Overdue" in page.text
    assert "Showing the 100 most overdue of" in page.text  # thousands due: the rest via search
    assert page.text.count('data-testid="reconnect-row"') == 100
    assert elapsed < 1.0, f"Reconnect took {elapsed:.2f}s"


@pytest.mark.req("C-17")
def test_logging_after_bulk_compose_logs_everyone_selected(
    client: TestClient, db_session: Session, due_people: dict[str, Contact]
) -> None:
    vera, justin = due_people["very"], due_people["just"]
    token = _csrf(client, "/")
    response = client.post(
        "/selection/log",
        data={
            "csrf_token": token,
            "contact_ids": [str(vera.id), str(justin.id), "999999"],
            "kind": "email",
            "summary": "Emailed",
            "next": "/?q=x",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?q=x&notice=logged_many&n=2"
    db_session.expire_all()
    for person in (vera, justin):
        assert person.activities[0].kind == "email"
        assert person.activities[0].occurred_on == date.today()
    names = re.findall(r'class="reconnect-name">([^<]+)<', client.get("/reconnect").text)
    assert "Vera Overdue" not in names
    assert "Justin Late" not in names
    bad = client.post(
        "/selection/log",
        data={"csrf_token": token, "contact_ids": [str(vera.id)], "kind": "note"},
    )
    assert bad.status_code == 422
