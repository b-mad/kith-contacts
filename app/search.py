"""Context search (S-01 to S-05, ADR-0003).

Each contact has a weighted ``search_vector``:

    A  display, first, last and nick names
    B  team, company, manager's name, tags
    C  title, department, works on, list names, emails, custom fields
    D  notes, location, activity summaries, address city/region/postal code/country

``refresh_search`` rebuilds it for given contacts; every write that changes
any of those inputs must call it (the service layer does). Queries use prefix
matching ("lab res" finds "lab results"), fall back to matching any word when
all words don't match, and to trigram similarity on names for typos ("Mria").
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

from markupsafe import Markup
from sqlalchemy import (
    ColumnElement,
    Select,
    bindparam,
    case,
    func,
    literal,
    literal_column,
    select,
    text,
)
from sqlalchemy.orm import Session, selectinload

from app.geo import EARTH_MILES
from app.models import Activity, Contact, ContactAddress, ContactList, ListMember, Tag, contact_tag
from app.privacy import Presenting, presenting
from app.timephrase import INTERACTION_KINDS, TimeQuery, parse_time_query

FUZZY_THRESHOLD = 0.3
NAME_WEIGHT = "'{a}'::\"char\"[]"  # ts_filter weight array: names only
MultiMatch = Literal["any", "all"]
SortKey = Literal["relevance", "name", "company", "team", "type", "updated", "last_contact"]
SORT_KEYS: tuple[SortKey, ...] = (
    "relevance", "name", "company", "team", "type", "updated", "last_contact",
)  # fmt: skip

# Kept in sync with the newest migration that embeds a frozen copy (0010).
_DOCUMENT_SQL = """
    setweight(to_tsvector('simple', concat_ws(' ', c.display_name, c.first_name, c.last_name,
        c.nickname)), 'A')
    || setweight(to_tsvector('simple', concat_ws(' ', c.team, c.company,
        (SELECT m.display_name FROM contact m WHERE m.id = c.manager_id),
        (SELECT string_agg(t.name, ' ') FROM contact_tag ct JOIN tag t ON t.id = ct.tag_id
          WHERE ct.contact_id = c.id))), 'B')
    || setweight(to_tsvector('simple', concat_ws(' ', c.title, c.department, c.works_on,
        (SELECT string_agg(cl.name, ' ') FROM list_member lm
           JOIN contact_list cl ON cl.id = lm.list_id WHERE lm.contact_id = c.id),
        (SELECT string_agg(ce.email || ' ' || translate(ce.email, '.@_-+', '     '), ' ')
           FROM contact_email ce WHERE ce.contact_id = c.id),
        (SELECT string_agg(cf.name || ' ' || cf.value, ' ')
           FROM custom_field cf WHERE cf.contact_id = c.id))), 'C')
    || setweight(to_tsvector('simple', concat_ws(' ', c.notes, c.location,
        (SELECT string_agg(a.summary, ' ') FROM activity a WHERE a.contact_id = c.id),
        (SELECT string_agg(concat_ws(' ', ad.city, ad.region, ad.postal_code, ad.country), ' ')
           FROM contact_address ad WHERE ad.contact_id = c.id))), 'D')
