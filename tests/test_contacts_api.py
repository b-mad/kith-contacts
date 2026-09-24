"""Contacts JSON API (C-01 to C-08, M-04)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def types(client: TestClient) -> dict[str, int]:
    return {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}


def create(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/contacts", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.mark.req("C-01", "C-05")
def test_create_vendor_with_no_email_or_phone(client: TestClient, types: dict[str, int]) -> None:
    body = create(client, display_name="Acme sales rep", contact_type_id=types["Vendor"])

    assert body["contact_type"]["name"] == "Vendor"
    assert body["emails"] == []
    assert body["phones"] == []
    assert body["links"] == {"mailto": None, "teams": None, "slack": None, "tel": None}
    assert body["archived"] is False


@pytest.mark.req("C-01")
def test_read_contact(client: TestClient, types: dict[str, int]) -> None:
    created = create(client, display_name="Pat", contact_type_id=types["Customer"])
    response = client.get(f"/api/contacts/{created['id']}")
    assert response.status_code == 200
    assert response.json()["display_name"] == "Pat"


@pytest.mark.req("C-01")
def test_unknown_contact_is_404(client: TestClient) -> None:
    assert client.get("/api/contacts/999999").status_code == 404
    assert client.patch("/api/contacts/999999", json={"team": "x"}).status_code == 404


@pytest.mark.req("C-02", "C-03", "C-06", "C-08", "M-04")
def test_create_employee_with_full_details(client: TestClient, types: dict[str, int]) -> None:
    body = create(
        client,
        display_name="Dev Patel",
        contact_type_id=types["Employee"],
        company="Acme Health",
        title="Data Engineer",
        team="Data Platform",
        department="Engineering",
        location="Atlanta",
        works_on="Lab results pipeline",
        notes="Met at the HL7 working session",
        emails=[
            {"email": "dev@acme.example", "label": "work"},
            {"email": "dev@home.example", "label": "personal"},
        ],
        phones=[{"number": "(404) 555-0123", "label": "mobile"}],
        slack_handle="@dev",
        slack_url="https://acme.slack.com/team/U123",
    )

    assert [(e["email"], e["is_primary"]) for e in body["emails"]] == [
        ("dev@acme.example", True),
        ("dev@home.example", False),
    ]
    assert body["phones"] == [{"number": "+14045550123", "label": "mobile"}]
    assert (body["team"], body["department"], body["location"]) == (
        "Data Platform",
        "Engineering",
        "Atlanta",
    )
    assert body["works_on"] == "Lab results pipeline"
    assert body["slack_handle"] == "dev"
    assert body["links"] == {
        "mailto": "mailto:dev@acme.example",
        "teams": "https://teams.microsoft.com/l/chat/0/0?users=dev@acme.example",
        "slack": "https://acme.slack.com/team/U123",
        "tel": "tel:+14045550123",
    }


@pytest.mark.req("C-07")
def test_manager_card_lists_direct_reports(client: TestClient, types: dict[str, int]) -> None:
    maria = create(client, display_name="Maria Lopez", contact_type_id=types["Employee"])
    dev = create(
        client, display_name="Dev Patel", contact_type_id=types["Employee"], manager_id=maria["id"]
    )

    assert dev["manager"]["display_name"] == "Maria Lopez"
    reports = client.get(f"/api/contacts/{maria['id']}").json()["reports"]
    assert [r["display_name"] for r in reports] == ["Dev Patel"]


@pytest.mark.req("C-07")
def test_manager_cycles_are_rejected(client: TestClient, types: dict[str, int]) -> None:
    emp = types["Employee"]
    ceo = create(client, display_name="CEO", contact_type_id=emp)
    vp = create(client, display_name="VP", contact_type_id=emp, manager_id=ceo["id"])
    lead = create(client, display_name="Lead", contact_type_id=emp, manager_id=vp["id"])

    self_ref = client.patch(f"/api/contacts/{ceo['id']}", json={"manager_id": ceo["id"]})
    indirect = client.patch(f"/api/contacts/{ceo['id']}", json={"manager_id": lead["id"]})

    assert self_ref.status_code == 422
    assert indirect.status_code == 422
    assert indirect.json()["detail"][0]["loc"] == ["body", "manager_id"]
    assert "cycle" in indirect.json()["detail"][0]["msg"]


@pytest.mark.req("C-07")
def test_unknown_manager_rejected(client: TestClient, types: dict[str, int]) -> None:
    response = client.post(
        "/api/contacts",
        json={"display_name": "X", "contact_type_id": types["Employee"], "manager_id": 999999},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Manager not found"


def test_unknown_contact_type_rejected(client: TestClient) -> None:
    response = client.post("/api/contacts", json={"display_name": "X", "contact_type_id": 999999})
    assert response.status_code == 422


@pytest.mark.req("C-02")
def test_patch_replaces_emails_and_moves_primary(client: TestClient, types: dict[str, int]) -> None:
    contact = create(
        client,
        display_name="Sam",
        contact_type_id=types["Customer"],
        emails=[{"email": "sam@work.example"}, {"email": "sam@home.example"}],
    )

    response = client.patch(
        f"/api/contacts/{contact['id']}",
        json={
            "emails": [
                {"email": "SAM@home.example", "is_primary": True, "label": "personal"},
                {"email": "sam@new.example"},
            ]
        },
    )

    assert response.status_code == 200, response.text
    assert [(e["email"], e["is_primary"], e["label"]) for e in response.json()["emails"]] == [
        ("SAM@home.example", True, "personal"),
        ("sam@new.example", False, None),
    ]


def test_patch_changes_only_sent_fields(client: TestClient, types: dict[str, int]) -> None:
    contact = create(
        client,
        display_name="Sam",
        contact_type_id=types["Customer"],
        company="Peachtree Labs",
        phones=[{"number": "404-555-0100"}],
    )
    response = client.patch(
        f"/api/contacts/{contact['id']}",
        json={"team": "Lab Ops", "contact_type_id": types["Vendor"]},
    )
    body = response.json()
    assert (body["company"], body["team"], body["contact_type"]["name"]) == (
        "Peachtree Labs",
        "Lab Ops",
        "Vendor",
    )
    assert len(body["phones"]) == 1


@pytest.mark.req("C-01")
def test_archive_and_restore(client: TestClient, types: dict[str, int]) -> None:
    contact = create(client, display_name="Leaving Soon", contact_type_id=types["Vendor"])

    archived = client.delete(f"/api/contacts/{contact['id']}")
    listed = [c["display_name"] for c in client.get("/api/contacts").json()]
    listed_all = [
        c["display_name"] for c in client.get("/api/contacts?include_archived=true").json()
    ]
    restored = client.post(f"/api/contacts/{contact['id']}/restore", json={})

    assert archived.json()["archived"] is True
    assert "Leaving Soon" not in listed
    assert "Leaving Soon" in listed_all
    assert restored.json()["archived"] is False


@pytest.mark.req("C-05")
def test_list_filters_by_type_and_sorts(client: TestClient, types: dict[str, int]) -> None:
    create(client, display_name="Zed", contact_type_id=types["Vendor"], company="Acme")
    create(client, display_name="amy", contact_type_id=types["Vendor"], company="Zeta")
    create(client, display_name="Bob", contact_type_id=types["Customer"])

    vendors = client.get(f"/api/contacts?type={types['Vendor']}").json()
    by_company = client.get(f"/api/contacts?type={types['Vendor']}&sort=company").json()

    assert [c["display_name"] for c in vendors] == ["amy", "Zed"]  # case-insensitive
    assert [c["display_name"] for c in by_company] == ["Zed", "amy"]


def test_invalid_sort_rejected(client: TestClient) -> None:
    assert client.get("/api/contacts?sort=salary").status_code == 422


@pytest.mark.req("C-07")
def test_lookup_for_manager_picker(client: TestClient, types: dict[str, int]) -> None:
    maria = create(client, display_name="Maria Lopez", contact_type_id=types["Employee"])
    create(client, display_name="Omar Marino", contact_type_id=types["Employee"], team="Data")
    create(client, display_name="Ann", contact_type_id=types["Employee"], company="Mariachi Co")

    names = [c["display_name"] for c in client.get("/api/contacts/lookup?q=mar").json()]
    excluded = client.get(f"/api/contacts/lookup?q=maria&exclude={maria['id']}").json()

    assert names[0] == "Maria Lopez"  # name starting with the query ranks first
    assert set(names) == {"Maria Lopez", "Omar Marino", "Ann"}
    assert [c["display_name"] for c in excluded] == ["Ann"]
    assert client.get("/api/contacts/lookup?q=%20").json() == []
    assert client.get("/api/contacts/lookup?q=100%25").json() == []  # % is literal


def test_writes_require_json_content_type(client: TestClient, types: dict[str, int]) -> None:
    """CSRF defence for the API: a cross-site HTML form cannot send application/json."""
    response = client.post(
        "/api/contacts",
        content=f"display_name=X&contact_type_id={types['Vendor']}",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415
