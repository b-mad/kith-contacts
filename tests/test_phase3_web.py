"""Phase 3 pages: settings/backups, export, import, org chart, tag & type admin, photos."""

from __future__ import annotations

import io
import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app import main as main_module
from app.config import Settings
from app.main import BackupStatus, create_app, initials
from app.migrate import upgrade_to_head
from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
from scripts.seed import seed
from tests.conftest import make_settings

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf(client: TestClient) -> str:
    match = TOKEN.search(client.get("/contacts/new").text)
    assert match
    return match.group(1)


def post(client: TestClient, url: str, files: Any = None, **fields: Any) -> Any:
    return client.post(
        url, data={"csrf_token": csrf(client), **fields}, files=files, follow_redirects=False
    )


@pytest.fixture
def seeded_client(client: TestClient, db_session: Session) -> TestClient:
    seed(db_session)
    return client


def contact_id(client: TestClient, name: str) -> int:
    hits = client.get("/api/search", params={"q": name}).json()
    return int(next(h["contact"]["id"] for h in hits if h["contact"]["display_name"] == name))


# ---------------------------------------------------------------- settings & backups through the UI


@pytest.fixture
def live_instance(admin_url: str, tmp_path: Path) -> Iterator[tuple[Settings, TestClient]]:
    """A real instance (own database + role) served by the app, like on the Mac."""
    spec = InstanceSpec(name=f"tw-{uuid.uuid4().hex[:6]}", port=5196, app_env="test")
    info = bootstrap(spec, admin_url, None)
    settings = make_settings(
        info.database_url, instance_name="Web Test", backup_dir=str(tmp_path / "b")
    )
    upgrade_to_head(settings)
    with TestClient(create_app(settings)) as client:
        yield settings, client
    drop_database(spec, admin_url)


@pytest.mark.req("D-04", "I-06")
def test_backup_now_and_restore_from_settings(live_instance: tuple[Settings, TestClient]) -> None:
    _settings, client = live_instance
    types = {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}
    client.post(
        "/api/contacts", json={"display_name": "Keep Me", "contact_type_id": types["Employee"]}
    )

    made = post(client, "/settings/backups")
    name = re.search(r"name=([^&]+)", made.headers["location"]).group(1)  # type: ignore[union-attr]
    page = client.get("/settings").text
    assert 'data-testid="backup-row"' in page
    assert name in page
    assert client.get(f"/settings/backups/{name}").content[:5] == b"PGDMP"  # download works
    assert client.get("/settings/backups/../../etc/passwd").status_code == 404

    client.post(
        "/api/contacts", json={"display_name": "Added Later", "contact_type_id": types["Vendor"]}
    )
    wrong = post(client, f"/settings/backups/{name}/restore", confirm="nope")
    assert "error=" in wrong.headers["location"]
    done = post(client, f"/settings/backups/{name}/restore", confirm="Web Test")

    assert "notice=restored" in done.headers["location"]
    names = [c["display_name"] for c in client.get("/api/contacts").json()]
    assert names == ["Keep Me"]
    assert "before-restore" in client.get("/settings").text  # safety copy listed


