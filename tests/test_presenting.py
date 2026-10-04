"""Presenting mode: private details never reach the browser (P-01 to P-07, ADR-0016)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.config import Settings
from app.contacts import create_contact, to_out
from app.db import get_session
from app.lists import add_members, create_list
from app.main import create_app
from app.migrate import ensure_contact_types
from app.models import Contact, ContactType, CustomField, Tag
from app.privacy import (
    COOKIE,
    DEFAULT,
    NAME_FIELDS,
    PRESENTING,
    PRIVATE_FIELDS,
    WORK_FIELDS,
    Presenting,
    PrivacySettings,
    is_blocked,
    is_presenting,
    is_unlocked,
    load_privacy,
    parse_names,
    save_privacy,
)
from app.saved_searches import save_search
from app.schemas import ContactCreate, ContactOut
from app.search import search
from app.tags import add_tag
from tests.fake_embedder import HashingEmbedder

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')
# Every private value seeded below contains "zqxcanary" followed by a letter; a query that
# echoes the bare word back ("No contacts match “zqxcanary”") does not.
CANARY = re.compile(r"zqxcanary\w", re.IGNORECASE)
LAST_CONTACT = date.today() - timedelta(days=3)


@pytest.fixture
def app_client(settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """An app with search by meaning on (fake model), so the canary covers it too."""
    ensure_contact_types(db_session, settings.contact_types)
    app = create_app(
        settings, run_migrations=False, embedder=HashingEmbedder(), background_indexing=False
    )
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as client:
        yield client


def csrf(client: TestClient) -> str:
    found = TOKEN.search(client.get("/settings").text)
    assert found
    return found.group(1)


def present(client: TestClient, on: bool = True) -> None:
    client.cookies.set(COOKIE, "1" if on else "0")


def use_settings(client: TestClient, session: Session, settings: PrivacySettings) -> None:
    client.app.state.privacy = save_privacy(session, settings)  # type: ignore[attr-defined]


def _type_id(session: Session) -> int:
    found = session.scalars(select(ContactType.id).order_by(ContactType.sort_order)).first()
    if found is not None:
        return found
    created = ContactType(name="Colleague")
    session.add(created)
    session.flush()
    return created.id


def _contact(session: Session, name: str, **fields: Any) -> Contact:
    data = ContactCreate.model_validate(
        {"display_name": name, "contact_type_id": _type_id(session), **fields}
    )
    return create_contact(session, data)


@dataclass
class Seeded:
    public: Contact
    private: Contact
    plain: Contact
    public_list: int
    private_list: int
    public_tag: int
    private_tag: int
    saved: int


def seed(session: Session) -> Seeded:
    """One contact with a private value in every hideable place, plus a private contact."""
    private = _contact(
        session,
        "Zqxcanaryhidden Person",
        company="Zqxcanarycorp",
        emails=[{"email": "zqxcanaryboss@example.com", "label": "work"}],
    )
    private.is_private = True
    public = _contact(
        session,
        "Maria Lopez",
        company="Northwind Health",
        team="Data Platform",
        title="Integration lead",
        works_on="HL7 interfaces and lab results",
        notes="Met at HIMSS. zqxcanarynote: kids are Ana and Leo",
        location="Zqxcanarycity office",
        birthday="1985-03-03",  # C-20: personal
        manager_id=private.id,
        emails=[
            {"email": "maria@northwind.example", "label": "work", "is_primary": True},
            {"email": "zqxcanarypersonal@example.com", "label": "personal"},
        ],
        phones=[
            {"number": "+1 617 555 0101", "label": "work"},
            {"number": "+44 20 7946 0958", "label": "mobile"},
        ],
        addresses=[  # C-19: a work address is shown; a home address is personal
            {"label": "work", "street": "1 Harbor Way", "city": "Boston", "region": "MA"},
            {"label": "home", "street": "9 Zqxcanarystreet", "city": "Zqxcanaryhometown"},
        ],
        custom_fields=[
            {"name": "Birthday", "value": "zqxcanarybirthday March 3"},
            {"name": "Family", "value": "zqxcanaryfamily two kids"},
            {"name": "Desk", "value": "Building 4"},
        ],
    )
    plain = _contact(session, "Sam Okafor", team="Data Platform", company="Northwind Health")
    # P-08: every contact of a private type is private, and so is the type's name.
    kids = ContactType(name="Zqxcanarytype Kids", sort_order=99, is_private=True)
    session.add(kids)
    session.flush()
    _contact(session, "Zqxcanarykid Person", contact_type_id=kids.id)
    session.flush()
    for field in public.custom_fields:
        field.is_private = field.name == "Birthday"
    add_activity(
        session,
        public.id,
        kind="call",
        summary="zqxcanaryactivity talked about her move",
        occurred_on=LAST_CONTACT,
    )
    add_tag(session, [public.id, private.id], "informatics")
    secret_tag = add_tag(session, [public.id, plain.id], "zqxcanarytag-flight-risk")
    secret_tag.is_private = True
    shown_list = create_list(session, "Lab rollout")
    add_members(session, shown_list, [public.id, private.id], role_note="customer sponsor")
    hidden_list = create_list(session, "Zqxcanarylist renewal risk")
    hidden_list.is_private = True
    add_members(session, hidden_list, [public.id, plain.id])
    saved = save_search(session, "Flight risks zqxcanarysaved", "tag=zqxcanarytag-flight-risk")
    session.flush()
    from app.search import refresh_search

    refresh_search(session, [public.id, private.id, plain.id])
    session.flush()
    informatics = session.scalar(select(Tag.id).where(Tag.name == "informatics"))
    assert informatics is not None
    return Seeded(
        public=public,
        private=private,
        plain=plain,
        public_list=shown_list.id,
        private_list=hidden_list.id,
        public_tag=informatics,
        private_tag=secret_tag.id,
        saved=saved.id,
    )


def fresh(session: Session) -> None:
    """Each request in production has its own session; drop what the seeding loaded."""
    session.flush()
    session.expire_all()


# ---------------------------------------------------------------- pure rules


@pytest.mark.req("P-02")
def test_every_contact_field_is_classified_public_or_private() -> None:
    """A field added to ContactOut later stays hidden until someone classifies it."""
    fields = set(ContactOut.model_fields)
    assert fields == (WORK_FIELDS | set(PRIVATE_FIELDS)) & fields
    assert not WORK_FIELDS & set(PRIVATE_FIELDS)
    assert NAME_FIELDS <= WORK_FIELDS
    assert "notes" in PRIVATE_FIELDS


@pytest.mark.req("P-05")
@pytest.mark.parametrize(
    ("path", "blocked"),
    [
        ("/import", True),
        ("/import/preview", True),
        ("/duplicates/merge", True),
        ("/export/contacts.csv", True),
        ("/settings/backups/x.dump", True),
        ("/settings/privacy", True),
        ("/contacts/4/edit", True),
        ("/contacts/4/vcard", True),
        ("/contacts/4/export.json", True),
        ("/contacts/4", False),
        ("/lists/4/edit", False),
        ("/settings", False),
        ("/api/contacts", False),
    ],
)
def test_raw_data_pages_are_blocked(path: str, blocked: bool) -> None:
    assert is_blocked(path) is blocked


@pytest.mark.req("P-07")
def test_a_locked_instance_still_serves_the_toggle_and_assets() -> None:
    assert is_unlocked("/presenting")
    assert is_unlocked("/static/app.css")
    assert not is_unlocked("/")
    assert not is_unlocked("/api/contacts")


@pytest.mark.req("P-01", "P-07")
def test_the_cookie_wins_over_starting_presenting() -> None:
    start = replace(DEFAULT, start=True)
    assert is_presenting({COOKIE: "1"}, DEFAULT)
    assert not is_presenting({COOKIE: "0"}, start)
    assert is_presenting({}, start)
    assert not is_presenting({}, DEFAULT)


@pytest.mark.req("P-03")
def test_label_lists_are_trimmed_lower_case_and_unique() -> None:
    assert parse_names(" Personal, home ,HOME,, Mobile  phone ") == (
        "personal",
        "home",
        "mobile phone",
    )


@pytest.mark.req("P-03")
def test_privacy_settings_round_trip(db_session: Session) -> None:
    assert load_privacy(db_session) == DEFAULT
    chosen = PrivacySettings(
        hidden=frozenset({"notes", "location"}),
        labels=("home",),
        fields=("birthday",),
        look="none",
        off="2h",
        start=True,
        view="locked",
    )
    assert save_privacy(db_session, chosen) == chosen
    assert load_privacy(db_session) == chosen


@pytest.mark.req("P-02")
def test_redaction_keeps_only_public_fields(db_session: Session) -> None:
    s = seed(db_session)
    fresh(db_session)
    contact = db_session.get(Contact, s.public.id)
    assert contact is not None
    token = PRESENTING.set(Presenting(DEFAULT))
    try:
        out = to_out(contact, detail=True)
    finally:
        PRESENTING.reset(token)
    assert out.notes is None
    assert [e.email for e in out.emails] == ["maria@northwind.example"]
    assert [p.label for p in out.phones] == ["work"]
    assert [a.city for a in out.addresses] == ["Boston"]
    assert out.birthday is None
    assert out.links.mailto == "mailto:maria@northwind.example"
    assert out.links.tel is not None
    assert "7946" not in out.links.tel
    assert {f.name for f in out.custom_fields or []} == {"Family", "Desk"}  # Birthday flagged
    assert out.activities
    assert all(a.summary == "" for a in out.activities)
    assert out.manager is None  # a private contact
    assert {t.name for t in out.tags} == {"informatics"}
    assert {cl.name for cl in out.lists} == {"Lab rollout"}
    assert out.location == "Zqxcanarycity office"  # shown unless Settings hides it


@pytest.mark.req("P-02", "P-07")
def test_names_only_view_keeps_names_and_companies(db_session: Session) -> None:
    s = seed(db_session)
    fresh(db_session)
    contact = db_session.get(Contact, s.public.id)
    assert contact is not None
    token = PRESENTING.set(Presenting(replace(DEFAULT, view="names")))
    try:
        out = to_out(contact, detail=True)
    finally:
        PRESENTING.reset(token)
    assert (out.display_name, out.company) == ("Maria Lopez", "Northwind Health")
    assert out.title is None
    assert out.team is None
    assert out.works_on is None
    assert out.emails == []
    assert out.phones == []
    assert out.tags == []
    assert out.links.mailto is None
    assert out.links.tel is None


@pytest.mark.req("P-02")
def test_without_presenting_nothing_is_withheld(db_session: Session) -> None:
    s = seed(db_session)
    fresh(db_session)
    contact = db_session.get(Contact, s.public.id)
    assert contact is not None
    out = to_out(contact, detail=True)
    assert out.notes
    assert "zqxcanarynote" in out.notes
    assert len(out.emails) == 2
    assert out.manager is not None
    assert {t.name for t in out.tags} == {"informatics", "zqxcanarytag-flight-risk"}


# ---------------------------------------------------------------- the canary (ADR-0016)


def _api_routes(routes: list[Any]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):  # FastAPI's included routers
            yield from _api_routes(route.original_router.routes)


def _get_routes(app: Any) -> list[str]:
    return sorted(
        {
            r.path
            for r in _api_routes(app.routes)
            if "GET" in (r.methods or set()) and r.path != "/presenting"
        }
    )


def _fill(path: str, s: Seeded) -> list[str]:
    """Each GET route with its path parameters filled in, for public and private items."""
    values: dict[str, list[int | str]] = {
        "contact_id": [s.public.id, s.private.id, s.plain.id],
        "list_id": [s.public_list, s.private_list],
        "tag_id": [s.public_tag, s.private_tag],
        "type_id": [1],
        "search_id": [s.saved],
        "name": ["contacts-x.dump"],
    }
    paths = [path]
    for key, options in values.items():
        if "{" + key + "}" in path:
            paths = [p.replace("{" + key + "}", str(v)) for p in paths for v in options]
    return paths


QUERIES = (
    "",
    "?q=zqxcanary",
    "?q=kids",
    "?q=maria+zqxcanary",
    "?q=lab+results",
    "?q=talked+about+a+move+recently",
    "?q=family+birthday+who+is+moving",
    "?archived=1&sort=last_contact",
)


@pytest.mark.req("P-02", "P-04", "P-05")
def test_canary_no_private_value_reaches_any_page_or_api(
    app_client: TestClient, db_session: Session
) -> None:
    s = seed(db_session)
    every = PrivacySettings(hidden=frozenset({"notes", "activity", "personal", "fields",
                                              "location", "photo", "last_contact"}),
                            fields=("family",))  # fmt: skip
    use_settings(app_client, db_session, every)
    semantic = app_client.app.state.semantic  # type: ignore[attr-defined]
    semantic.index_pending(db_session)
    fresh(db_session)
    present(app_client)
    extra = [
        f"/?list={s.private_list}",
        f"/?manager={s.private.id}",
        f"/org?root={s.private.id}",
        "/api/contacts/lookup?q=zqx",
        "/api/tags?q=zqx",
        "/api/search/meaning?q=talked+about+her+move",
        # Every filter, so joins that alias a table (related tags joins tag twice) run too.
        "/?tag=informatics",
        "/contacts/results?tag=informatics&q=maria",
        f"/?list={s.public_list}",
        "/?team=Data+Platform&company=Northwind+Health&favorites=1&due=1&contacted=30",
        "/api/search?tag=informatics",
        "/lists?tag=informatics",
    ]
    checked = 0
    for route in _get_routes(app_client.app):
        for path in _fill(route, s):
            for query in QUERIES:
                response = app_client.get(path + query, follow_redirects=False)
                assert response.status_code < 500, (path + query, response.status_code)
                body = response.text
                leak = CANARY.search(body)
                assert leak is None, (
                    f"{path + query} shows {body[leak.start() - 80 : leak.end() + 40]!r}"
                )
                assert "7946" not in body, path + query  # the mobile number
                assert LAST_CONTACT.isoformat() not in body, path + query
                checked += 1
    for path in extra:
        response = app_client.get(path)
        assert response.status_code < 500, path
        assert CANARY.search(response.text) is None, path
    assert checked > 200  # every GET page, fragment and API route was rendered


@pytest.mark.req("P-02")
def test_canary_markers_do_show_when_not_presenting(
    app_client: TestClient, db_session: Session
) -> None:
    """The canary must be able to fail: the same pages show the values normally."""
    s = seed(db_session)
    fresh(db_session)
    card = app_client.get(f"/contacts/{s.public.id}").text
    for marker in ("zqxcanarynote", "zqxcanarypersonal", "zqxcanarybirthday", "zqxcanarytag",
                   "Zqxcanarylist", "Zqxcanaryhidden", "zqxcanaryactivity"):  # fmt: skip
        assert marker in card


# ---------------------------------------------------------------- turning it on and off (P-01)


@pytest.mark.req("P-01")
def test_present_button_sets_a_cookie_for_every_instance(client: TestClient) -> None:
    token = csrf(client)
    page = client.get("/").text
    assert 'data-testid="present-toggle"' in page
    assert 'aria-pressed="false"' in page
    response = client.post(
        "/presenting",
        data={"csrf_token": token, "on": "1", "next": "/lists"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/lists"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=1;")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Max-Age" not in cookie  # default: off when the browser closes
    page = client.get("/").text
    assert 'data-testid="presenting-bar"' in page
    assert "is-presenting" in page
    off = client.post(
        "/presenting", data={"csrf_token": token, "on": "0", "next": "/"}, follow_redirects=False
    )
    assert off.headers["set-cookie"].startswith(f"{COOKIE}=0;")
    assert 'data-testid="presenting-bar"' not in client.get("/").text


@pytest.mark.req("P-01")
def test_presenting_toggle_needs_the_csrf_token(client: TestClient) -> None:
    assert client.post("/presenting", data={"on": "1"}).status_code == 403


@pytest.mark.req("P-01")
def test_two_hour_setting_gives_the_cookie_a_lifetime(
    client: TestClient, db_session: Session
) -> None:
    use_settings(client, db_session, replace(DEFAULT, off="2h"))
    response = client.post(
        "/presenting", data={"csrf_token": csrf(client), "on": "1"}, follow_redirects=False
    )
    assert "Max-Age=7200" in response.headers["set-cookie"]


@pytest.mark.req("P-01")
def test_turning_it_on_from_a_hidden_page_lands_on_the_contacts(
    client: TestClient, db_session: Session
) -> None:
    s = seed(db_session)
    token = csrf(client)
    for target in (f"/contacts/{s.private.id}", f"/contacts/{s.public.id}/edit", "/import"):
        response = client.post(
            "/presenting",
            data={"csrf_token": token, "on": "1", "next": target},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/", target
    response = client.post(
        "/presenting",
        data={"csrf_token": token, "on": "1", "next": f"/contacts/{s.public.id}"},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"/contacts/{s.public.id}"


@pytest.mark.req("P-07")
def test_an_instance_can_start_every_visit_presenting(
    client: TestClient, db_session: Session
) -> None:
    use_settings(client, db_session, replace(DEFAULT, start=True))
    client.cookies.clear()
    response = client.get("/")
    assert 'data-testid="presenting-bar"' in response.text
    assert response.headers["set-cookie"].count(f"{COOKIE}=1") == 1
    present(client, on=False)  # stopped earlier in this browser session
    assert 'data-testid="presenting-bar"' not in client.get("/").text


# ---------------------------------------------------------------- pages while presenting


@pytest.mark.req("P-02", "P-03")
def test_card_shows_placeholders_for_what_is_hidden(
    client: TestClient, db_session: Session
) -> None:
    s = seed(db_session)
    use_settings(client, db_session, replace(DEFAULT, fields=("family",)))
    fresh(db_session)
    present(client)
    card = client.get(f"/contacts/{s.public.id}").text
    assert "Maria Lopez" in card
    assert "HL7 interfaces" in card
    assert 'data-testid="hidden-notes"' in card
    assert "3 personal addresses or numbers hidden while presenting" in card  # + home (C-19)
    assert "1 private tag hidden while presenting" in card
    assert "1 private list hidden while presenting" in card
    assert "2 private fields hidden while presenting" in card
    assert "details hidden while presenting" in card  # the activity summary
    assert 'data-testid="hidden-manager"' in card  # the private manager, not "None"
    assert 'data-testid="edit"' not in card
    assert 'data-testid="private-toggle"' not in card
    assert "Building 4" in card


@pytest.mark.req("P-02")
def test_leave_no_trace_drops_the_placeholders(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    use_settings(client, db_session, replace(DEFAULT, look="none"))
    fresh(db_session)
    present(client)
    card = client.get(f"/contacts/{s.public.id}").text
    assert "hidden while presenting" not in card
    assert "Notes" not in re.sub(r"<[^>]+>", " ", card).split("Works on", 1)[1]


@pytest.mark.req("P-02", "P-03")
def test_a_private_contact_is_left_out_everywhere(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    fresh(db_session)
    present(client)
    assert client.get(f"/contacts/{s.private.id}").status_code == 404
    assert client.get(f"/api/contacts/{s.private.id}").status_code == 404
    names = [c["display_name"] for c in client.get("/api/contacts").json()]
    assert "Maria Lopez" in names
    assert "Zqxcanaryhidden Person" not in names
    members = client.get(f"/lists/{s.public_list}").text
    assert "Maria Lopez" in members
    assert "Zqxcanaryhidden" not in members
    assert client.get(f"/lists/{s.private_list}").status_code == 404


@pytest.mark.req("P-05")
def test_raw_data_pages_say_they_are_unavailable(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    present(client)
    for path in ("/import", "/duplicates", f"/contacts/{s.public.id}/edit", "/export/contacts.csv"):
        response = client.get(path)
        assert response.status_code == 403, path
        assert "Not available while presenting" in response.text, path
    settings_page = client.get("/settings").text
    assert "Stop presenting to change these settings" in settings_page


@pytest.mark.req("P-07")
def test_a_locked_instance_shows_only_a_lock_screen(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    use_settings(client, db_session, replace(DEFAULT, view="locked"))
    present(client)
    page = client.get("/")
    assert page.status_code == 403
    assert 'data-testid="locked"' in page.text
    assert "Maria" not in page.text
    assert "Reconnect" not in page.text  # no navigation or counts
    assert client.get("/api/contacts").json() == {"detail": "Not available while presenting"}
    assert client.get("/static/app.css").status_code == 200
    token = TOKEN.search(page.text)
    assert token
    response = client.post(
        "/presenting", data={"csrf_token": token.group(1), "on": "0"}, follow_redirects=False
    )
    assert response.status_code == 303


@pytest.mark.req("P-07")
def test_names_view_shows_names_and_companies_only(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    use_settings(client, db_session, replace(DEFAULT, view="names"))
    fresh(db_session)
    present(client)
    page = client.get("/").text
    assert "Maria Lopez" in page
    assert "Northwind Health" in page
    assert "maria@northwind.example" not in page
    assert "Integration lead" not in page
    card = client.get(f"/contacts/{s.public.id}").text
    assert 'data-testid="names-only"' in card
    assert "HL7" not in card


# ---------------------------------------------------------------- search (P-04, P-06)


@pytest.mark.req("P-04")
def test_search_matches_hidden_fields_without_quoting_them(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    fresh(db_session)
    present(client)
    page = client.get("/contacts/results?q=kids").text
    assert "Maria Lopez" in page
    assert "Matched in notes · hidden while presenting" in page
    assert "Ana and Leo" not in page
    flight = client.get("/contacts/results?q=flight").text
    assert "Maria Lopez" in flight
    assert "Matched in a hidden detail" in flight
    assert "flight-risk" not in flight
    shown = client.get("/contacts/results?q=lab+results").text
    assert "works on:" in shown  # public context is still quoted


@pytest.mark.req("P-04")
def test_search_counts_private_contacts_it_leaves_out(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    fresh(db_session)
    present(client)
    page = client.get("/contacts/results?q=informatics").text
    assert "Maria Lopez" in page
    assert "Zqxcanaryhidden" not in page
    assert "1 private contact hidden while presenting" in page
    nobody = client.get("/contacts/results?q=zqxcanarycorp").text
    assert 'data-testid="no-results"' in nobody
    # the private company's contact, and the private-type contact whose name is a typo match
    assert "2 private contacts hidden while presenting" in nobody


@pytest.mark.req("P-04")
def test_search_function_hides_private_contacts_only_while_presenting(
    db_session: Session,
) -> None:
    seed(db_session)
    fresh(db_session)
    everyone = {h.contact.display_name for h in search(db_session, "informatics")}
    assert everyone == {"Maria Lopez", "Zqxcanaryhidden Person"}
    db_session.expire_all()
    token = PRESENTING.set(Presenting(DEFAULT))
    try:
        shown = {h.contact.display_name for h in search(db_session, "informatics")}
    finally:
        PRESENTING.reset(token)
    assert shown == {"Maria Lopez"}


@pytest.mark.req("P-06")
def test_copy_and_compose_get_work_addresses_only(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    fresh(db_session)
    present(client)
    page = client.get("/").text
    assert 'data-email="maria@northwind.example"' in page
    assert "zqxcanarypersonal" not in page
    members = client.get(f"/lists/{s.public_list}").text
    assert 'data-email="maria@northwind.example"' in members


@pytest.mark.req("P-04")
def test_api_search_blanks_hidden_activity(client: TestClient, db_session: Session) -> None:
    seed(db_session)
    fresh(db_session)
    present(client)
    hits = client.get("/api/search", params={"q": "maria recently"}).json()
    assert hits
    assert hits[0]["interaction"]["summary"] == ""
    assert hits[0]["contact"]["notes"] is None


# ---------------------------------------------------------------- settings (P-03)


@pytest.mark.req("P-03")
def test_settings_page_saves_choices(client: TestClient, db_session: Session) -> None:
    seed(db_session)
    page = client.get("/settings/privacy")
    assert page.status_code == 200
    assert 'data-testid="private-tag-' in page.text
    token = csrf(client)
    response = client.post(
        "/settings/privacy",
        data={
            "csrf_token": token,
            "hidden": ["notes", "location"],
            "labels": "Home, cell",
            "look": "none",
            "off": "manual",
            "start": "1",
            "view": "names",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = load_privacy(db_session)
    assert saved.hidden == {"notes", "location"}
    assert saved.labels == ("home", "cell")
    assert (saved.look, saved.off, saved.start, saved.view) == ("none", "manual", True, "names")
    assert client.app.state.privacy == saved  # type: ignore[attr-defined]


@pytest.mark.req("P-03")
def test_settings_marks_tags_lists_fields_and_contacts_private(
    client: TestClient, db_session: Session
) -> None:
    s = seed(db_session)
    token = csrf(client)

    def mark(kind: str, key: object, private: bool) -> int:
        return client.post(
            "/settings/privacy/item",
            data={
                "csrf_token": token,
                "kind": kind,
                "key": str(key),
                "private": "1" if private else "0",
            },
            follow_redirects=False,
        ).status_code

    assert mark("tag", s.public_tag, True) == 303
    assert mark("list", s.private_list, False) == 303
    assert mark("contact", s.private.id, False) == 303
    assert mark("field", "desk", True) == 303
    assert mark("tag", 999999, True) == 404
    assert mark("nonsense", 1, True) == 422
    db_session.expire_all()
    assert db_session.get(Tag, s.public_tag).is_private  # type: ignore[union-attr]
    assert not s.private.is_private
    desk = db_session.scalars(select(CustomField).where(CustomField.name == "Desk")).one()
    assert desk.is_private
    assert "desk" in load_privacy(db_session).fields
    assert mark("field", "Desk", False) == 303
    db_session.expire_all()
    assert not desk.is_private
    assert "desk" not in load_privacy(db_session).fields


@pytest.mark.req("P-03")
def test_card_switch_marks_a_contact_private(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    card = client.get(f"/contacts/{s.plain.id}").text
    assert 'data-testid="private-toggle"' in card
    response = client.post(
        f"/contacts/{s.plain.id}/private",
        data={"csrf_token": csrf(client), "private": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(s.plain)
    assert s.plain.is_private
    assert "Marked private" in client.get(response.headers["location"]).text


@pytest.mark.req("P-02")
def test_saved_searches_naming_private_items_are_hidden(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    fresh(db_session)
    assert "zqxcanarysaved" in client.get("/saved-searches").text
    present(client)
    assert "zqxcanarysaved" not in client.get("/saved-searches").text


@pytest.mark.req("P-03")
def test_categories_left_unchecked_stay_visible(client: TestClient, db_session: Session) -> None:
    s = seed(db_session)
    use_settings(client, db_session, replace(DEFAULT, hidden=frozenset()))
    fresh(db_session)
    present(client)
    card = client.get(f"/contacts/{s.public.id}").text
    assert "zqxcanarynote" in card
    assert "zqxcanaryactivity" in card
    assert "zqxcanarypersonal@example.com" in card
    assert "zqxcanarybirthday" in card
    assert "zqxcanarytag" not in card  # private tags, lists and contacts always vanish
    assert "Zqxcanarylist" not in card


@pytest.mark.req("P-04")
def test_meaning_text_is_quoted_only_from_shown_sources() -> None:
    from app.semantic import quotable

    on = Presenting(DEFAULT)
    assert quotable("notes", None)
    assert quotable("works_on", on)
    assert not quotable("notes", on)
    assert not quotable("activity", on)
    assert not quotable("profile", on)  # can name private tags or lists
    assert quotable("notes", Presenting(replace(DEFAULT, hidden=frozenset())))
    assert not quotable("works_on", Presenting(replace(DEFAULT, view="names")))


@pytest.mark.req("P-02", "T-05")
def test_tag_filter_with_related_tags_works_while_presenting(
    client: TestClient, db_session: Session
) -> None:
    """Regression: related tags join the tag table twice; the private filter must follow."""
    seed(db_session)
    fresh(db_session)
    present(client)
    page = client.get("/?tag=informatics")
    assert page.status_code == 200
    assert "Maria Lopez" in page.text
    assert "zqxcanarytag" not in page.text  # the private tag is not offered as "often together"


@pytest.mark.req("P-02", "L-01", "T-01")
def test_list_and_tag_counts_leave_out_private_contacts(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    fresh(db_session)

    def lab_rollout_count() -> str:
        page = client.get("/lists").text
        row = page.split("Lab rollout</a></td>", 1)[1].split("</tr>", 1)[0]
        cells = [c.split("<", 1)[0] for c in row.split("<td>")[1:]]
        return cells[2]

    def informatics_count() -> str:
        page = client.get("/tags").text
        return page.split('informatics <span class="count">', 1)[1].split("<", 1)[0]

    assert (lab_rollout_count(), informatics_count()) == ("2", "2")
    present(client)
    assert (lab_rollout_count(), informatics_count()) == ("1", "1")
