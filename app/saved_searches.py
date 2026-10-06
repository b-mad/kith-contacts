"""Saved searches (S-07, ADR-0012): a name for a search-page query string."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound
from app.models import SavedSearch
from app.privacy import presenting, private_refs

SAVED_PARAMS = (
    "q", "type", "company", "team", "manager", "tag", "tag_match", "list", "list_match",
    "favorites", "archived", "contacted", "due", "near", "within",  # near: S-14
)  # fmt: skip
#: S-15: these may repeat (``company=A&company=B``); every other parameter keeps its last value.
MULTI_PARAMS = frozenset({"company", "team", "tag", "list"})
MAX_NAME = 100
MAX_QUERY = 1000


def clean_query(params: Mapping[str, str] | Sequence[tuple[str, str]] | str) -> str:
    """Keep only known, non-empty search parameters, in a stable order.

    ``sort`` is left out: a saved search is about *who*, not how they are ordered.
    """
    if isinstance(params, str):
        pairs = parse_qsl(params)
    elif isinstance(params, Mapping):
        pairs = [(str(k), str(v)) for k, v in params.items()]
    else:
        pairs = [(str(k), str(v)) for k, v in params]
    kept: list[tuple[str, str]] = []
    for key in SAVED_PARAMS:
        values = [" ".join(v.split())[:200] for k, v in pairs if k == key]
        values = [v for v in values if v]
        if key in MULTI_PARAMS:
            seen = dict.fromkeys(values)  # no repeats, order kept
            kept += [(key, v) for v in list(seen)[:25]]
        elif key in {"tag_match", "list_match"}:
            if values and values[-1] == "all":  # "any" is the default and stays out of the URL
                kept.append((key, "all"))
        elif values:
            kept.append((key, values[-1]))
    return urlencode(kept)


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
    rows = session.scalars(select(SavedSearch).order_by(func.lower(SavedSearch.name))).all()
    if presenting() is None:
        return rows
    tags, lists, contacts = private_refs(session)  # P-02: a saved search can name them
    return [s for s in rows if not _mentions(s.query, tags, lists, contacts)]


def _mentions(query: str, tags: set[str], lists: set[int], contacts: set[int]) -> bool:
    pairs = parse_qsl(query)
    return (
        any(v.lower() in tags for k, v in pairs if k == "tag")
        or any(_id(v) in lists for k, v in pairs if k == "list")
        or any(_id(v) in contacts for k, v in pairs if k == "manager")
    )


def _id(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


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
    "contacted": "contacted in the last",
    "due": "due to reconnect",
}


def describe_query(query: str) -> str:
    """Readable summary, e.g. 'text “lab res” · tag HL7'."""
    parts = []
    for key, value in parse_qsl(query):
        label = _LABELS.get(key, key)
        if key in {"favorites", "archived", "due"}:
            parts.append(label)
        elif key == "contacted":
            parts.append(f"{label} {value} days")
        elif key == "q":
            parts.append(f"{label} “{value}”")
        else:
            parts.append(f"{label}{'' if label.endswith('#') else ' '}{value}")
    return " · ".join(parts)
