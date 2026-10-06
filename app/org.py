"""Org chart (S-06, S-16, S-17): manager chains up and reporting trees down.

Two views are built from one directory of people (ADR-0030):

* **Focus** (``build_focus``): one person with their chain of managers, peers and direct reports.
* **Outline** (``build_org`` + ``outline_rows``): the whole tree as rows that open and close.

Presenting mode (ADR-0016) applies. Private contacts never reach the query (the session
filters them), a hidden photo category yields initials, and "names and companies only" also
blanks title and team.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactPhoto
from app.privacy import presenting

MAX_DEPTH = 12
MAX_PEERS = 8  # peer chips shown before "+N more"
MAX_MATCHES = 20  # people listed for a search on the Focus view
LEVEL_CHOICES: Final = ("1", "2", "3", "all")
DEFAULT_LEVELS: Final = "2"
_WORD = re.compile(r"\w+")


@dataclass
class OrgNode:
    id: int
    name: str
    title: str | None
    team: str | None
    has_photo: bool = False
    children: list[OrgNode] = field(default_factory=list)

    @property
    def direct(self) -> int:
        return len(self.children)

    @property
    def total_reports(self) -> int:
        return sum(1 + c.total_reports for c in self.children)


@dataclass
class OrgView:
    chain: list[OrgNode]  # managers above the focus, top first
    roots: list[OrgNode]  # the tree(s) to draw
    focus_id: int | None
    unplaced: int  # active people with neither a manager nor reports


@dataclass(frozen=True)
class OrgPerson:
    """One person on a card or chip: who they are and how big their organization is."""

    id: int
    name: str
    title: str | None
    team: str | None
    has_photo: bool
    direct: int  # direct reports
    total: int  # everyone below them


@dataclass
class FocusView:
    focus: OrgPerson | None  # None: the top-level leaders
    chain: list[OrgPerson]  # managers above the focus, top first
    manager: OrgPerson | None
    peers: list[OrgPerson]  # same manager (or the other top-level leaders), without the focus
    more_peers: int  # peers not listed
    cards: list[OrgPerson]  # the focus's direct reports, or the top-level leaders
    unplaced: int


@dataclass(frozen=True)
class OutlineRow:
    person: OrgPerson
    depth: int
    parent_id: int | None
    open: bool  # children shown
    expandable: bool  # has rows beneath it on this page
    hidden: bool  # an ancestor is closed
    hit: bool  # matches the search


class _Directory:
    """Everyone active, who reports to whom, and who has a photo."""

    def __init__(self, session: Session) -> None:
        p = presenting()
        self.names_only = p is not None and p.names_only
        rows = session.execute(
            select(
                Contact.id, Contact.display_name, Contact.title, Contact.team, Contact.manager_id
            ).where(Contact.archived_at.is_(None))
        ).all()
        self.rows = rows
        self.info = {r.id: r for r in rows}
        no_photos = p is not None and (p.hides("photo") or p.names_only)
        self.photos: set[int] = (
            set() if no_photos else set(session.scalars(select(ContactPhoto.contact_id)))
        )
        kids: dict[int, list[int]] = defaultdict(list)
        for r in rows:
            if r.manager_id in self.info:
                kids[r.manager_id].append(r.id)
        for ids in kids.values():
            ids.sort(key=lambda c: self.info[c].display_name.lower())
        self.children: dict[int, list[int]] = dict(kids)
        self._totals: dict[int, int] = {}

    def total(self, contact_id: int, path: frozenset[int] = frozenset()) -> int:
        if contact_id in self._totals:
            return self._totals[contact_id]
        count = sum(
            1 + self.total(c, path | {contact_id})
            for c in self.children.get(contact_id, [])
            if c not in path and c != contact_id  # cycle guard; the service layer prevents cycles
        )
        self._totals[contact_id] = count
        return count

    def title(self, contact_id: int) -> str | None:
        return None if self.names_only else self.info[contact_id].title

    def team(self, contact_id: int) -> str | None:
        return None if self.names_only else self.info[contact_id].team

    def person(self, contact_id: int) -> OrgPerson:
        r = self.info[contact_id]
        return OrgPerson(
            r.id,
            r.display_name,
            self.title(contact_id),
            self.team(contact_id),
            r.id in self.photos,
            len(self.children.get(contact_id, [])),
            self.total(contact_id),
        )

    def node(self, contact_id: int) -> OrgNode:
        r = self.info[contact_id]
        return OrgNode(r.id, r.display_name, self.title(r.id), self.team(r.id), r.id in self.photos)

    def top(self) -> list[int]:
        """People with reports and no manager, the biggest organization first."""
        ids = [r.id for r in self.rows if r.manager_id not in self.info and self.children.get(r.id)]
        return sorted(ids, key=lambda i: (-self.total(i), self.info[i].display_name.lower()))

    def unplaced(self) -> int:
        return sum(
            1 for r in self.rows if r.manager_id not in self.info and not self.children.get(r.id)
        )

    def chain(self, contact_id: int) -> list[int]:
        """Managers above a person, top first."""
        chain: list[int] = []
        current = self.info[contact_id].manager_id
        seen = {contact_id}
        while current in self.info and current not in seen and len(chain) < MAX_DEPTH:
            chain.insert(0, current)
            seen.add(current)
            current = self.info[current].manager_id
        return chain


def build_org(session: Session, focus_id: int | None = None) -> OrgView:
    """The reporting tree: everyone (no focus), or a person's chain above and tree below."""
    directory = _Directory(session)

    def node(contact_id: int, depth: int, seen: set[int]) -> OrgNode:
        result = directory.node(contact_id)
        if depth < MAX_DEPTH:
            for child in directory.children.get(contact_id, []):
                if child not in seen:  # cycle guard; the service layer prevents cycles anyway
                    result.children.append(node(child, depth + 1, seen | {child}))
        return result

    if focus_id is not None and focus_id in directory.info:
        chain = [directory.node(m) for m in directory.chain(focus_id)]
        return OrgView(chain, [node(focus_id, 0, {focus_id})], focus_id, 0)
    roots = [node(t, 0, {t}) for t in directory.top()]
    return OrgView([], roots, None, directory.unplaced())


