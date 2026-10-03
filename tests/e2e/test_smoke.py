"""Browser smoke test (run with `make e2e`). Starts a real server and opens it in Chromium."""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

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


def _make(page: object, base_url: str, body: dict[str, object]) -> dict[str, object]:
    response = page.request.post(f"{base_url}/api/contacts", data=body)  # type: ignore[attr-defined]
    assert response.status == 201, response.text()
    result: dict[str, object] = response.json()
    return result


@pytest.mark.req("S-05", "M-01", "M-02", "M-03")
def test_live_search_select_and_copy_for_outlook_or_gmail(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        context = browser.new_context()
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        # Capture compose URLs instead of opening Gmail/Outlook.
        page.add_init_script("window.open = (url) => { window.__opened = url; return null; };")

        types = {
            t["name"]: t["id"] for t in page.request.get(f"{base_url}/api/contact-types").json()
        }
        _make(
            page,
            base_url,
            {
                "display_name": "Quinn Copyton",
                "contact_type_id": types["Employee"],
                "emails": [{"email": "quinn@acme.example"}],
                "team": "Copy Team",
            },
        )
        _make(
            page,
            base_url,
            {
                "display_name": "Rhea Copyton",
                "contact_type_id": types["Employee"],
                "emails": [{"email": "rhea@acme.example"}],
                "team": "Copy Team",
            },
        )
        _make(
            page,
            base_url,
            {
                "display_name": "Sol Nomail",
                "contact_type_id": types["Vendor"],
                "works_on": "Copy machines",
            },
        )

        page.goto(base_url)
        search = page.get_by_test_id("search-input")

        # S-05: results update as you type, no Enter needed.
        search.press_sequentially("quinn", delay=15)
        expect(page.get_by_test_id("result-row")).to_have_count(1)
        page.get_by_label("Select Quinn Copyton").check()
        expect(page.get_by_test_id("action-bar")).to_be_visible()

        # Selection survives a new search (M-01).
        search.fill("")
        search.press_sequentially("copy", delay=15)
        expect(page.get_by_test_id("result-row")).to_have_count(3)
        expect(page.get_by_label("Select Quinn Copyton")).to_be_checked()
        page.get_by_label("Select Rhea Copyton").check()
        page.get_by_label("Select Sol Nomail").check()
        expect(page.locator("[data-selected-count]")).to_have_text("3 selected")

        # More than one address: choose Outlook or Gmail (ADR-0009).
        page.get_by_test_id("copy-emails").click()
        expect(page.get_by_test_id("copy-menu")).to_be_visible()
        page.get_by_test_id("copy-outlook").click()
        assert (
            page.evaluate("navigator.clipboard.readText()")
            == "quinn@acme.example; rhea@acme.example"
        )
        expect(page.get_by_test_id("action-status")).to_contain_text(
            "Copied 2 addresses for Outlook"
        )
        expect(page.get_by_test_id("action-status")).to_contain_text(
            "1 skipped (no email): Sol Nomail"
        )

        page.get_by_test_id("copy-emails").click()
        expect(page.get_by_test_id("copy-outlook")).to_have_class(re.compile("preferred"))
        page.get_by_test_id("copy-gmail").click()
        assert (
            page.evaluate("navigator.clipboard.readText()")
            == "quinn@acme.example, rhea@acme.example"
        )

        # Compose in Gmail with Cc (M-03).
        page.get_by_test_id("compose").click()
        page.get_by_label("Cc").check()
        page.get_by_test_id("compose-gmail").click()
        assert page.evaluate("window.__opened") == (
            "https://mail.google.com/mail/?view=cm&fs=1&cc=quinn%40acme.example,rhea%40acme.example"
        )
        page.get_by_test_id("compose").click()
        page.get_by_label("To", exact=True).check()
        page.get_by_test_id("compose-outlook").click()
        assert page.evaluate("window.__opened") == (
            "https://outlook.office.com/mail/deeplink/compose?to=quinn%40acme.example;rhea%40acme.example"
        )

        # Tag the selection from the action bar (T-01 bulk).
        page.get_by_test_id("add-tag").click()
        page.get_by_test_id("tag-input").fill("Copy club")
        page.get_by_test_id("tag-submit").click()
        expect(page.get_by_test_id("flash")).to_contain_text("Tagged 3 contact(s)")

        assert errors == []
        browser.close()


@pytest.mark.req("C-14")
def test_company_defaults_for_employees_and_can_be_added(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        types = {
            t["name"]: t["id"] for t in page.request.get(f"{base_url}/api/contact-types").json()
        }
        for name in ("Home One", "Home Two"):
            _make(
                page,
                base_url,
                {
                    "display_name": name,
                    "contact_type_id": types["Employee"],
                    "company": "Homebase Inc",
                },
            )

        page.goto(f"{base_url}/contacts/new")
        company = page.get_by_test_id("company-select")
        page.get_by_test_id("type-select").select_option(label="Employee")
        expect(company).to_have_value("Homebase Inc")
        expect(page.get_by_test_id("company-new")).to_be_hidden()

        # Switching to Vendor clears the default; back to Employee restores it.
        page.get_by_test_id("type-select").select_option(label="Vendor")
        expect(company).to_have_value("")
        page.get_by_test_id("type-select").select_option(label="Employee")
        expect(company).to_have_value("Homebase Inc")

        # Add a new company.
        page.get_by_label("Display name").fill("Newco Person")
        page.get_by_test_id("type-select").select_option(label="Vendor")
        company.select_option(value="__new__")
        expect(page.get_by_test_id("company-new")).to_be_visible()
        page.get_by_test_id("company-new").fill("Brand New Co")
        page.get_by_test_id("save").click()
        expect(page.get_by_test_id("contact-card")).to_contain_text("Brand New Co")
        browser.close()


@pytest.mark.req("M-05", "S-06", "C-09")
def test_teams_group_chat_org_chart_and_photo(base_url: str, tmp_path: object) -> None:
    import io
    from pathlib import Path

    from PIL import Image
    from playwright.sync_api import expect, sync_playwright

    photo = Path(str(tmp_path)) / "face.png"
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 140, 90)).save(buffer, "PNG")
    photo.write_bytes(buffer.getvalue())

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.add_init_script("window.open = (url) => { window.__opened = url; return null; };")
        types = {
            t["name"]: t["id"] for t in page.request.get(f"{base_url}/api/contact-types").json()
        }
        boss = _make(
            page,
            base_url,
            {
                "display_name": "Teamsy Boss",
                "contact_type_id": types["Employee"],
                "emails": [{"email": "boss@teams.example"}],
            },
        )
        _make(
            page,
            base_url,
            {
                "display_name": "Teamsy Report",
                "contact_type_id": types["Employee"],
                "manager_id": boss["id"],
                "emails": [{"email": "report@teams.example"}],
            },
        )

        # M-05: Teams group chat with the selection.
        page.goto(f"{base_url}/?q=teamsy")
        expect(page.get_by_test_id("result-row")).to_have_count(2)
        page.get_by_test_id("select-all").check()
        page.get_by_test_id("compose").click()
        page.get_by_test_id("compose-teams").click()
        assert page.evaluate("window.__opened") == (
            "https://teams.microsoft.com/l/chat/0/0?users=boss%40teams.example,report%40teams.example"
        )

        # S-06: org chart from the card.
        page.goto(f"{base_url}/contacts/{boss['id']}")
        page.get_by_test_id("org-link").click()
        expect(page.get_by_test_id("org-tree")).to_contain_text("Teamsy Report")

        # C-09: upload a photo on the card.
        page.goto(f"{base_url}/contacts/{boss['id']}")
        page.get_by_test_id("photo-input").set_input_files(str(photo))
        page.get_by_test_id("photo-upload").click()
        expect(page.get_by_test_id("flash")).to_have_text("Photo saved.")
        expect(page.get_by_test_id("photo")).to_be_visible()
        assert page.evaluate("document.querySelector('[data-testid=photo]').naturalWidth") == 512

        assert errors == []
        browser.close()


