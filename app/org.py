"""Org chart (S-06): manager chains up and reporting trees down."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact

MAX_DEPTH = 12


@dataclass
class OrgNode:
    id: int
    name: str
    title: str | None
    team: str | None
    children: list[OrgNode] = field(default_factory=list)

    @property
    def total_reports(self) -> int:
        return sum(1 + c.total_reports for c in self.children)


@dataclass
class OrgView:
    chain: list[OrgNode]  # managers above the focus, top first
    roots: list[OrgNode]  # the tree(s) to draw
    focus_id: int | None
    unplaced: int  # active people with neither a manager nor reports


def build_org(session: Session, focus_id: int | None = None) -> OrgView:
    rows = session.execute(
        select(
            Contact.id, Contact.display_name, Contact.title, Contact.team, Contact.manager_id
        ).where(Contact.archived_at.is_(None))
    ).all()
    info = {r.id: r for r in rows}
    children: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        if r.manager_id in info:
            children[r.manager_id].append(r.id)

    def node(contact_id: int, depth: int, seen: set[int]) -> OrgNode:
        r = info[contact_id]
        result = OrgNode(r.id, r.display_name, r.title, r.team)
        if depth < MAX_DEPTH:
            for child in sorted(
                children.get(contact_id, []), key=lambda c: info[c].display_name.lower()
            ):
                if child not in seen:  # cycle guard; the service layer prevents cycles anyway
                    result.children.append(node(child, depth + 1, seen | {child}))
        return result

    if focus_id is not None and focus_id in info:
        chain: list[OrgNode] = []
        current = info[focus_id].manager_id
        seen = {focus_id}
        while current in info and current not in seen and len(chain) < MAX_DEPTH:
            r = info[current]
            chain.insert(0, OrgNode(r.id, r.display_name, r.title, r.team))
            seen.add(current)
            current = r.manager_id
        return OrgView(chain, [node(focus_id, 0, {focus_id})], focus_id, 0)

    tops = [r.id for r in rows if r.manager_id not in info and children.get(r.id)]
    roots = [node(t, 0, {t}) for t in tops]
    roots.sort(key=lambda n: (-n.total_reports, n.name.lower()))
    unplaced = sum(1 for r in rows if r.manager_id not in info and not children.get(r.id))
    return OrgView([], roots, None, unplaced)
