"""Search by meaning (S-08, ADR-0013): chunking, indexing, caching, ranking and pages.

These tests use a hashing stand-in for the model; ``tests/test_semantic_model.py``
checks real-model quality (``make test-model``).
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.anonymize import anonymize
from app.config import Settings
from app.contacts import get_contact
from app.db import get_session
from app.embedder import ModelUnavailable, OnnxEmbedder
from app.lists import add_members, create_list
from app.main import create_app, semantic_loop
from app.migrate import ensure_contact_types, upgrade_to_head
from app.models import Activity, ContactType, CustomField, SemanticChunk, SemanticDoc
from app.search import SearchFilters
from app.semantic import (
    SemanticService,
    VectorIndex,
    chunks_hash,
    contact_chunks,
    index_all,
    index_contacts,
    index_counts,
    index_pending,
    mark_all_stale,
    mark_changed,
    pending_ids,
    search_by_meaning,
    split_text,
)
from app.tags import add_tag
from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
from tests.conftest import make_settings
from tests.fake_embedder import HashingEmbedder

pytestmark = pytest.mark.req("S-08")
TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
def service(settings: Settings, embedder: HashingEmbedder) -> SemanticService:
    return SemanticService(settings, embedder=embedder)


@pytest.fixture
def mclient(
    settings: Settings, db_session: Session, embedder: HashingEmbedder
) -> Iterator[TestClient]:
    """An app with search by meaning on (fake model, no background task)."""
    ensure_contact_types(db_session, settings.contact_types)
    app = create_app(settings, run_migrations=False, embedder=embedder, background_indexing=False)
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as client:
        yield client


def _types(session: Session) -> dict[str, int]:
    return {t.name: t.id for t in session.scalars(select(ContactType))}


def _new(client: TestClient, session: Session, name: str, **fields: Any) -> int:
    body = {"display_name": name, "contact_type_id": _types(session)["Employee"], **fields}
    res = client.post("/api/contacts", json=body)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


def _people(client: TestClient, session: Session) -> dict[str, int]:
    return {
        "maya": _new(client, session, "Maya Chen", title="Director", company="Acme Health",
                     notes="Helped us get the FDA 510(k) submission approved; regulatory lead."),
        "dev": _new(client, session, "Dev Patel", team="Data Platform",
                    works_on="HL7 interface engine and Kafka pipelines"),
        "sam": _new(client, session, "Sam Lee", company="QuickShip",
                    notes="Courier dispatcher for specimen pickups"),
        "ana": _new(client, session, "Ana Silva", notes="Met at the soccer practice; loves hiking"),
    }  # fmt: skip


def form_post(client: TestClient, url: str, pairs: list[tuple[str, str]]) -> Any:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    return client.post(
        url,
        content=urlencode([("csrf_token", token.group(1)), *pairs]),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


# ---------------------------------------------------------------- chunks


def test_split_text_packs_paragraphs_and_wraps_long_sentences() -> None:
    assert split_text("One.  Two.\n\nThree") == ["One. Two.", "Three"]
    packed = split_text("A" * 50 + ". " + "B" * 50 + ".", limit=60)
    assert packed == ["A" * 50 + ".", "B" * 50 + "."]
    long = split_text("x" * 130, limit=60)
    assert [len(p) for p in long] == [60, 60, 10]
    assert split_text("short. " + "y" * 70, limit=60) == ["short.", "y" * 60, "y" * 10]
    assert split_text(" \n \n") == []


def test_contact_chunks_describe_the_person(client: TestClient, db_session: Session) -> None:
    boss = _new(client, db_session, "Maria Lopez")
    cid = _new(client, db_session, "Dev Patel", nickname="DP", title="Staff Engineer",
               team="Data Platform", department="IT", company="Acme Health",
               location="Atlanta", manager_id=boss, works_on="Kafka pipelines",
               notes="Para one.\n\nPara two.",
               custom_fields=[{"name": "Epic role", "value": "Bridges analyst"}])  # fmt: skip
    add_tag(db_session, [cid], "HL7")
    add_members(db_session, create_list(db_session, "Q4 LIS"), [cid], "tech lead")
    for day in range(1, 33):
        add_activity(db_session, cid, kind="call", summary=f"Call number {day}",
                     occurred_on=date(2026, 1, day % 28 + 1))  # fmt: skip
    chunks = contact_chunks(get_contact(db_session, cid))
    by_source: dict[str, list[str]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.source, []).append(chunk.text)
    profile = by_source["profile"][0]
    assert profile.startswith("Dev Patel (DP). Staff Engineer, Data Platform team, IT at Acme")
    for part in ("Employee.", "Based in Atlanta.", "Reports to Maria Lopez.", "Tags: HL7.",
                 "Projects: Q4 LIS (tech lead)."):  # fmt: skip
        assert part in profile
    assert by_source["works_on"] == ["Works on Kafka pipelines"]
    assert by_source["notes"] == ["Para one.", "Para two."]
    assert by_source["fields"] == ["Epic role: Bridges analyst"]
    assert len(by_source["activity"]) == 30  # newest 30 only
    assert by_source["activity"][0].startswith("Call on 2026-01-28: ")
    assert chunks_hash(chunks, "m1") != chunks_hash(chunks, "m2")


# ---------------------------------------------------------------- indexing


def test_index_follows_edits(
    client: TestClient, db_session: Session, embedder: HashingEmbedder
) -> None:
    ids = _people(client, db_session)
    assert set(ids.values()) <= set(pending_ids(db_session, embedder.model_id, limit=100))
    assert index_pending(db_session, embedder) == 4
    assert pending_ids(db_session, embedder.model_id) == []
    counts = index_counts(db_session, embedder.model_id)
    assert (counts.indexed, counts.pending) == (counts.contacts, 0)
    assert index_counts(db_session, None).indexed == 0

    # An edit that changes the text marks the contact stale and re-embeds it.
    client.patch(f"/api/contacts/{ids['dev']}", json={"works_on": "FHIR APIs"})
    assert pending_ids(db_session, embedder.model_id) == [ids["dev"]]
    calls = embedder.texts
    assert index_pending(db_session, embedder) == 1
    assert embedder.texts > calls
    texts = db_session.scalars(
        select(SemanticChunk.text).where(SemanticChunk.contact_id == ids["dev"])
    ).all()
    assert "Works on FHIR APIs" in texts

    # Stale but unchanged text: cleared without calling the model.
    mark_all_stale(db_session)
    calls = embedder.calls
    assert index_pending(db_session, embedder, limit=100) == 0
    assert embedder.calls == calls
    assert pending_ids(db_session, embedder.model_id) == []

    # A change made behind the app's back is caught by the hourly re-check.
    db_session.execute(text("UPDATE contact SET notes = 'Moved to finance' WHERE id = :i"),
                       {"i": ids["ana"]})  # fmt: skip
    assert mark_changed(db_session, embedder.model_id) == 1
    assert pending_ids(db_session, embedder.model_id) == [ids["ana"]]

    # Another model means everything is re-embedded.
    other = HashingEmbedder()
    other.model_id = "other-model"
    assert len(pending_ids(db_session, "other-model", limit=100)) == counts.contacts
    assert index_all(db_session, other) == counts.contacts
    assert index_contacts(db_session, other, []) == 0


def test_vector_index_tracks_the_database(
    client: TestClient, db_session: Session, embedder: HashingEmbedder
) -> None:
    ids = _people(client, db_session)
    index_pending(db_session, embedder)
    index = VectorIndex()
    index.sync(db_session, embedder.model_id)
    assert len(index) == 4
    best = index.query(embedder.embed(["specimen courier"])[0])
    assert best[0].contact_id == ids["sam"]
    assert best[0].source == "notes"
    assert len({m.contact_id for m in best}) == len(best)  # one row per contact
    only = index.query(embedder.embed(["specimen courier"])[0], allowed={ids["maya"]})
    assert [m.contact_id for m in only] == [ids["maya"]]
    assert len(index.query(embedder.embed(["x"])[0], top=2)) == 2

    # Re-embedded contacts are reloaded; deleted ones disappear.
    client.patch(f"/api/contacts/{ids['sam']}", json={"notes": "Plays guitar"})
    index_pending(db_session, embedder)
    db_session.execute(text("DELETE FROM contact WHERE id = :i"), {"i": ids["ana"]})
    index.sync(db_session, embedder.model_id)
    assert len(index) == 3
    top = index.query(embedder.embed(["guitar"])[0])[0]
    assert (top.contact_id, top.text) == (ids["sam"], "Plays guitar")
    index.sync(db_session, embedder.model_id)  # nothing changed: no reload
    assert VectorIndex().query(np.ones(384, dtype=np.float32)) == []


def test_search_by_meaning_rules(
    client: TestClient, db_session: Session, service: SemanticService
) -> None:
    ids = _people(client, db_session)
    assert service.index_pending(db_session) == 4
    assert service.last_indexed_at is not None

    hits = search_by_meaning(db_session, service, "who handles specimen pickups")
    assert [h.contact.id for h in hits] == [ids["sam"]]
    assert hits[0].source_label == "notes"
    assert "specimen pickups" in hits[0].text

    # Already-listed people are left out; filters apply.
    assert search_by_meaning(db_session, service, "specimen pickups", exclude=[ids["sam"]]) == []
    vendor_only = SearchFilters(type_id=_types(db_session)["Vendor"])
    assert search_by_meaning(db_session, service, "specimen pickups", vendor_only) == []

    # One word: only when keywords found no one, and with a higher bar.
    assert search_by_meaning(db_session, service, "hiking", keyword_hits=1) == []
    assert [h.contact.id for h in search_by_meaning(db_session, service, "hiking")] == [ids["ana"]]
    assert search_by_meaning(db_session, service, "zebra unicorn") == []  # below the floor
    assert search_by_meaning(db_session, service, "  ") == []
    assert search_by_meaning(db_session, SemanticService(service.settings), "pickups") == []


# ---------------------------------------------------------------- pages and API


def test_meaning_results_on_the_search_page(mclient: TestClient, db_session: Session) -> None:
    ids = _people(mclient, db_session)
    mclient.app.state.semantic.index_pending(db_session)  # type: ignore[attr-defined]

    # No one matches every word: meaning matches come first, with the reason.
    page = mclient.get(
        "/contacts/results", params={"q": "who helped with the FDA submission approval"}
    )
    assert page.status_code == 200
    html = page.text
    assert "Best matches by meaning" in html
    rows = re.findall(r'data-contact-id="(\d+)"[^>]*data-testid="(meaning-row|result-row)"', html)
    assert rows[0] == (str(ids["maya"]), "meaning-row")
    assert "notes:</span> Helped us get the FDA 510(k)" in html
    assert html.count(f'data-contact-id="{ids["maya"]}"') == 1  # not listed twice
    assert "by meaning</p>" in html

    # Keywords match every word: keyword rows first, meaning rows after.
    lin = _new(mclient, db_session, "Lin Wu", notes="Interface engine expert, Kafka too")
    mclient.app.state.semantic.index_pending(db_session)  # type: ignore[attr-defined]
    html = mclient.get("/contacts/results", params={"q": "hl7 interface engine"}).text
    rows = re.findall(r'data-contact-id="(\d+)"[^>]*data-testid="(meaning-row|result-row)"', html)
    assert rows == [(str(ids["dev"]), "result-row"), (str(lin), "meaning-row")]
    assert html.index('data-testid="result-row"') < html.index("Also related, by meaning")

    api = mclient.get("/api/search/meaning", params={"q": "courier for specimen pickups"})
    assert api.status_code == 200
    body = api.json()
    assert body[0]["contact"]["display_name"] == "Sam Lee"
    assert body[0]["source"] == "notes"
    assert 0 < body[0]["score"] <= 1


def test_meaning_unavailable_and_settings(
    client: TestClient, mclient: TestClient, db_session: Session
) -> None:
    res = client.get("/api/search/meaning", params={"q": "anything at all"})
    assert res.status_code == 503
    settings_off = client.get("/settings").text
    assert 'data-testid="semantic-status"' in settings_off
    assert "make model" in settings_off
    assert "Best matches by meaning" not in client.get("/?q=fda+submission").text

    _new(mclient, db_session, "Index Me")
    on = mclient.get("/settings").text
    assert '<span class="pill ok">On</span>' in on
    assert "the rest are being added" in on
    res = form_post(mclient, "/settings/semantic/rebuild", [])
    assert res.status_code == 303
    assert "re-checking every contact" in mclient.get(res.headers["location"]).text


def test_service_load_reports_why(tmp_path: Path, settings: Settings) -> None:
    off = SemanticService(settings)
    assert not off.enabled
    assert off.load() is False
    assert "SEMANTIC_SEARCH=off" in (off.unavailable or "")

    missing = SemanticService(settings.model_copy(update={"semantic_search": "auto",
                                                          "model_dir": tmp_path}))  # fmt: skip
    assert missing.enabled
    assert missing.load() is False
    assert "make model" in (missing.unavailable or "")

    broken_dir = tmp_path / "broken"
    (broken_dir / "onnx").mkdir(parents=True)
    (broken_dir / "onnx/model.onnx").write_bytes(b"not a model")
    (broken_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    broken = SemanticService(settings.model_copy(update={"semantic_search": "auto",
                                                         "model_dir": broken_dir}))  # fmt: skip
    assert broken.load() is False
    assert "could not be loaded" in (broken.unavailable or "")

    with pytest.raises(ModelUnavailable, match="not installed"):
        OnnxEmbedder(tmp_path)
    ready = SemanticService(settings, embedder=HashingEmbedder())
    assert ready.load() is True


def test_anonymized_copy_drops_derived_and_free_text(
    client: TestClient, db_session: Session, embedder: HashingEmbedder
) -> None:
    cid = _new(client, db_session, "Secret Person",
               custom_fields=[{"name": "Spouse", "value": "Jordan"}])  # fmt: skip
    add_activity(db_session, cid, kind="meeting", summary="Talked about Jordan's surgery")
    index_pending(db_session, embedder)
    anonymize(db_session)
    assert db_session.scalars(select(SemanticChunk)).all() == []
    assert db_session.scalars(select(SemanticDoc)).all() == []
    db_session.expire_all()
    summary = db_session.scalars(select(Activity.summary).where(Activity.contact_id == cid)).one()
    assert "Jordan" not in summary
    assert summary.startswith("Meeting ")
    value = db_session.scalars(select(CustomField.value).where(CustomField.contact_id == cid)).one()
    assert "Jordan" not in value


# ---------------------------------------------------------------- background task (real instance)


@pytest.fixture
def live(admin_url: str, tmp_path: Path) -> Iterator[tuple[Settings, InstanceSpec]]:
    spec = InstanceSpec(name=f"ts-{uuid.uuid4().hex[:6]}", port=5194, app_env="test")
    info = bootstrap(spec, admin_url, None)
    settings = make_settings(info.database_url, instance_name="Sem", backup_dir=str(tmp_path))
    upgrade_to_head(settings)
    yield settings, spec
    drop_database(spec, admin_url)


def test_background_task_indexes_new_contacts(
    live: tuple[Settings, InstanceSpec], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _spec = live
    monkeypatch.setattr("app.main.SEMANTIC_IDLE_SECONDS", 0.05)
    with TestClient(create_app(settings, embedder=HashingEmbedder())) as client:
        types = {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}
        client.post("/api/contacts", json={
            "display_name": "Rita Gomez", "contact_type_id": types["Vendor"],
            "notes": "Runs the reference lab courier contract"})  # fmt: skip
        deadline = time.monotonic() + 10
        body: list[Any] = []
        while time.monotonic() < deadline:
            body = client.get("/api/search/meaning", params={"q": "courier contract"}).json()
            if body:
                break
            time.sleep(0.05)
        assert [b["contact"]["display_name"] for b in body] == ["Rita Gomez"]
        assert client.app.state.semantic.last_error is None  # type: ignore[attr-defined]


def test_loop_stops_quietly_without_a_model(settings: Settings, db_session: Session) -> None:
    service = SemanticService(settings.model_copy(update={"semantic_search": "auto",
                                                          "model_dir": Path("/nonexistent")}))  # fmt: skip
    asyncio.run(semantic_loop(service, None))
    assert service.unavailable is not None
    assert service.index_pending(db_session) == 0