@pytest.mark.req("C-11", "C-13", "S-07")
def test_custom_fields_activity_and_saved_search(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # C-11: "+ Add field" adds a row; both rows save.
        page.goto(f"{base_url}/contacts/new")
        page.fill("#display_name", "Fieldy Person")
        rows = page.get_by_test_id("custom-fields").locator(".row-item")
        rows.nth(0).locator("input[name=field_name]").fill("Epic role")
        rows.nth(0).locator("input[name=field_value]").fill("Beaker analyst")
        page.get_by_role("button", name="+ Add field").click()
        expect(rows).to_have_count(2)
        expect(rows.nth(1).locator("input[name=field_name]")).to_be_focused()
        rows.nth(1).locator("input[name=field_name]").fill("Birthday")
        rows.nth(1).locator("input[name=field_value]").fill("June 9")
        page.get_by_test_id("save").click()
        expect(page.get_by_test_id("custom-field-list")).to_contain_text("Beaker analyst")
        expect(page.get_by_test_id("custom-field-list")).to_contain_text("June 9")

        # C-13: log an activity from the card.
        page.get_by_test_id("activity-kind").select_option("call")
        page.get_by_test_id("activity-summary").fill("Asked about the courier schedule")
        page.get_by_test_id("activity-add").click()
        expect(page.get_by_test_id("flash")).to_have_text("Activity logged.")
        expect(page.get_by_test_id("activity")).to_contain_text("courier schedule")
        expect(page.get_by_test_id("last-contact")).to_be_visible()

        # S-07: live search, save it, and it shows as a chip.
        page.goto(base_url)
        page.get_by_test_id("search-input").fill("courier")
        expect(page.get_by_test_id("result-row")).to_have_count(1)
        page.locator("summary", has_text="Save this search").click()
        page.get_by_test_id("save-search-name").fill("Courier folks")
        page.get_by_test_id("save-search-name").press("Enter")
        expect(page.get_by_test_id("saved-search")).to_have_text("Courier folks")
        expect(page.get_by_test_id("result-row")).to_have_count(1)

        assert errors == []
        browser.close()


@pytest.fixture(scope="module")
def meaning_url(settings: Settings) -> Iterator[str]:
    """A server with search by meaning on (hashing stand-in model, background indexing)."""
    from tests.fake_embedder import HashingEmbedder

    port = _free_port()
    app = create_app(settings, embedder=HashingEmbedder())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
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


@pytest.mark.req("S-08", "S-05", "M-01")
def test_live_search_by_meaning_and_select(meaning_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        types = {
            t["name"]: t["id"] for t in page.request.get(f"{meaning_url}/api/contact-types").json()
        }
        _make(page, meaning_url, {
            "display_name": "Regina Clearance", "contact_type_id": types["Employee"],
            "emails": [{"email": "regina@acme.example"}],
            "notes": "Steered the zebrafish device submission through the agency review"})  # fmt: skip

        # The background task embeds the new contact within moments.
        page.goto(meaning_url)
        search = page.get_by_test_id("search-input")
        rows = page.get_by_test_id("meaning-row")
        deadline = time.monotonic() + 10
        while rows.count() == 0 and time.monotonic() < deadline:
            search.fill("")
            search.fill("who steered our zebrafish device submission")
            page.wait_for_timeout(300)
        expect(rows).to_have_count(1)
        expect(page.get_by_test_id("meaning-results")).to_contain_text("Best matches by meaning")
        expect(page.get_by_test_id("meaning-why")).to_contain_text("zebrafish device submission")

        # Meaning rows can be selected like any other result.
        rows.first.locator(".select-contact").check()
        expect(page.get_by_test_id("action-bar")).to_contain_text("1 selected")

        assert errors == []
        browser.close()


@pytest.mark.req("A-01", "A-03")
def test_theme_follows_the_system_until_chosen_and_is_right_on_first_paint(base_url: str) -> None:
    """System follows the OS; a choice applies at once, persists, and needs no script."""
    from playwright.sync_api import expect, sync_playwright

    dark_bg, light_bg = "rgb(13, 19, 26)", "rgb(244, 246, 249)"  # Harbor --bg
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page(color_scheme="dark")
        page.goto(base_url)
        body = page.locator("body")
        expect(page.locator("html")).to_have_attribute("data-theme", "system")
        expect(body).to_have_css("background-color", dark_bg)

        with page.expect_response(lambda r: r.url.endswith("/settings/appearance")) as saved:
            page.get_by_test_id("theme-light").check()
        assert saved.value.ok
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        expect(body).to_have_css("background-color", light_bg)

        page.reload()
        expect(body).to_have_css("background-color", light_bg)
        expect(page.get_by_test_id("theme-light")).to_be_checked()

        # Without JavaScript the server-rendered attribute still wins over the OS (no flash).
        no_js = browser.new_context(java_script_enabled=False, color_scheme="dark").new_page()
        no_js.goto(base_url)
        expect(no_js.locator("body")).to_have_css("background-color", light_bg)

        # Leave the shared database as other browser tests expect it.
        with page.expect_response(lambda r: r.url.endswith("/settings/appearance")):
            page.get_by_test_id("theme-system").check()
        expect(body).to_have_css("background-color", dark_bg)
        browser.close()


@pytest.mark.req("A-02", "A-05")
def test_palette_and_density_are_chosen_in_settings(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page(color_scheme="light")
        page.goto(base_url + "/settings")
        page.get_by_test_id("settings-palette-clay").check()
        page.get_by_test_id("settings-density-compact").check()
        page.get_by_test_id("appearance-save").click()
        expect(page.get_by_test_id("flash")).to_contain_text("Appearance saved")
        html = page.locator("html")
        expect(html).to_have_attribute("data-palette", "clay")
        expect(html).to_have_attribute("data-density", "compact")
        expect(page.locator("body")).to_have_css("background-color", "rgb(249, 246, 242)")
        # The Sage preview shows Sage's own colors inside a Clay page.
        sage_light = page.locator('.palette-preview[data-palette="sage"] .preview-light')
        expect(sage_light).to_have_css("background-color", "rgb(244, 247, 243)")
        sage_dark = page.locator('.palette-preview[data-palette="sage"] .preview-dark')
        expect(sage_dark).to_have_css("background-color", "rgb(14, 20, 17)")

        # Leave the shared database as other browser tests expect it.
        page.get_by_test_id("settings-palette-harbor").check()
        page.get_by_test_id("settings-density-comfortable").check()
        page.get_by_test_id("appearance-save").click()
        expect(html).to_have_attribute("data-palette", "harbor")
        browser.close()


@pytest.mark.req("A-06")
def test_increased_contrast_and_reduced_motion_follow_the_system(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    def transition(page: Any) -> str:
        return str(page.evaluate("getComputedStyle(document.body).transitionDuration"))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        normal = browser.new_page(color_scheme="light")
        normal.goto(base_url + "/settings")
        expect(normal.locator(".panel").first).to_have_css("border-top-color", "rgb(211, 219, 228)")
        assert transition(normal) == "0s"

        more = browser.new_page(color_scheme="light", contrast="more", reduced_motion="reduce")
        more.goto(base_url + "/settings")
        # Hairlines take the field-border strength; muted text becomes full-strength text.
        expect(more.locator(".panel").first).to_have_css("border-top-color", "rgb(125, 139, 155)")
        expect(more.locator("p.muted").first).to_have_css("color", "rgb(20, 28, 38)")
        assert transition(more) != "0s"  # the reduced-motion rule is in force
        browser.close()


@pytest.mark.req("S-11", "C-15", "C-17")
def test_reconnect_count_page_and_log_prompt(base_url: str) -> None:
    from datetime import date, timedelta

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        page = browser.new_page()
        types = page.request.get(base_url + "/api/contact-types").json()
        employee = next(t["id"] for t in types if t["name"] == "Employee")
        rhea = page.request.post(
            base_url + "/api/contacts",
            data={
                "display_name": "Rhea Reconnect",
                "contact_type_id": employee,
                "emails": [{"email": "rhea@example.com", "label": "work", "is_primary": True}],
            },
        ).json()

        # Every 2 weeks, last call 30 days ago -> overdue.
        page.goto(base_url + f"/contacts/{rhea['id']}")
        page.get_by_test_id("kit-interval").select_option("2w")
        page.get_by_test_id("kit-save").click()
        page.locator("#act-kind").select_option("call")
        page.locator("#act-date").fill((date.today() - timedelta(days=30)).isoformat())
        page.locator("#act-summary").fill("Quarterly check-in")
        page.get_by_test_id("activity-add").click()
        expect(page.get_by_test_id("kit-line")).to_contain_text("Overdue by 16 days")
        expect(page.get_by_test_id("reconnect-count")).to_contain_text("1")

        page.get_by_test_id("nav-reconnect").click()
        row = page.get_by_test_id("reconnect-row").filter(has_text="Rhea Reconnect")
        expect(row).to_contain_text("Overdue by 16 days")

        # Clicking Email offers to log it (the mail app itself is suppressed in the test).
        page.evaluate(
            "window.addEventListener('click', e => {"
            " if (e.target.closest('a[href^=\"mailto:\"]')) e.preventDefault(); }, true)"
        )
        row.get_by_role("link", name="Email").click()
        prompt = page.get_by_test_id("log-prompt")
        expect(prompt).to_be_visible()
        expect(prompt).to_contain_text("Log an email with Rhea Reconnect today?")
        page.get_by_test_id("log-prompt-yes").click()
        expect(page.get_by_test_id("flash")).to_contain_text("Logged")
        expect(
            page.get_by_test_id("reconnect-row").filter(has_text="Rhea Reconnect")
        ).to_have_count(0)
        expect(page.get_by_test_id("reconnect-count")).to_have_count(0)
        browser.close()


@pytest.mark.req("P-01", "P-02", "P-06")
def test_shift_p_presents_and_hides_private_details(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        context = browser.new_context()
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
        page = context.new_page()
        types = page.request.get(base_url + "/api/contact-types").json()
        employee = next(t["id"] for t in types if t["name"] == "Employee")
        for name, emails in (
            ("Pia Presenter", [{"email": "pia@work.example", "label": "work"}]),
            ("Pete Personal", [{"email": "pete@home.example", "label": "personal"}]),
        ):
            page.request.post(
                base_url + "/api/contacts",
                data={
                    "display_name": name,
                    "contact_type_id": employee,
                    "team": "Presenting Team",
                    "notes": "Secret memory cue",
                    "emails": emails,
                },
            )

        page.goto(base_url + "/?team=Presenting+Team")
        expect(page.get_by_test_id("present-toggle")).to_have_attribute("aria-pressed", "false")
        page.get_by_test_id("search-input").press("Shift+P")  # typing: not a shortcut
        expect(page.get_by_test_id("presenting-bar")).to_have_count(0)
        page.locator("h1, body").first.click()
        page.keyboard.press("Shift+P")
        expect(page.get_by_test_id("presenting-bar")).to_be_visible()
        expect(page.get_by_test_id("present-toggle")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("body")).not_to_contain_text("pete@home.example")

        page.get_by_test_id("select-all").check()
        page.get_by_test_id("copy-emails").click()  # one address: copied straight away
        expect(page.get_by_test_id("action-status")).to_contain_text(
            "Copied 1 address · 1 left out (no work address): Pete Personal"
        )
        assert page.evaluate("navigator.clipboard.readText()") == "pia@work.example"

        page.get_by_role("link", name="Pia Presenter").click()  # preview pane first
        expect(page.get_by_test_id("preview")).to_contain_text("pia@work.example")
        page.get_by_role("link", name="Pia Presenter").click()  # then the card
        expect(page.get_by_test_id("hidden-notes")).to_be_visible()
        expect(page.locator("body")).not_to_contain_text("Secret memory cue")

        # The cookie covers every page of every instance in this browser until turned off.
        page.goto(base_url + "/lists")
        expect(page.get_by_test_id("presenting-bar")).to_be_visible()
        page.get_by_test_id("stop-presenting").click()
        expect(page.get_by_test_id("presenting-bar")).to_have_count(0)
        browser.close()


@pytest.mark.req("S-02", "S-04", "N-09", "M-02")
def test_preview_pane_chips_and_keyboard(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        )
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
        page = context.new_page()
        types = page.request.get(base_url + "/api/contact-types").json()
        employee = next(t["id"] for t in types if t["name"] == "Employee")
        for name, email in (
            ("Pax Preview", "pax@acme.example"),
            ("Pim Preview", "pim@acme.example"),
        ):
            page.request.post(
                base_url + "/api/contacts",
                data={
                    "display_name": name,
                    "contact_type_id": employee,
                    "team": "Preview Team",
                    "title": "Analyst",
                    "works_on": "Previewing panes",
                    "emails": [{"email": email}],
                },
            )

        page.goto(base_url + "/")
        pane = page.get_by_test_id("preview-pane")
        expect(pane).to_be_visible()
        expect(pane).to_contain_text("Choose a name to see their details here.")

        # Typing searches live; matched words are highlighted.
        search = page.get_by_test_id("search-input")
        search.press_sequentially("panes", delay=15)
        expect(page.get_by_test_id("result-row")).to_have_count(2)
        expect(page.locator("[data-testid=result-row] mark").first).to_have_text("panes")

        # A click on a name previews instead of navigating; a second click opens the card.
        page.get_by_role("link", name="Pim Preview").click()
        expect(page.get_by_test_id("preview")).to_contain_text("pim@acme.example")
        expect(page).to_have_url(re.compile(r"/\?q=panes$"))
        row = page.get_by_test_id("result-row").filter(has_text="Pim Preview")
        expect(row).to_have_class(re.compile("previewing"))

        # ↓ from the search box and between names previews each person; space selects; c copies.
        search.focus()
        page.keyboard.press("ArrowDown")
        expect(page.get_by_test_id("preview")).to_contain_text("pax@acme.example")
        page.keyboard.press("Space")
        page.keyboard.press("ArrowDown")
        expect(page.get_by_test_id("preview")).to_contain_text("pim@acme.example")
        page.keyboard.press("Space")
        expect(page.locator("[data-selected-count]")).to_have_text("2 selected")
        page.keyboard.press("c")
        expect(page.get_by_test_id("copy-menu")).to_be_visible()

        # Filters are chips; a chosen one is filled and the results follow.
        page.keyboard.press("Escape")
        page.get_by_test_id("filter-team").select_option("Preview Team")
        expect(page.get_by_test_id("filter-chips")).to_contain_text("Team: Preview Team")
        page.get_by_test_id("more-filters").locator("summary").click()
        expect(page.get_by_test_id("filter-contacted")).to_be_visible()
        page.keyboard.press("Escape")  # the popover closes
        expect(page.get_by_test_id("filter-contacted")).to_be_hidden()

        page.get_by_role("link", name="Pim Preview").click()  # already previewed
        expect(page).to_have_url(re.compile(r"/contacts/\d+$"))

        # Narrow screens keep one column: a name opens the card straight away.
        page.set_viewport_size({"width": 700, "height": 900})
        page.goto(base_url + "/?q=panes")
        expect(page.get_by_test_id("preview-pane")).to_be_hidden()
        page.get_by_role("link", name="Pax Preview").click()
        expect(page).to_have_url(re.compile(r"/contacts/\d+$"))
        browser.close()