"""

# The f-string only inserts the constant _DOCUMENT_SQL; ids are a bound parameter.
# A single-table UPDATE (no self-join) keeps the plan linear even with stale stats.
REFRESH_SQL = text(
    f"""
    UPDATE contact AS c SET search_vector = {_DOCUMENT_SQL}
    WHERE c.id = ANY(:ids)
    """  # noqa: S608
).bindparams(bindparam("ids"))
REFRESH_ALL_SQL = text(f"UPDATE contact AS c SET search_vector = {_DOCUMENT_SQL}")  # noqa: S608


def refresh_search(session: Session, contact_ids: Iterable[int]) -> None:
    """Rebuild the search document for these contacts (S-01)."""
    ids = sorted({int(i) for i in contact_ids if i is not None})
    if ids:
        session.flush()
        session.execute(REFRESH_SQL, {"ids": ids})
        session.execute(MARK_STALE_SQL, {"ids": ids})  # S-08: re-embed soon (ADR-0013)


def refresh_all(session: Session) -> None:
    session.flush()
    session.execute(REFRESH_ALL_SQL)
    session.execute(text("UPDATE semantic_doc SET stale = true"))


MARK_STALE_SQL = text("UPDATE semantic_doc SET stale = true WHERE contact_id = ANY(:ids)")


# ---------------------------------------------------------------- query parsing

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def query_terms(q: str, *, limit: int = 8) -> list[str]:
    """Lower-cased word fragments, e.g. 'Lab-res, Maria' -> ['lab', 'res', 'maria']."""
    return [w.lower() for w in _WORD.findall(q)][:limit]


def to_tsquery_text(terms: Sequence[str], operator: Literal["&", "|"]) -> str:
    """Prefix query: every term becomes ``term:*``. Terms are already alphanumeric."""
    return f" {operator} ".join(f"{t}:*" for t in terms)


# ---------------------------------------------------------------- filters

MAX_MULTI_VALUES = 25  # S-15: values per filter; a longer list is cut, not an error


def multi_texts(values: Iterable[str]) -> tuple[str, ...]:
    """S-15: filter values from a query string — trimmed, no blanks, no repeats ignoring case."""
    seen: dict[str, str] = {}
    for raw in values:
        text = " ".join(raw.split())[:200]
        if text:
            seen.setdefault(text.lower(), text)
    return tuple(seen.values())[:MAX_MULTI_VALUES]


def multi_ids(values: Iterable[str]) -> tuple[int, ...]:
    """S-15: ids from a query string, in order, without repeats."""
    found = dict.fromkeys(int(v) for v in values if v.strip().isdigit())
    return tuple(found)[:MAX_MULTI_VALUES]


def match_mode(value: str | None) -> MultiMatch:
    return "all" if value == "all" else "any"


@dataclass(frozen=True)
class SearchFilters:
    """S-04: combinable filters."""

    type_id: int | None = None
    # S-15: Company, Team, Tag and List take several values. Within one filter, a person
    # matches any of the values (a person has one company); Tag and List can instead require
    # all of them. Different filters always combine with "and".
    companies: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()
    manager_id: int | None = None
    tags: tuple[str, ...] = ()
    tag_match: MultiMatch = "any"
    list_ids: tuple[int, ...] = ()
    list_match: MultiMatch = "any"
    favorites: bool = False
    include_archived: bool = False
    # S-09/S-10: people with an interaction (not a note) in this period, optionally of these kinds.
    active_from: date | None = None
    active_to: date | None = None
    kinds: tuple[str, ...] = ()
    # S-11: people whose keep-in-touch reminder is due on or before this date.
    due_by: date | None = None
    # S-13: exactly these people (a selection shown on the map).
    ids: tuple[int, ...] = ()
    # S-14: within ``near_miles`` of a point (an address of theirs, not just any mention).
    near_lat: float | None = None
    near_lon: float | None = None
    near_miles: float = 50
    # S-13: people with no address that could be placed on the map.
    unplaced: bool = False

    @property
    def has_near(self) -> bool:
        return self.near_lat is not None and self.near_lon is not None

    @property
    def has_period(self) -> bool:
        return self.active_from is not None or self.active_to is not None or bool(self.kinds)

    def interactions(self) -> Any:
        """Activities that count for the period filter (correlated on the outer contact)."""
        cond: list[ColumnElement[bool]] = [Activity.kind.in_(self.kinds or INTERACTION_KINDS)]
        if self.active_from is not None:
            cond.append(Activity.occurred_on >= self.active_from)
        if self.active_to is not None:
            cond.append(Activity.occurred_on <= self.active_to)
        return cond

    def apply(self, stmt: Select[tuple[Contact]]) -> Select[tuple[Contact]]:
        if not self.include_archived:
            stmt = stmt.where(Contact.archived_at.is_(None))
        if self.type_id is not None:
            stmt = stmt.where(Contact.contact_type_id == self.type_id)
        if self.companies:
            stmt = stmt.where(func.lower(Contact.company).in_([c.lower() for c in self.companies]))
        if self.teams:
            stmt = stmt.where(func.lower(Contact.team).in_([t.lower() for t in self.teams]))
        if self.manager_id is not None:
            stmt = stmt.where(Contact.manager_id == self.manager_id)
        if self.tags:
            wanted = [t.lower() for t in self.tags]
            for names in [wanted] if self.tag_match == "any" else [[t] for t in wanted]:
                stmt = stmt.where(
                    Contact.id.in_(
                        select(contact_tag.c.contact_id)
                        .join(Tag, Tag.id == contact_tag.c.tag_id)
                        .where(func.lower(Tag.name).in_(names))
                    )
                )
        if self.list_ids:
            for ids in (
                [self.list_ids] if self.list_match == "any" else [(i,) for i in self.list_ids]
            ):
                stmt = stmt.where(
                    Contact.id.in_(
                        select(ListMember.contact_id)
                        .join(ContactList, ContactList.id == ListMember.list_id)  # private: P-02
                        .where(ListMember.list_id.in_(ids))
                    )
                )
        if self.favorites:
            stmt = stmt.where(Contact.is_favorite.is_(True))
        if self.due_by is not None:
            from app.keep_in_touch import due_column  # app.contacts imports this module

            stmt = stmt.where(due_column() <= self.due_by)
        if self.has_period:
            stmt = stmt.where(
                select(Activity.id)
                .where(Activity.contact_id == Contact.id, *self.interactions())
                .exists()
            )
        if self.ids:
            stmt = stmt.where(Contact.id.in_(self.ids))
        if self.near_lat is not None and self.near_lon is not None:
            stmt = stmt.where(Contact.id.in_(self._near_ids(self.near_lat, self.near_lon)))
        if self.unplaced:
            placed = select(ContactAddress.id).where(
                ContactAddress.contact_id == Contact.id, ContactAddress.latitude.is_not(None)
            )
            stmt = stmt.where(~placed.exists())
        return stmt

    def _near_ids(self, lat: float, lon: float) -> Any:
        """Addresses within ``near_miles`` (haversine); a bounding box first keeps it quick.
        While presenting, hidden (personal) addresses don't count (P-02)."""
        miles = self.near_miles
        dlat = miles / 69.0
        dlon = miles / max(1.0, 69.0 * math.cos(math.radians(lat)))
        a = ContactAddress
        rad = func.radians
        hav = func.power(func.sin(rad(a.latitude - lat) / 2), 2) + func.cos(rad(lat)) * func.cos(
            rad(a.latitude)
        ) * func.power(func.sin(rad(a.longitude - lon) / 2), 2)
        return select(a.contact_id).where(
            a.latitude.between(lat - dlat, lat + dlat),
            a.longitude.between(lon - dlon, lon + dlon),
            2 * EARTH_MILES * func.asin(func.sqrt(func.least(1.0, hav))) <= miles,
        )

    @property
    def active(self) -> bool:
        return any(
            (
                self.type_id is not None,
                bool(self.companies),
                bool(self.teams),
                self.manager_id is not None,
                bool(self.tags),
                bool(self.list_ids),
                self.favorites,
                self.has_period,
                self.due_by is not None,
                bool(self.ids),
                self.has_near,
                self.unplaced,
            )
        )


