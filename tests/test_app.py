"""Application shell: health check, home page, instance banner, security headers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import APP_DIR, SECURITY_HEADERS, create_app
from app.migrate import head_revision
from app.models import Contact, ContactType
from tests.conftest import make_settings


def test_healthz_reports_instance_and_database(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "instance": "Test",
        "env": "test",
        "status": "ok",
        "database": "ok",
        "revision": head_revision(),
    }


def test_healthz_returns_503_when_database_unreachable() -> None:
    settings = make_settings("postgresql://nobody:nothing@127.0.0.1:1/none")
    with TestClient(create_app(settings, run_migrations=False)) as client:
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_home_page_shows_instance_name_and_empty_state(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "<title>All contacts · Test</title>" in html
    assert 'data-testid="instance-name">Test<' in html
    assert 'href="http://testserver/instance.css"' in html
    assert 'data-testid="env-badge">TEST<' in html
    assert "No contacts yet." in html


def test_home_page_lists_active_contacts_only(client: TestClient, db_session: Session) -> None:
    employee = db_session.scalars(select(ContactType).where(ContactType.name == "Employee")).one()
    db_session.add_all(
        [
            Contact(display_name="Maria Lopez", contact_type=employee, team="Data Platform"),
            Contact(
                display_name="Old Contact",
                contact_type=employee,
                archived_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    db_session.flush()

    html = client.get("/").text

    assert "Maria Lopez" in html
    assert "Data Platform" in html
    assert "Old Contact" not in html


@pytest.mark.req("I-03")
def test_instance_color_served_as_stylesheet(client: TestClient) -> None:
    response = client.get("/instance.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.text == ":root { --instance-color: #bf3989; --instance-on: #ffffff; }\n"


def test_templates_use_no_inline_styles_blocked_by_csp() -> None:
    """The CSP forbids inline style attributes; a template using one would silently lose styling."""
    for template in (APP_DIR / "templates").rglob("*.html"):
        assert "style=" not in template.read_text(encoding="utf-8"), template.name


def test_security_headers_are_set(client: TestClient) -> None:
    response = client.get("/healthz")
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_api_docs_hidden_in_production(settings: Settings) -> None:
    prod = make_settings(str(settings.database_url), app_env="production")
    with TestClient(create_app(prod, run_migrations=False)) as client:
        assert client.get("/docs").status_code == 404
        assert 'data-testid="env-badge"' not in client.get("/").text
