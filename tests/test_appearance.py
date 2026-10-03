"""Theme, palette and density, saved per instance and rendered by the server (A-01 to A-05)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.datastructures import State

from app.appearance import (
    DEFAULT,
    Appearance,
    Palette,
    contrast_ratio,
    current_appearance,
    forget_appearance,
    load_appearance,
    save_appearance,
    text_on,
)
from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.migrate import ensure_contact_types
from app.models import AppSetting
from tests.conftest import make_settings

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


def save(client: TestClient, **fields: str) -> int:
    """Post the Settings form; returns the status code."""
    return client.post(
        "/settings/appearance",
        data={"csrf_token": csrf(client), **fields},
        follow_redirects=False,
    ).status_code


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
    assert response.json() == {"theme": "dark", "palette": "harbor", "density": "comfortable"}


@pytest.mark.req("A-03")
@pytest.mark.parametrize(
    "fields", [{"theme": "sepia"}, {"palette": "neon"}, {"density": "cozy"}, {"theme": ""}]
)
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


@pytest.mark.req("A-02")
@pytest.mark.parametrize("palette", ["harbor", "sage", "clay"])
def test_each_palette_can_be_chosen_and_is_rendered(client: TestClient, palette: str) -> None:
    assert save(client, palette=palette) == 303
    assert f'data-palette="{palette}"' in html_tag(client)
    page = client.get("/settings").text
    assert re.search(rf'value="{palette}" checked data-testid="settings-palette-{palette}"', page)


@pytest.mark.req("A-02")
def test_settings_previews_every_palette_in_light_and_dark(client: TestClient) -> None:
    page = client.get("/settings").text
    for palette in ("harbor", "sage", "clay"):
        assert f'class="palette-preview" data-palette="{palette}"' in page
    assert page.count('class="preview-light"') == 3
    assert page.count('class="preview-dark"') == 3


@pytest.mark.req("A-05")
def test_compact_density_is_saved_and_rendered(client: TestClient) -> None:
    assert 'data-density="comfortable"' in html_tag(client)
    save(client, density="compact")
    assert 'data-density="compact"' in html_tag(client)
    assert re.search(
        r'value="compact" checked data-testid="settings-density-compact"',
        client.get("/settings").text,
    )


@pytest.fixture
def clay_client(database_url: str, db_session: Session) -> Iterator[TestClient]:
    """An instance whose env file says DEFAULT_PALETTE=clay."""
    settings = make_settings(database_url, default_palette="clay")
    ensure_contact_types(db_session, settings.contact_types)
    app = create_app(settings, run_migrations=False)
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.req("A-02", "I-01")
def test_default_palette_comes_from_the_env_file_until_one_is_chosen(
    clay_client: TestClient,
) -> None:
    assert 'data-palette="clay"' in html_tag(clay_client)
    save(clay_client, theme="dark")  # saving the theme keeps the instance's default palette
    assert 'data-palette="clay"' in html_tag(clay_client)
    save(clay_client, palette="sage")
    assert 'data-palette="sage"' in html_tag(clay_client)


@pytest.mark.req("I-01")
def test_an_unknown_default_palette_is_a_configuration_error(database_url: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url, default_palette="neon")


def test_settings_and_appearance_accept_the_same_palettes() -> None:
    field = Settings.model_fields["default_palette"]
    assert get_args(field.annotation) == get_args(Palette)


@pytest.mark.req("I-03")
@pytest.mark.parametrize(
    ("color", "text"),
    [
        ("#1f6feb", "#ffffff"),  # business-prod blue
        ("#8250df", "#ffffff"),  # personal-prod purple
        ("#bf3989", "#ffffff"),
        ("#2da44e", "#141c26"),  # mid green: dark text reads better
        ("#f2c94c", "#141c26"),  # yellow
    ],
)
def test_instance_band_text_is_whichever_color_reads_better(color: str, text: str) -> None:
    assert text_on(color) == text


def test_contrast_ratio_matches_wcag_reference_values() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)


@pytest.mark.req("I-03")
def test_instance_stylesheet_sets_a_readable_band_text_color(database_url: str) -> None:
    app = create_app(make_settings(database_url, instance_color="#f2c94c"), run_migrations=False)
    with TestClient(app) as test_client:
        css = test_client.get("/instance.css").text
    assert "--instance-color: #f2c94c;" in css
    assert "--instance-on: #141c26;" in css