# ---------------------------------------------------------------- results


MatchMode = Literal["all", "any", "fuzzy", "list"]


@dataclass
class SearchHit:
    contact: Contact
    rank: float = 0.0
    matched: list[tuple[str, str]] = field(default_factory=list)
    fuzzy: bool = False
    mode: MatchMode = "list"  # all words / some words / typo match / no query
    hidden: list[str] = field(default_factory=list)  # P-04: matched where it can't be quoted


def _with_details(stmt: Select[tuple[Contact]]) -> Select[tuple[Contact]]:
    return stmt.options(
        selectinload(Contact.contact_type),
        selectinload(Contact.emails),
        selectinload(Contact.phones),
        selectinload(Contact.addresses),
        selectinload(Contact.manager),
        selectinload(Contact.reports),
        selectinload(Contact.tags),
        selectinload(Contact.photo),
        selectinload(Contact.memberships).selectinload(ListMember.contact_list),
    )


def _order(sort: SortKey) -> list[Any]:
    name = func.lower(Contact.display_name)
    orders: dict[str, list[Any]] = {
        "relevance": [name],
        "name": [name],
        "company": [func.lower(Contact.company).nulls_last(), name],
        "team": [func.lower(Contact.team).nulls_last(), name],
        "type": [Contact.contact_type_id, name],
        "updated": [Contact.updated_at.desc(), name],
        "last_contact": [_last_contact_column().desc().nulls_last(), name],
    }
    return orders[sort]


def _last_contact_column() -> Any:
    return (
        select(func.max(Activity.occurred_on))
        .where(Activity.contact_id == Contact.id, Activity.kind.in_(INTERACTION_KINDS))
        .scalar_subquery()
    )


def last_interactions(
    session: Session, contact_ids: Iterable[int], filters: SearchFilters | None = None
) -> dict[int, Activity]:
    """S-09/S-10: each contact's latest interaction (within the filter's period, if any)."""
    ids = sorted(set(contact_ids))
    if not ids:
        return {}
    filters = filters or SearchFilters()
    stmt = (
        select(Activity)
        .where(Activity.contact_id.in_(ids), *filters.interactions())
        .order_by(Activity.contact_id, Activity.occurred_on.desc(), Activity.id.desc())
        .distinct(Activity.contact_id)
    )
    return {a.contact_id: a for a in session.scalars(stmt)}


