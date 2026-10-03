"""Theme mode and palette, saved per instance and rendered by the server (A-01, A-03, ADR-0015)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.datastructures import State

from app.appearance import (
    DEFAULT,
    Appearance,
    current_appearance,
    forget_appearance,
    load_appearance,
    save_appearance,
)
from app.models import AppSetting

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')
HTML_TAG = re.compile(r"<html [^>]*>")


def csrf(client: TestClient) -> str:
    match = TOKEN.search(client.get("/").text)
    assert match, "page has no CSRF token"
    return match.group(1)


def html_tag(client: TestClient, path: str = "/") -> str:
    match = HTML_TAG.search(client.get(path).text)
    assert match, f"{path} has no <html> tag"
    return match.group(0)


def save(client: TestClient, **fields: str) -> object:
    return client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), **fields},
        follow_redirects=False,
    )


@pytest.mark.req("A-01", "A-03")
def test_pages_default_to_the_system_theme_and_harbor(client: TestClient) -> None:
    tag = html_tag(client)
    assert 'data-theme="system"' in tag
    assert 'data-palette="harbor"' in tag


@pytest.mark.req("A-01", "A-03")
def test_a_saved_theme_is_rendered_on_every_page_and_stored_in_the_instance(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), "theme": "dark"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings?notice=appearance#appearance-h"
    for path in ("/", "/settings", "/tags", "/lists"):
        assert 'data-theme="dark"' in html_tag(client, path)
    stored = db_session.scalar(select(AppSetting.value).where(AppSetting.key == "theme"))
    assert stored == "dark"


@pytest.mark.req("A-01")
def test_the_header_switch_marks_the_choice_and_returns_to_the_same_page(
    client: TestClient,
) -> None:
    assert re.search(r'value="system" checked data-testid="theme-system"', client.get("/").text)
    response = client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), "theme": "light", "next": "/?q=maria"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?q=maria"
    assert re.search(r'value="light" checked data-testid="theme-light"', client.get("/").text)


@pytest.mark.req("A-03")
def test_an_off_site_next_is_ignored(client: TestClient) -> None:
    response = client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), "theme": "light", "next": "//evil.example/"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


@pytest.mark.req("A-03")
def test_the_script_enhanced_switch_gets_json(client: TestClient) -> None:
    response = client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), "theme": "dark"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"theme": "dark", "palette": "harbor"}


@pytest.mark.req("A-03")
@pytest.mark.parametrize("fields", [{"theme": "sepia"}, {"palette": "neon"}, {"theme": ""}])
def test_unknown_values_are_rejected_and_nothing_changes(
    client: TestClient, fields: dict[str, str]
) -> None:
    response = client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), **fields},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert 'data-theme="system"' in html_tag(client)


@pytest.mark.req("A-03")
def test_saving_requires_the_csrf_token(client: TestClient) -> None:
    response = client.post("/settings/appearance", data={"theme": "dark"})
    assert response.status_code == 403
    assert 'data-theme="system"' in html_tag(client)


@pytest.mark.req("A-01")
def test_settings_offers_every_theme_with_the_current_one_checked(client: TestClient) -> None:
    page = client.get("/settings").text
    assert 'id="appearance-h"' in page
    assert re.search(r'value="system" checked data-testid="settings-theme-system"', page)
    assert 'data-testid="settings-theme-light"' in page
    assert 'data-testid="settings-theme-dark"' in page


def test_load_falls_back_to_defaults_for_unknown_stored_values(db_session: Session) -> None:
    db_session.add_all(
        [AppSetting(key="theme", value="sepia"), AppSetting(key="palette", value="neon")]
    )
    db_session.flush()
    assert load_appearance(db_session) == DEFAULT


def test_save_changes_only_the_given_values_and_rejects_unknown_ones(db_session: Session) -> None:
    assert save_appearance(db_session, theme="light") == Appearance(theme="light")
    assert save_appearance(db_session, palette="harbor") == Appearance(theme="light")
    assert save_appearance(db_session, theme="dark") == Appearance(theme="dark")
    with pytest.raises(ValueError, match="unknown theme"):
        save_appearance(db_session, theme="sepia")


def test_the_cached_choice_is_reloaded_after_a_restore_and_defaults_if_the_database_is_down() -> (
    None
):
    def unreachable() -> Session:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    state = State()
    state.appearance = Appearance(theme="dark")
    state.session_factory = unreachable
    assert current_appearance(state) == Appearance(theme="dark")
    forget_appearance(state)
    assert current_appearance(state) == DEFAULT
