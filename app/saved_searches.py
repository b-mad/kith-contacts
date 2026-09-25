"""Saved searches (S-07, ADR-0012): a name for a search-page query string."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound
from app.models import SavedSearch

SAVED_PARAMS = ("q", "type", "company", "team", "manager", "tag", "list", "favorites", "archived")
MAX_NAME = 100
MAX_QUERY = 1000


def clean_query(params: Mapping[str, str] | str) -> str:
    """Keep only known, non-empty search parameters, in a stable order.

    ``sort`` is left out: a saved search is about *who*, not how they are ordered.
    """
    values = dict(parse_qsl(params)) if isinstance(params, str) else dict(params)
    kept = [(k, " ".join(str(values[k]).split())[:200]) for k in SAVED_PARAMS if values.get(k)]
    return urlencode([(k, v) for k, v in kept if v])


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise ContactError("Give the search a name", "name")
    if len(name) > MAX_NAME:
        raise ContactError(f"Name is longer than {MAX_NAME} characters", "name")
    return name


def _find(session: Session, name: str) -> SavedSearch | None:
    return session.scalars(
        select(SavedSearch).where(func.lower(SavedSearch.name) == name.lower())
    ).first()


def list_saved_searches(session: Session) -> Sequence[SavedSearch]:
    return session.scalars(select(SavedSearch).order_by(func.lower(SavedSearch.name))).all()


def get_saved_search(session: Session, search_id: int) -> SavedSearch:
    saved = session.get(SavedSearch, search_id)
    if saved is None:
        raise ContactNotFound(search_id)
    return saved


def save_search(session: Session, name: str, query: str) -> SavedSearch:
    """Create a saved search; saving again under the same name updates it."""
    clean = _clean_name(name)
    q = clean_query(query)
    if not q:
        raise ContactError("Type a search or pick a filter before saving", "query")
    if len(q) > MAX_QUERY:
        raise ContactError("That search is too long to save", "query")
    saved = _find(session, clean)
    if saved is None:
        saved = SavedSearch(name=clean, query=q)
        session.add(saved)
    else:
        saved.name, saved.query = clean, q
    session.flush()
    return saved


def rename_saved_search(session: Session, saved: SavedSearch, name: str) -> SavedSearch:
    clean = _clean_name(name)
    clash = _find(session, clean)
    if clash is not None and clash.id != saved.id:
        raise ContactError(f"A saved search named “{clean}” already exists", "name")
    saved.name = clean
    session.flush()
    return saved


def delete_saved_search(session: Session, saved: SavedSearch) -> None:
    session.delete(saved)
    session.flush()


_LABELS = {
    "q": "text",
    "type": "type #",
    "company": "company",
    "team": "team",
    "manager": "manager #",
    "tag": "tag",
    "list": "list #",
    "favorites": "favorites",
    "archived": "include archived",
}


def describe_query(query: str) -> str:
    """Readable summary, e.g. 'text “lab res” · tag HL7'."""
    parts = []
    for key, value in parse_qsl(query):
        label = _LABELS.get(key, key)
        if key in {"favorites", "archived"}:
            parts.append(label)
        elif key == "q":
            parts.append(f"{label} “{value}”")
        else:
            parts.append(f"{label}{'' if label.endswith('#') else ' '}{value}")
    return " · ".join(parts)
