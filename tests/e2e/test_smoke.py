"""Browser smoke test (run with `make e2e`). Starts a real server and opens it in Chromium."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url(settings: Settings) -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
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


@pytest.mark.req("I-03")
def test_home_page_renders_instance_banner(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        # PLAYWRIGHT_CHROMIUM_EXECUTABLE lets you use an already-installed Chromium.
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        page.goto(base_url)
        expect(page.get_by_test_id("instance-name")).to_have_text("Test")
        expect(page.get_by_test_id("env-badge")).to_have_text("TEST")
        expect(page.get_by_test_id("empty-state")).to_be_visible()
        # The banner must actually render in the instance color (#bf3989), not just exist.
        expect(page.get_by_test_id("instance-bar")).to_have_css(
            "background-color", "rgb(191, 57, 137)"
        )
        assert page.title() == "All contacts · Test"
        browser.close()


@pytest.mark.req("C-01", "C-07", "M-04")
def test_add_contacts_and_pick_manager_by_typing(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # A manager with only a name (C-01).
        page.goto(f"{base_url}/contacts/new")
        page.get_by_label("Display name").fill("Maria Browserton")
        page.get_by_test_id("save").click()
        expect(page.get_by_test_id("flash")).to_have_text("Saved.")

        # A report: pick the manager by typing part of the name (C-07).
        page.goto(f"{base_url}/contacts/new")
        page.get_by_label("Display name").fill("Dev Browserton")
        page.get_by_test_id("manager-input").press_sequentially("Maria Brow", delay=20)
        option = page.get_by_test_id("manager-options").get_by_role("option").first
        expect(option).to_contain_text("Maria Browserton")
        option.click()
        expect(page.get_by_test_id("manager-input")).to_have_value("Maria Browserton")

        page.get_by_label("Email 1", exact=True).fill("dev@acme.example")
        page.get_by_role("button", name="+ Add phone").click()
        page.locator('input[name="phone_number"]').last.fill("404-555-0199")
        page.get_by_test_id("save").click()

        # Card: manager link and one-click actions (M-04).
        expect(page.get_by_test_id("manager")).to_contain_text("Maria Browserton")
        expect(page.get_by_test_id("action-email")).to_have_attribute(
            "href", "mailto:dev@acme.example"
        )
        expect(page.get_by_test_id("action-call")).to_have_attribute("href", "tel:+14045550199")
        expect(page.get_by_test_id("action-teams")).to_have_attribute(
            "href", "https://teams.microsoft.com/l/chat/0/0?users=dev@acme.example"
        )

        # Manager's card lists the new direct report.
        page.get_by_test_id("manager").get_by_role("link").click()
        expect(page.get_by_test_id("reports")).to_contain_text("Dev Browserton")

        assert errors == []
        browser.close()