def build_focus(session: Session, focus_id: int | None = None) -> FocusView:
    """S-16: one person with their chain, peers and direct reports (or the top-level leaders)."""
    directory = _Directory(session)
    if focus_id is None or focus_id not in directory.info:
        cards = [directory.person(i) for i in directory.top()]
        return FocusView(None, [], None, [], 0, cards, directory.unplaced())
    chain_ids = directory.chain(focus_id)
    manager_id = chain_ids[-1] if chain_ids else None
    sibling_ids = directory.children.get(manager_id, []) if manager_id else directory.top()
    peer_ids = [i for i in sibling_ids if i != focus_id]
    return FocusView(
        focus=directory.person(focus_id),
        chain=[directory.person(i) for i in chain_ids],
        manager=directory.person(manager_id) if manager_id else None,
        peers=[directory.person(i) for i in peer_ids[:MAX_PEERS]],
        more_peers=max(0, len(peer_ids) - MAX_PEERS),
        cards=[directory.person(i) for i in directory.children.get(focus_id, [])],
        unplaced=0,
    )


def search_terms(text: str) -> list[str]:
    """Lower-case words of a search box; each must start a word of the name or title."""
    return [w.lower() for w in _WORD.findall(text)][:8]


def _matches(name: str, title: str | None, terms: Sequence[str]) -> bool:
    words = [w.lower() for w in _WORD.findall(f"{name} {title or ''}")]
    return all(any(w.startswith(t) for w in words) for t in terms)


def find_people(session: Session, text: str) -> list[OrgPerson]:
    """People in the chart (with a manager or reports) whose name or title match the words."""
    terms = search_terms(text)
    if not terms:
        return []
    directory = _Directory(session)
    found = [
        r.id
        for r in directory.rows
        if (r.manager_id in directory.info or directory.children.get(r.id))
        and _matches(r.display_name, directory.title(r.id), terms)
    ]
    found.sort(key=lambda i: directory.info[i].display_name.lower())
    return [directory.person(i) for i in found[:MAX_MATCHES]]


def outline_rows(
    roots: Sequence[OrgNode], levels: str = DEFAULT_LEVELS, terms: Sequence[str] = ()
) -> list[OutlineRow]:
    """S-17: the tree as flat rows. ``levels`` is "1", "2", "3" or "all": how many levels show.

    With search words only matching people and the managers above them are listed, and those
    managers are open so every match is visible."""
    shown_levels = None if levels == "all" else int(levels)
    rows: list[OutlineRow] = []

    def person(n: OrgNode) -> OrgPerson:
        return OrgPerson(n.id, n.name, n.title, n.team, n.has_photo, n.direct, n.total_reports)

    def walk(n: OrgNode, depth: int, parent: int | None, parent_open: bool) -> bool:
        """Append the rows for ``n`` and below; False when nothing under or at ``n`` matches."""
        start = len(rows)
        rows.append(OutlineRow(person(n), depth, parent, False, False, not parent_open, False))
        hit = bool(terms) and _matches(n.name, n.title, terms)
        if terms:
            is_open = True  # a manager of a match must be open; closed ones get no rows
        else:
            is_open = n.direct > 0 and (shown_levels is None or depth + 1 < shown_levels)
        kept = False
        for child in n.children:
            kept |= walk(child, depth + 1, n.id, parent_open and is_open)
        if terms and not hit and not kept:
            del rows[start:]
            return False
        rows[start] = OutlineRow(
            person(n), depth, parent, is_open and kept if terms else is_open,
            kept if terms else n.direct > 0, not parent_open, hit,
        )  # fmt: skip
        return True

    for root in roots:
        walk(root, 0, None, True)
    return rows
