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
