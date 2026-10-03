"""Find people by when you last interacted (S-09, S-10, ADR-0014)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.config import Settings
from app.models import ContactType
from app.saved_searches import clean_query, describe_query
from app.search import SearchFilters, apply_time_query, last_interactions, search
from app.semantic import SemanticService, search_by_meaning
from app.timephrase import contacted_since, parse_time_query
from tests.fake_embedder import HashingEmbedder

TODAY = date(2026, 10, 3)  # a Saturday


# ---------------------------------------------------------------- S-10 parser


@pytest.mark.req("S-10")
@pytest.mark.parametrize(
    ("query", "start", "end", "label", "terms", "kinds"),
    [
        ("who have I interacted with recently", "2026-09-04", "2026-10-03",
         "recently (last 30 days)", (), ()),
        ("who did I meet last week", "2026-09-21", "2026-09-27",
         "last week (Sep 21 to Sep 27, 2026)", (), ("meeting",)),
        ("This week", "2026-09-28", "2026-10-03", "this week (Sep 28 to Oct 3, 2026)", (), ()),
        ("who did I talk to about contracts in September", "2026-09-01", "2026-09-30",
         "in September 2026", ("contracts",), ()),
        ("in december", "2025-12-01", "2025-12-31", "in December 2025", (), ()),
        ("during Jan 2026 lab", "2026-01-01", "2026-01-31", "in January 2026", ("lab",), ()),
        ("emailed since June 1", "2026-06-01", "2026-10-03", "since Jun 1, 2026", (), ("email",)),
        ("since Nov 3", "2025-11-03", "2026-10-03", "since Nov 3, 2025", (), ()),
        ("since 2026-09-15", "2026-09-15", "2026-10-03", "since Sep 15, 2026", (), ()),
        ("who I've called in the past 2 weeks", "2026-09-20", "2026-10-03",
         "in the last 2 weeks (Sep 20 to Oct 3, 2026)", (), ("call",)),
        ("messaged or texted over the last three days", "2026-10-01", "2026-10-03",
         "in the last 3 days (Oct 1 to Oct 3, 2026)", (), ("message",)),
        ("in the last month", "2026-09-04", "2026-10-03",
         "in the last month (Sep 4 to Oct 3, 2026)", (), ()),
        ("past year", "2025-10-04", "2026-10-03",
         "in the past year (Oct 4, 2025 to Oct 3, 2026)", (), ()),
        ("Yesterday", "2026-10-02", "2026-10-02", "yesterday (Oct 2, 2026)", (), ()),
        ("today", "2026-10-03", "2026-10-03", "today (Oct 3, 2026)", (), ()),
        ("last month vendors", "2026-09-01", "2026-09-30",
         "last month (Sep 1 to Sep 30, 2026)", ("vendors",), ()),
        ("this month", "2026-10-01", "2026-10-03", "this month (Oct 1 to Oct 3, 2026)", (), ()),
        ("last quarter", "2026-07-01", "2026-09-30",
         "last quarter (Jul 1 to Sep 30, 2026)", (), ()),
        ("this quarter", "2026-10-01", "2026-10-03",
         "this quarter (Oct 1 to Oct 3, 2026)", (), ()),
        ("last year", "2025-01-01", "2025-12-31",
         "last year (Jan 1 to Dec 31, 2025)", (), ()),
        ("this year", "2026-01-01", "2026-10-03",
         "this year (Jan 1 to Oct 3, 2026)", (), ()),
        ("lately, anyone at LabCo", "2026-09-04", "2026-10-03",
         "lately (last 30 days)", ("labco",), ()),
        ("in the past 1 year", "2025-10-04", "2026-10-03",
         "in the last year (Oct 4, 2025 to Oct 3, 2026)", (), ()),
    ],
)  # fmt: skip
def test_time_phrases(
    query: str, start: str, end: str, label: str, terms: tuple[str, ...], kinds: tuple[str, ...]
) -> None:
    tq = parse_time_query(query, TODAY)
    assert tq is not None
    assert (tq.start.isoformat(), tq.end.isoformat()) == (start, end)
    assert tq.label == label
    assert tq.terms == terms
    assert tq.kinds == kinds


@pytest.mark.req("S-10")
@pytest.mark.parametrize(
    "query",
    ["data platform maria", "may", "since 2027-01-01", "since 2026-02-30", "since Feb 30",
     "last", "recent hires", ""],
)  # fmt: skip
def test_no_time_phrase(query: str) -> None:
    assert parse_time_query(query, TODAY) is None


@pytest.mark.req("S-10")
def test_first_phrase_wins_and_remainder_keeps_the_rest() -> None:
    tq = parse_time_query("Q4 LIS people yesterday or last week", TODAY)
    assert tq is not None
    assert tq.phrase == "yesterday"
    assert tq.remainder == "Q4 LIS people or last week"
    assert contacted_since(30, TODAY) == date(2026, 9, 4)


# ---------------------------------------------------------------- data


def _types(session: Session) -> dict[str, int]:
    return {t.name: t.id for t in session.scalars(select(ContactType))}


def _new(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    body = {"display_name": name, "contact_type_id": _types(session)["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


@pytest.fixture
def people(client: TestClient, db_session: Session) -> dict[str, int]:
    today = date.today()
    ids = {
        "recent": _new(client, db_session, "Rae Recent", notes="Handles the contract renewal"),
        "older": _new(client, db_session, "Olly Older"),
        "noted": _new(client, db_session, "Nia Noted"),
        "never": _new(client, db_session, "Nev Never", notes="Contract lawyer"),
        "stale": _new(client, db_session, "Stan Stale", notes="Old contract work"),
    }
    add_activity(db_session, ids["recent"], kind="message", summary="Sent the Q4 courier schedule",
                 occurred_on=today - timedelta(days=2))  # fmt: skip
    add_activity(db_session, ids["recent"], kind="meeting", summary="Kickoff",
                 occurred_on=today - timedelta(days=60))  # fmt: skip
    add_activity(db_session, ids["older"], kind="call", summary="Budget check-in",
                 occurred_on=today - timedelta(days=40))  # fmt: skip
    add_activity(db_session, ids["noted"], kind="note", summary="Prefers Teams",
                 occurred_on=today)  # fmt: skip
    add_activity(db_session, ids["stale"], kind="email", summary="Contract question",
                 occurred_on=today - timedelta(days=200))  # fmt: skip
    return ids


ROW = re.compile(r'data-contact-id="(\d+)"[^>]*data-testid="result-row"')


def _rows(html: str) -> list[int]:
    return [int(i) for i in ROW.findall(html)]


# ---------------------------------------------------------------- S-09 filter, sort, column


@pytest.mark.req("S-09")
def test_contacted_filter_sort_and_column(
    client: TestClient, db_session: Session, people: dict[str, int]
) -> None:
    week = client.get("/contacts/results", params={"contacted": "7"}).text
    assert _rows(week) == [people["recent"]]  # notes are not interactions
    assert "Contacted in the last 7 days" in week
    ninety = client.get("/contacts/results", params={"contacted": "90", "sort": "last_contact"})
    assert _rows(ninety.text) == [people["recent"], people["older"]]
    everyone = client.get("/contacts/results", params={"sort": "last_contact"}).text
    order = _rows(everyone)
    assert order[:3] == [people["recent"], people["older"], people["stale"]]
    assert set(order[3:]) >= {people["noted"], people["never"]}  # never contacted: last
    recent = date.today() - timedelta(days=2)
    assert f'<time datetime="{recent.isoformat()}">' in everyone
    assert 'data-testid="filter-contacted"' in client.get("/").text
    assert _rows(client.get("/contacts/results", params={"contacted": "5"}).text)  # ignored

    filters = SearchFilters(active_from=date.today() - timedelta(days=89))
    hits = search(db_session, "", filters, sort="last_contact")
    assert [h.contact.id for h in hits] == [people["recent"], people["older"]]
    latest = last_interactions(db_session, [people["recent"], people["noted"]])
    assert latest[people["recent"]].kind == "message"
    assert people["noted"] not in latest
    assert last_interactions(db_session, []) == {}

    assert clean_query({"contacted": "30", "q": ""}) == "contacted=30"
    assert describe_query("contacted=30") == "contacted in the last 30 days"


# ---------------------------------------------------------------- S-10 in the search box


@pytest.mark.req("S-10")
def test_who_have_i_interacted_with_recently(client: TestClient, people: dict[str, int]) -> None:
    html = client.get("/contacts/results", params={"q": "who have I interacted with recently"}).text
    assert _rows(html) == [people["recent"]]
    assert "Interacted recently (last 30 days)" in html
    assert "Message · " in html
    assert "Sent the Q4 courier schedule" in html
    assert "q=who+have+I+interacted+with" in html  # the chip removes the time limit


@pytest.mark.req("S-10")
def test_kinds_topics_and_empty_periods(client: TestClient, people: dict[str, int]) -> None:
    calls = client.get("/contacts/results", params={"q": "who did I call in the last 90 days"})
    assert _rows(calls.text) == [people["older"]]
    assert "· call" in calls.text
    meetings = client.get("/contacts/results", params={"q": "who did I meet in the past year"})
    assert _rows(meetings.text) == [people["recent"]]
    assert "Meeting · " in meetings.text  # the meeting, not the newer message

    # Remaining words are searched within the period only.
    topic = client.get("/contacts/results", params={"q": "contract work in the past year"})
    assert _rows(topic.text) == [people["stale"]]  # 200 days ago: inside the past year
    topic = client.get("/contacts/results", params={"q": "contract work in the past 90 days"})
    assert people["stale"] not in _rows(topic.text)
    broad = client.get("/contacts/results", params={"q": "contract in the past year"}).text
    assert people["never"] not in _rows(broad)  # mentions contracts, but no interactions

    none = client.get("/contacts/results", params={"q": "who did I email yesterday"}).text
    assert 'data-testid="no-results"' in none
    assert "No logged meetings, calls, emails or messages yesterday" in none


@pytest.mark.req("S-09", "S-10")
def test_search_api(client: TestClient, people: dict[str, int]) -> None:
    body = client.get("/api/search", params={"q": "recently"}).json()
    assert [b["contact"]["id"] for b in body] == [people["recent"]]
    assert body[0]["interaction"]["kind"] == "message"
    assert body[0]["last_contact"] == (date.today() - timedelta(days=2)).isoformat()
    body = client.get("/api/search", params={"contacted": 90}).json()
    assert {b["contact"]["id"] for b in body} == {people["recent"], people["older"]}
    assert client.get("/api/search", params={"contacted": 0}).status_code == 422


@pytest.mark.req("S-08", "S-10")
def test_meaning_search_respects_the_period(
    client: TestClient, db_session: Session, people: dict[str, int], settings: Settings
) -> None:
    service = SemanticService(settings, embedder=HashingEmbedder())
    while service.index_pending(db_session):
        pass
    words, filters, tq = apply_time_query("contract questions in the past 90 days", SearchFilters())
    assert tq is not None
    assert words == "contract questions"
    found = {h.contact.id for h in search_by_meaning(db_session, service, words)}
    assert people["stale"] in found
    within = {h.contact.id for h in search_by_meaning(db_session, service, words, filters)}
    assert people["stale"] not in within
    assert people["never"] not in within
