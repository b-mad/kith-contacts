"""Search by meaning with the real model (S-08). Run with `make test-model` after `make model`.

These check that the chosen model and thresholds (ADR-0013) find people from
descriptive questions, and stay quiet when nothing is related.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.config import Settings
from app.db import get_session
from app.embedder import default_model_dir, load_embedder
from app.main import create_app
from app.migrate import ensure_contact_types
from app.models import ContactType
from app.semantic import SemanticService, search_by_meaning

pytestmark = [pytest.mark.model, pytest.mark.req("S-08")]


@pytest.fixture(scope="module")
def model() -> Any:
    return load_embedder(default_model_dir())


@pytest.fixture
def people(settings: Settings, db_session: Session, model: Any) -> Iterator[dict[str, Any]]:
    ensure_contact_types(db_session, settings.contact_types)
    app = create_app(settings, run_migrations=False, embedder=model, background_indexing=False)
    app.dependency_overrides[get_session] = lambda: db_session
    types = {t.name: t.id for t in db_session.scalars(select(ContactType))}
    with TestClient(app) as client:

        def new(name: str, kind: str = "Employee", **fields: Any) -> int:
            body = {"display_name": name, "contact_type_id": types[kind], **fields}
            return int(client.post("/api/contacts", json=body).json()["id"])

        ids = {
            "maya": new("Maya Chen", title="Director, Regulatory Affairs", company="Acme Health",
                        notes="Got our FDA 510(k) clearance over the line in 2025."),
            "dev": new("Dev Patel", title="Staff Engineer", team="Data Platform",
                       works_on="HL7 interface engine, Kafka streaming"),
            "sam": new("Sam Lee", "Vendor", company="QuickShip",
                       notes="Dispatcher for courier routes"),
            "nora": new("Nora Kim", "Vendor", company="LabCo", title="Account manager"),
            "ana": new("Ana Silva", "Customer", title="Pediatric nurse"),
            "omar": new("Omar Reyes", title="CFO", works_on="Budget and annual planning"),
        }  # fmt: skip
        add_activity(
            db_session, ids["sam"], kind="call", summary="Asked about the specimen pickup times"
        )
        add_activity(
            db_session, ids["nora"], kind="meeting", summary="Contract renewal for send-out testing"
        )
        service: SemanticService = app.state.semantic
        service.index_pending(db_session)
        yield {"ids": ids, "service": service, "client": client}


def _names(people: dict[str, Any], session: Session, q: str) -> list[int]:
    return [h.contact.id for h in search_by_meaning(session, people["service"], q)]


@pytest.mark.parametrize(
    ("question", "who"),
    [
        ("the person who helped with the FDA submission", "maya"),
        ("who handles specimen pickups", "sam"),
        ("someone at the lab company about contracts", "nora"),
        ("engineer who knows kafka", "dev"),
        ("who owns the budget", "omar"),
        ("a nurse who works with children", "ana"),
    ],
)
def test_questions_find_the_right_person(
    people: dict[str, Any], db_session: Session, question: str, who: str
) -> None:
    found = _names(people, db_session, question)
    assert found[:1] == [people["ids"][who]], (question, found)
    assert len(found) <= 3  # focused, not a list of everyone


def test_unrelated_questions_find_no_one(people: dict[str, Any], db_session: Session) -> None:
    assert _names(people, db_session, "favorite pizza toppings in Naples") == []


def test_search_page_puts_the_meaning_match_first(people: dict[str, Any]) -> None:
    html = (
        people["client"]
        .get("/contacts/results", params={"q": "the person who helped with the FDA submission"})
        .text
    )
    assert "Best matches by meaning" in html
    assert "FDA 510(k) clearance" in html
