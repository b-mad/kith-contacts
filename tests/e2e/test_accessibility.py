"""Automated WCAG 2.2 AA checks with axe-core, in every palette and mode (A-04, A-06, N-09).

Runs against a production-mode instance (themed header with the instance stripe and chip)
and a development-mode one (full striped band), so both headers are covered.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
import uvicorn
from psycopg import sql

from app.config import Settings
from app.main import create_app
from app.migrate import upgrade_to_head
from tests.conftest import _database_url, make_settings

pytestmark = pytest.mark.e2e

WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
PAGES = [
    "/",
    "/?q=Ada",
    "/contacts/new",
    "/settings",
    "/tags",
    "/lists",
    "/org",
    "/import",
    "/duplicates",
    "/saved-searches",
]
TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _serve(settings: Settings) -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:  # pragma: no cover
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def a11y_database(admin_url: str) -> Iterator[str]:
    """Its own database, so the sample contacts don't leak into other browser tests."""
    name = f"contacts_test_a11y_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _database_url(name)
    try:
        upgrade_to_head(make_settings(url))
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="module")
def prod_url(a11y_database: str) -> Iterator[str]:
    settings = make_settings(
        a11y_database,
        app_env="production",
        auto_backup=False,
        instance_name="Business",
        instance_color="#1f6feb",
    )
    yield from _serve(settings)


@pytest.fixture(scope="module")
def dev_url(a11y_database: str) -> Iterator[str]:
    yield from _serve(make_settings(a11y_database, app_env="development"))


def _violations(page: Any) -> list[str]:
    from axe_playwright_python.sync_playwright import Axe

    results = Axe().run(page, options={"runOnly": {"type": "tag", "values": WCAG_22_AA}})
    found = []
    for v in results.response["violations"]:
        targets = ", ".join(str(n["target"]) for n in v["nodes"][:3])
        found.append(f"{v['id']} ({v['impact']}): {v['help']} — {targets}")
    return found


def _set(page: Any, base: str, **fields: str) -> None:
    page.goto(base + "/settings")
    match = TOKEN.search(page.content())
    assert match
    response = page.request.post(
        base + "/settings/appearance",
        form={"csrf_token": match.group(1), **fields},
        headers={"Accept": "application/json"},
    )
    assert response.ok, response.text()


def _seed(page: Any, base: str) -> int:
    """One contact with a manager, emails, phone, notes and a tag, so pages have content."""
    types = page.request.get(base + "/api/contact-types").json()
    employee = next(t["id"] for t in types if t["name"] == "Employee")
    manager = page.request.post(
        base + "/api/contacts",
        data={"display_name": "Grace Hopper", "contact_type_id": employee, "team": "Platform"},
    ).json()
    ada = page.request.post(
        base + "/api/contacts",
        data={
            "display_name": "Ada Lovelace",
            "contact_type_id": employee,
            "team": "Platform",
            "title": "Analyst",
            "manager_id": manager["id"],
            "notes": "Met at the analytics summit.",
            "emails": [{"email": "ada@example.com", "label": "work", "is_primary": True}],
            "phones": [{"number": "+14045550142", "label": "mobile"}],
        },
    ).json()
    page.goto(base + f"/contacts/{ada['id']}")
    match = TOKEN.search(page.content())
    assert match
    page.request.post(
        base + f"/contacts/{ada['id']}/tags", form={"csrf_token": match.group(1), "tag": "HL7"}
    )
    return int(ada["id"])


@pytest.mark.req("A-04", "A-06", "N-09")
def test_every_page_passes_axe_in_every_palette_and_mode(prod_url: str, dev_url: str) -> None:
    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        contact_id = _seed(page, prod_url)
        pages = [*PAGES, f"/contacts/{contact_id}", f"/contacts/{contact_id}/edit"]
        try:
            for palette in ("harbor", "sage", "clay"):
                for theme in ("light", "dark"):
                    _set(page, prod_url, theme=theme, palette=palette)
                    for path in pages:
                        page.goto(prod_url + path)
                        failures += [f"{palette}/{theme} {path}: {v}" for v in _violations(page)]
            # The development header (striped instance band) in both modes.
            for theme in ("light", "dark"):
                _set(page, dev_url, theme=theme, palette="harbor")
                page.goto(dev_url + "/")
                failures += [f"dev/{theme} /: {v}" for v in _violations(page)]
        finally:
            _set(page, prod_url, theme="system", palette="harbor")
            browser.close()
    assert not failures, "\n".join(failures)
