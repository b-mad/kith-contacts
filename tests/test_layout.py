"""Layout refresh: preview pane, filter chips, highlighted matches (S-02, S-04, ADR-0015 step 6)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.privacy import COOKIE
from app.search import highlight


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def make(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture
def maria(client: TestClient, types: dict[str, int]) -> dict[str, Any]:
    boss = make(client, display_name="Grace Hopper", contact_type_id=types["Employee"])
    person = make(
        client,
        display_name="Maria Lopez",
        contact_type_id=types["Employee"],
        title="Integration lead",
        team="Data Platform",
        company="Acme Health",
        works_on="Lab results pipeline",
        notes="Two kids, Ana and Leo",
        manager_id=boss["id"],
        emails=[
            {"email": "maria@acme.example", "label": "work", "is_primary": True},
            {"email": "maria@home.example", "label": "personal"},
        ],
        phones=[{"number": "+1 617 555 0101", "label": "work"}],
    )
    for days, summary in ((40, "Kickoff"), (20, "Design review"), (10, "Q4 plan"), (2, "Cutover")):
        _log(client, person["id"], summary, date.today() - timedelta(days=days))
    return person


def _log(client: TestClient, contact_id: int, summary: str, on: date) -> None:
    page = client.get(f"/contacts/{contact_id}").text
    token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    response = client.post(
        f"/contacts/{contact_id}/activities",
        data={
            "csrf_token": token,
            "kind": "call",
            "summary": summary,
            "occurred_on": on.isoformat(),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


# ---------------------------------------------------------------- highlighted matches (S-02)


@pytest.mark.req("S-02")
def test_highlight_marks_words_the_search_terms_start() -> None:
    assert highlight("Lab results pipeline", ["res", "lab"]) == (
        "<mark>Lab</mark> <mark>results</mark> pipeline"
    )
    assert highlight("Data Platform", []) == "Data Platform"


@pytest.mark.req("S-02", "N-05")
def test_highlight_escapes_everything_else() -> None:
    marked = highlight("<b>lab</b> & co", ["lab"])
    assert marked == "&lt;b&gt;<mark>lab</mark>&lt;/b&gt; &amp; co"


@pytest.mark.req("S-02")
def test_results_show_role_line_and_highlighted_context(
    client: TestClient, maria: dict[str, Any]
) -> None:
    html = client.get("/contacts/results", params={"q": "pipeline"}).text
    assert 'data-testid="person-sub">Integration lead · Data Platform · Acme Health<' in html
    assert '<span class="match-field">works on:</span> Lab results <mark>pipeline</mark>' in html
    assert f'href="/contacts/{maria["id"]}" data-preview-link' in html
    assert 'data-email="maria@acme.example"' in html  # Copy emails still reads the row


# ---------------------------------------------------------------- filter chips (S-04)


@pytest.mark.req("S-04")
def test_filters_are_chips_with_less_used_ones_under_more(
    client: TestClient, types: dict[str, int]
) -> None:
    page = client.get("/").text
    assert 'class="filter-chip" aria-label="Company"' in page
    assert '<option value="">Company</option>' in page
    assert 'data-testid="more-filters" data-more-filters>' in page  # a closed popover
    assert '<option value="" selected>Best match</option>' in page
    listed = client.get("/?contacted=30&archived=1").text
    assert "More filters · 2" in listed


@pytest.mark.req("S-04")
def test_sort_control_keeps_an_explicit_sort_only(client: TestClient) -> None:
    by_team = client.get("/?q=lab&sort=team").text
    assert '<option value="team" selected>Team</option>' in by_team
    assert '<option value="" selected>Best match</option>' not in by_team


# ---------------------------------------------------------------- preview pane (S-02)


@pytest.mark.req("S-02", "M-04")
def test_preview_fragment_has_actions_facts_tags_and_recent_activity(
    client: TestClient, maria: dict[str, Any]
) -> None:
    response = client.get(f"/contacts/{maria['id']}/preview")
    assert response.status_code == 200
    html = response.text
    assert "<!doctype" not in html.lower()  # a fragment for the pane
    assert 'data-testid="preview"' in html
    assert "Maria Lopez" in html
    assert 'data-testid="action-email" data-log-kind="email"' in html
    assert 'href="mailto:maria@acme.example"' in html
    assert "+1 more" in html
    assert "Grace Hopper" in html
    assert "Lab results pipeline" in html
    assert html.count('<li><span class="pill kind-') == 3  # the three newest
    assert "Cutover" in html
    assert "Kickoff" not in html
    assert f'href="/contacts/{maria["id"]}" data-testid="preview-open"' in html
    assert 'title="No Slack handle saved"' in html  # a missing channel says why
    assert "data-contact-id" not in html  # never counted as a selectable row


@pytest.mark.req("S-02")
def test_preview_of_unknown_contact_is_404(client: TestClient) -> None:
    assert client.get("/contacts/999999/preview").status_code == 404


@pytest.mark.req("S-02", "P-02")
def test_preview_while_presenting_uses_the_presentable_view(
    client: TestClient, maria: dict[str, Any]
) -> None:
    client.cookies.set(COOKIE, "1")
    html = client.get(f"/contacts/{maria['id']}/preview").text
    assert "maria@home.example" not in html
    assert "+1 more" not in html
    assert "Cutover" not in html
    assert "details hidden while presenting" in html
    assert "1 personal address or number hidden while presenting" in html


@pytest.mark.req("S-02")
def test_search_page_has_an_empty_preview_pane(client: TestClient) -> None:
    page = client.get("/").text
    assert 'data-preview-pane hidden data-testid="preview-pane"' in page
    assert "Choose a name to see their details here." in page