def test_backup_failure_is_shown(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import web_admin
    from app.backup import BackupError

    def fail(settings: Settings) -> None:
        raise BackupError("docker is not running")

    monkeypatch.setattr(web_admin, "backup", fail)
    response = post(client, "/settings/backups")
    assert "docker+is+not+running" in response.headers["location"]
    assert "docker is not running" in client.get(response.headers["location"]).text


@pytest.mark.req("I-06")
def test_auto_backup_runs_at_startup_when_enabled(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Settings] = []

    def fake(s: Settings) -> None:
        calls.append(s)

    monkeypatch.setattr(main_module, "ensure_recent_backup", fake)
    enabled = settings.model_copy(update={"auto_backup": True})
    with TestClient(create_app(enabled, run_migrations=False)) as client:
        client.get("/healthz")
        status: BackupStatus = client.app.state.backup_status  # type: ignore[attr-defined]
    assert calls == [enabled]
    assert status.enabled
    assert status.last_check is not None


def test_auto_backup_errors_do_not_stop_the_app(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(s: Settings) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(main_module, "ensure_recent_backup", boom)
    with TestClient(
        create_app(settings.model_copy(update={"auto_backup": True}), run_migrations=False)
    ) as client:
        assert client.get("/healthz").status_code == 200
        assert client.app.state.backup_status.last_error == "disk full"  # type: ignore[attr-defined]


def test_auto_backup_defaults_to_production_only() -> None:
    assert make_settings("postgresql://u:p@x/db", app_env="production").auto_backup_enabled
    assert not make_settings("postgresql://u:p@x/db", app_env="development").auto_backup_enabled


# ---------------------------------------------------------------- export (D-02, D-03)


@pytest.mark.req("D-03", "D-02")
def test_export_downloads(seeded_client: TestClient) -> None:
    csv_response = seeded_client.get("/export/contacts.csv")
    json_response = seeded_client.get("/export/contacts.json")
    vcf_response = seeded_client.get("/export/contacts.vcf")

    assert csv_response.headers["content-disposition"].startswith(
        'attachment; filename="test-contacts-'
    )
    assert csv_response.text.startswith("﻿display_name,")  # BOM so Excel reads UTF-8
    assert len(json.loads(json_response.text)["contacts"]) == 50
    assert vcf_response.text.count("BEGIN:VCARD") == 50

    one = seeded_client.get(f"/contacts/{contact_id(seeded_client, 'Dev Patel')}/vcard")
    assert 'filename="Dev-Patel.vcf"' in one.headers["content-disposition"]
    assert "FN:Dev Patel" in one.text


# ---------------------------------------------------------------- import (D-01, D-02)

CSV = (
    "Full Name,Work Email,Employer,Job Title,Reports To,Labels\n"
    "Nia Import,nia@new.example,Globex,PM,,Launch\n"
    "Ola Import,ola@new.example,Globex,Engineer,Nia Import,Launch;Backend\n"
    "Maria Again,maria.lopez@acmehealth.example,Acme Health,,,\n"
)


@pytest.mark.req("D-01")
def test_import_csv_preview_then_run(seeded_client: TestClient) -> None:
    preview = post(
        seeded_client,
        "/import/preview",
        files={"file": ("people.csv", CSV.encode(), "text/csv")},
        list_name="Globex launch",
    )
    html = preview.text

    assert preview.status_code == 200
    assert "<strong>2</strong> ready to import" in html
    assert "<strong>1</strong> possible duplicate" in html
    assert '<option value="email" selected>Email</option>' in html  # "Work Email" recognised
    assert '<option value="manager" selected>Manager (name)</option>' in html
    assert html.count('data-testid="import-row"') == 3

    # remap "Job Title" to Team and re-preview using the carried-over data
    raw = re.search(r'<textarea name="raw" hidden>(.*?)</textarea>', html, re.S).group(1)  # type: ignore[union-attr]
    import html as html_lib

    raw = html_lib.unescape(raw)
    fields = {"kind": "csv", "raw": raw, "map_0": "display_name", "map_1": "email", "map_2": "company",
              "map_3": "team", "map_4": "manager", "map_5": "tags", "list_name": "Globex launch"}  # fmt: skip
    updated = post(seeded_client, "/import/preview", **fields)
    assert '<option value="team" selected>Team</option>' in updated.text

    done = post(seeded_client, "/import/run", **fields)
    assert re.match(r"^/lists/\d+\?notice=imported&n=2", done.headers["location"])
    ola = next(
        h["contact"]
        for h in seeded_client.get("/api/search", params={"q": "ola import"}).json()
        if h["contact"]["display_name"] == "Ola Import"
    )
    assert ola["team"] == "Engineer"
    assert ola["manager"]["display_name"] == "Nia Import"
    assert sorted(t["name"] for t in ola["tags"]) == ["Backend", "Launch"]


@pytest.mark.req("D-06")
def test_import_pages_link_to_the_mapping_help(seeded_client: TestClient) -> None:
    upload = seeded_client.get("/import").text
    preview = post(
        seeded_client, "/import/preview", files={"file": ("people.csv", CSV.encode(), "text/csv")}
    ).text
    page = seeded_client.get("/import/help")

    assert 'href="/import/help" data-testid="import-help-link"' in upload
    assert 'class="help-icon" href="/import/help#mapping" target="_blank"' in preview
    assert preview.count('class="mapping-arrow"') == preview.count('class="mapping-row"')
    assert page.status_code == 200
    assert 'id="mapping"' in page.text
    assert (
        '<td><span class="mapping-header">Organization Name</span></td><td>Company</td>'
        in page.text
    )
    assert "Birthday" in page.text  # listed under the columns that are left out
    assert page.text.count("<tr><td>") >= 23  # one row per field, plus the Google table


@pytest.mark.req("D-02")
def test_import_vcard_file(seeded_client: TestClient) -> None:
    vcf = b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Vera Card\r\nORG:Initech\r\nEMAIL:vera@initech.example\r\nEND:VCARD\r\n"
    preview = post(seeded_client, "/import/preview", files={"file": ("x.vcf", vcf, "text/vcard")})
    assert "Vera Card" in preview.text
    assert "Column mapping" not in preview.text
    done = post(seeded_client, "/import/run", kind="vcard", raw=vcf.decode())
    assert done.headers["location"].startswith("/?sort=updated&notice=imported&n=1")


def test_import_errors(client: TestClient) -> None:
    assert "Choose a CSV, vCard or JSON file" in post(client, "/import/preview").text
    empty = post(client, "/import/preview", files={"file": ("x.csv", b"\n", "text/csv")})
    assert empty.status_code == 422
    assert "no rows" in empty.text
    assert client.get("/import").status_code == 200


# ---------------------------------------------------------------- org chart (S-06)


@pytest.mark.req("S-06")
def test_org_page(seeded_client: TestClient) -> None:
    whole = seeded_client.get("/org").text
    maria_id = contact_id(seeded_client, "Maria Lopez")
    focused = seeded_client.get(f"/org?root={maria_id}").text
    card = seeded_client.get(f"/contacts/{maria_id}").text

    assert 'data-testid="org-tree"' in whole
    assert "Priya Raman" in whole
    assert 'data-testid="org-chain"' in focused
    assert "Dev Patel" in focused
    assert "Paul Bennett" not in focused
    assert f'href="/org?root={maria_id}" data-testid="org-link"' in card


# ---------------------------------------------------------------- tags & types admin (T-04, I-08)


@pytest.mark.req("T-04")
def test_tag_admin_pages(seeded_client: TestClient) -> None:
    dev = contact_id(seeded_client, "Dev Patel")
    post(seeded_client, "/selection/tag", contact_ids=[dev], tag="Old name")
    tag_id = seeded_client.get("/api/tags").json()[0]["id"]

    post(seeded_client, f"/tags/{tag_id}/edit", name="New name", color="blue")
    page = seeded_client.get("/tags").text
    assert "tag tag-c-blue" in page
    assert "New name" in page
    assert post(seeded_client, f"/tags/{tag_id}/edit", name="x", color="#bad").status_code == 422
    post(seeded_client, f"/tags/{tag_id}/delete")
    assert seeded_client.get("/api/tags").json() == []
    assert post(seeded_client, "/tags/999999/delete").status_code == 404


@pytest.mark.req("I-08")
def test_contact_types_page(client: TestClient) -> None:
    post(client, "/settings/types", name="Family")
    types = {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}
    post(client, f"/settings/types/{types['Family']}/rename", name="Relatives")
    post(client, f"/settings/types/{types['Family']}/move", direction="up")
    client.post("/api/contacts", json={"display_name": "Aunt", "contact_type_id": types["Vendor"]})
    blocked = post(client, f"/settings/types/{types['Vendor']}/delete")
    post(client, f"/settings/types/{types['Vendor']}/delete", move_to=str(types["Family"]))

    names = [t["name"] for t in client.get("/api/contact-types").json()]
    assert blocked.status_code == 422
    assert "choose a type to move them to" in blocked.text
    assert names == ["Employee", "Customer", "Relatives"] or names.index("Relatives") < 3
    assert "Vendor" not in names
    assert post(client, "/settings/types", name="relatives").status_code == 422
    assert post(client, "/settings/types/999999/rename", name="x").status_code == 404
    assert post(client, "/settings/types/999999/move", direction="up").status_code == 404
    assert post(client, "/settings/types/999999/delete").status_code == 404


# ---------------------------------------------------------------- photos (C-09)


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (800, 800), (10, 120, 200)).save(out, "PNG")
    return out.getvalue()


@pytest.mark.req("C-09")
def test_photo_upload_serve_and_remove(seeded_client: TestClient) -> None:
    dev = contact_id(seeded_client, "Dev Patel")
    post(seeded_client, f"/contacts/{dev}/photo", files={"photo": ("me.png", png(), "image/png")})

    served = seeded_client.get(f"/contacts/{dev}/photo")
    cached = seeded_client.get(
        f"/contacts/{dev}/photo", headers={"If-None-Match": served.headers["etag"]}
    )
    card = seeded_client.get(f"/contacts/{dev}").text
    results = seeded_client.get("/?q=dev+patel").text

    assert served.headers["content-type"] == "image/jpeg"
    assert cached.status_code == 304
    assert 'data-testid="photo"' in card
    assert f'<img class="avatar" src="/contacts/{dev}/photo"' in results
    assert (
        post(
            seeded_client,
            f"/contacts/{dev}/photo",
            files={"photo": ("x.png", b"nope", "image/png")},
        ).status_code
        == 422
    )

    post(seeded_client, f"/contacts/{dev}/photo/remove")
    assert seeded_client.get(f"/contacts/{dev}/photo").status_code == 404
    assert (
        '<span class="photo initials" aria-hidden="true">DP</span>'
        in seeded_client.get(f"/contacts/{dev}").text
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Maria Lopez", "ML"),
        ("Dr. Angela Foster", "AF"),
        ("Cher", "C"),
        ("  ", "?"),
        ("José de la Cruz", "JC"),
    ],
)
def test_initials(name: str, expected: str) -> None:
    assert initials(name) == expected


@pytest.mark.req("T-03")
def test_card_shows_related_people(seeded_client: TestClient) -> None:
    html = seeded_client.get(f"/contacts/{contact_id(seeded_client, 'Chen Wei')}").text
    assert 'data-testid="related"' in html
    assert "same team" in html