def apply_time_query(q: str, filters: SearchFilters) -> tuple[str, SearchFilters, TimeQuery | None]:
    """S-10: turn a time phrase in ``q`` into a period filter; returns the words left to search."""
    tq = parse_time_query(q) if q else None
    if tq is None:
        return q, filters, None
    start = max(tq.start, filters.active_from) if filters.active_from else tq.start
    narrowed = replace(filters, active_from=start, active_to=tq.end, kinds=tq.kinds)
    return " ".join(tq.terms), narrowed, tq


def search(
    session: Session,
    q: str = "",
    filters: SearchFilters | None = None,
    *,
    sort: SortKey = "relevance",
    limit: int = 200,
) -> list[SearchHit]:
    """Ranked context search (S-01 to S-04). With no query, lists contacts by ``sort``."""
    filters = filters or SearchFilters()
    terms = query_terms(q)
    base = filters.apply(_with_details(select(Contact)))

    if not terms:
        rows = session.scalars(base.order_by(*_order(sort)).limit(limit)).all()
        return [SearchHit(c) for c in rows]

    hits: dict[int, SearchHit] = {}

    name_query = func.to_tsquery("simple", literal(to_tsquery_text(terms, "|")))

    def run(operator: Literal["&", "|"]) -> None:
        tsq = func.to_tsquery("simple", literal(to_tsquery_text(terms, operator)))
        # ts_rank saturates when many fields match, so a match on the person's own
        # name (weight A) gets an explicit boost: "data platform maria" puts Maria
        # first, then her team.
        name_boost = case(
            (
                func.ts_filter(Contact.search_vector, literal_column(NAME_WEIGHT)).op("@@")(
                    name_query
                ),
                1.0,
            ),
            else_=0.0,
        )
        rank = func.ts_rank(Contact.search_vector, tsq, 1) + name_boost
        stmt = base.add_columns(rank).where(Contact.search_vector.op("@@")(tsq))
        order = (
            [rank.desc(), func.lower(Contact.display_name)] if sort == "relevance" else _order(sort)
        )
        mode: MatchMode = "all" if operator == "&" else "any"
        for contact, score in session.execute(stmt.order_by(*order).limit(limit)).all():
            hits.setdefault(contact.id, SearchHit(contact, float(score), mode=mode))

    run("&")
    if not hits and len(terms) > 1:
        run("|")  # nobody matches every word: rank those matching the most words
    if len(hits) < 3:
        # Typo tolerance on names (S-03): trigram similarity, e.g. "Mria" -> "Maria".
        phrase = " ".join(terms)
        name = func.lower(Contact.display_name)
        sim = func.greatest(func.similarity(name, phrase), func.word_similarity(phrase, name))
        stmt = base.add_columns(sim).where(sim >= FUZZY_THRESHOLD)
        for contact, score in session.execute(stmt.order_by(sim.desc()).limit(10)).all():
            if contact.id not in hits:
                hits[contact.id] = SearchHit(contact, float(score) * 0.01, fuzzy=True, mode="fuzzy")

    results = list(hits.values())
    p = presenting()
    for hit in results:
        hit.matched = matched_fields(hit.contact, terms)
        if p is not None and not hit.fuzzy:
            hit.hidden = hidden_matches(hit.contact, terms, hit.matched, p, every=hit.mode == "all")
    return results


# ---------------------------------------------------------------- match context (S-02)

_SNIPPET = 60


def _field_values(contact: Contact) -> list[tuple[str, str]]:
    """Context a match can quote; while presenting, only what may be shown (P-04)."""
    p = presenting()
    if p is not None and p.names_only:
        return [("company", contact.company)] if contact.company else []
    manager = contact.manager
    values: list[tuple[str, str | None]] = [
        ("team", contact.team),
        ("manager", manager.display_name if manager and not _private(manager, p) else None),
        ("company", contact.company),
        ("title", contact.title),
        ("department", contact.department),
        ("works on", contact.works_on),
        *[("tag", t.name) for t in contact.tags if not _private(t, p)],
        *[
            ("list", m.contact_list.name)
            for m in contact.memberships
            if m.contact_list is not None and not _private(m.contact_list, p)
        ],
        *[("email", e.email) for e in contact.emails if p is None or not p.personal(e.label)],
        ("location", None if p and p.hides("location") else contact.location),
        *[
            ("address", _place(a))
            for a in contact.addresses
            if p is None or (not p.hides("location") and not p.personal(a.label))
        ],
        ("notes", None if p and p.hides("notes") else contact.notes),
        ("aka", " ".join(filter(None, [contact.first_name, contact.last_name, contact.nickname]))),
    ]
    return [(label, v) for label, v in values if v]


