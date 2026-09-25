"""Browser smoke test (run with `make e2e`). Starts a real server and opens it in Chromium."""

from __future__ import annotations

import os
import re
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