def _place(address: ContactAddress) -> str:
    """C-19: the searchable part of an address, e.g. "Olathe KS 66061 United States"."""
    parts = (address.city, address.region, address.postal_code, address.country)
    return " ".join(p for p in parts if p)


def _private(item: Contact | Tag | ContactList, p: Presenting | None) -> bool:
    if p is None:
        return False
    return p.private_contact(item) if isinstance(item, Contact) else item.is_private


def hidden_matches(
    contact: Contact,
    terms: Sequence[str],
    shown: Sequence[tuple[str, str]],
    p: Presenting,
    *,
    every: bool = True,
) -> list[str]:
    """P-04: where a match was found that presenting can't quote, e.g. ["notes"].

    ``every``: the contact matched all the words (else some). Notes and location are
    named; anything else (activity, private tags or lists,
    personal emails, private extra fields) is "a hidden detail".
    """
    if not p.placeholders:
        return []
    name_words = [w.lower() for w in _WORD.findall(contact.display_name)]
    pending = [t for t in terms if not any(w.startswith(t) for w in name_words)]
    for _, value in shown:
        words = [w.lower() for w in _WORD.findall(value)]
        pending = [t for t in pending if not any(w.startswith(t) for w in words)]
    if not pending or (not every and len(pending) < len(terms)):
        return []  # "some words" matches: one visible match explains the result
    named: list[str] = []
    places = " ".join(_place(a) for a in contact.addresses)
    location = " ".join(filter(None, [contact.location, places]))
    for label, private in (("notes", contact.notes), ("location", location)):
        if private and p.hides(label):
            words = [w.lower() for w in _WORD.findall(private)]
            if any(any(w.startswith(t) for w in words) for t in pending):
                named.append(label)
    return named or ["a hidden detail"]


def _snippet(value: str, term: str) -> str:
    flat = " ".join(value.split())
    if len(flat) <= _SNIPPET:
        return flat
    pos = flat.lower().find(term)
    start = max(0, pos - 20)
    end = min(len(flat), start + _SNIPPET)
    return ("…" if start else "") + flat[start:end].strip() + ("…" if end < len(flat) else "")


def matched_fields(contact: Contact, terms: Sequence[str]) -> list[tuple[str, str]]:
    """Which context fields matched the query, e.g. [("team", "Data Platform")].

    Words that match the person's own name are left out: the name is already shown.
    """
    name_words = [w.lower() for w in _WORD.findall(contact.display_name)]
    context_terms = [t for t in terms if not any(w.startswith(t) for w in name_words)]
    found: list[tuple[str, str]] = []
    for label, value in _field_values(contact):
        words = [w.lower() for w in _WORD.findall(value)]
        hit = next((t for t in context_terms if any(w.startswith(t) for w in words)), None)
        if hit is not None:
            item = (label, _snippet(value, hit))
            if item not in found:
                found.append(item)
    return found


def highlight(text: str, terms: Sequence[str]) -> Markup:
    """S-02: wrap each word that a search term starts, e.g. "lab <mark>results</mark>".

    The text is escaped first, so it is safe to render as HTML.
    """
    if not terms:
        return Markup.escape(text)
    out: list[str] = []
    last = 0
    for match in _WORD.finditer(text):
        word = match.group(0)
        if any(word.lower().startswith(t) for t in terms):
            out.append(str(Markup.escape(text[last : match.start()])))
            out.append(f"<mark>{Markup.escape(word)}</mark>")
            last = match.end()
    out.append(str(Markup.escape(text[last:])))
    return Markup("".join(out))  # noqa: S704 - every piece above is escaped


# ---------------------------------------------------------------- facets for filter dropdowns


def distinct_values(session: Session, column: Any) -> list[str]:
    rows = session.execute(
        select(column)
        .where(column.is_not(None), Contact.archived_at.is_(None))
        .group_by(column)
        .order_by(func.lower(column))
    ).scalars()
    return [r for r in rows if r]


def active_lists(session: Session) -> Sequence[ContactList]:
    return session.scalars(
        select(ContactList)
        .where(ContactList.status == "active")
        .order_by(func.lower(ContactList.name))
    ).all()
