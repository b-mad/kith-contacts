"""Manager tiers (S-18, ADR-0032): where a manager sits in a reporting line.

The top of a reporting line is **L0**; the people who report to them and manage others are L1,
and so on down. A *manager* is an active person with at least one active direct report. The
lines are the same ones the org chart draws (ADR-0030): someone with no active manager (none
set, archived, or private while presenting) heads a line of their own, so there can be several
L0s. People who manage nobody have no tier; the filter calls them "Not a manager".

The tiers are worked out in the database with a recursive query, so they follow the privacy
filters that apply to every ORM read (ADR-0016) and need no stored column to keep in step.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from sqlalchemy import CTE, Integer, Select, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Contact
from app.privacy import presenting

#: The filter value for people who manage nobody (``?tier=none``).
NOT_A_MANAGER: Final = "none"
MAX_TIER: Final = 50  # a guard for the recursive query; real organizations are far shallower


def tier_label(tier: int | str) -> str:
    """'L0', 'L1', … for a tier; 'Not a manager' for the no-tier option."""
    return "Not a manager" if tier == NOT_A_MANAGER else f"L{tier}"


def _lines() -> CTE:
    """Every active person with their depth in the reporting line (0 = top of a line)."""
    boss = aliased(Contact)
    line = (
        select(Contact.id.label("id"), literal(0, Integer).label("tier"))
        .where(
            Contact.archived_at.is_(None),
            or_(
                Contact.manager_id.is_(None),
                Contact.manager_id.not_in(select(boss.id).where(boss.archived_at.is_(None))),
            ),
        )
        .cte("manager_lines", recursive=True)
    )
    report = aliased(Contact)
    return line.union_all(
        select(report.id, (line.c.tier + 1).label("tier")).where(
            report.manager_id == line.c.id, report.archived_at.is_(None), line.c.tier < MAX_TIER
        )
    )


def _bosses() -> Select[tuple[int | None]]:
    """Ids of everyone with at least one active direct report."""
    report = aliased(Contact)
    return select(report.manager_id).where(
        report.archived_at.is_(None), report.manager_id.is_not(None)
    )


def manager_rows() -> tuple[CTE, Select[tuple[int, int]]]:
    """The recursive query and a select of ``(id, tier)`` for everyone who manages somebody.

    Both come from one call so a statement holds the recursive query only once.
    """
    lines = _lines()
    return lines, select(lines.c.id, lines.c.tier).where(lines.c.id.in_(_bosses()))


def manager_tiers(session: Session, ids: Iterable[int] | None = None) -> dict[int, int]:
    """``{person id: tier}`` for managers (all of them, or just those among ``ids``)."""
    lines, stmt = manager_rows()
    if ids is not None:
        wanted = list(ids)
        if not wanted:
            return {}
        stmt = stmt.where(lines.c.id.in_(wanted))
    return {int(i): int(t) for i, t in session.execute(stmt)}


def tier_options(session: Session) -> list[int]:
    """The tiers that have at least one manager, top first."""
    return sorted(set(manager_tiers(session).values()))


def shown_tiers(session: Session, ids: Iterable[int]) -> dict[int, int]:
    """Tiers to print next to people. While presenting, "names and companies only" shows none."""
    p = presenting()
    if p is not None and p.names_only:
        return {}
    return manager_tiers(session, ids)


def parse_tiers(values: Sequence[str], options: Sequence[int]) -> tuple[tuple[int, ...], bool]:
    """Turn the ticked boxes into ``(tiers, not_a_manager)``.

    Ticking every option (what the screen starts with) or none means no filter, so it returns
    ``((), False)``. Tiers come back sorted without repeats; junk values are ignored.
    """
    tiers: set[int] = set()
    non_managers = False
    for raw in values:
        value = raw.strip()
        if value == NOT_A_MANAGER:
            non_managers = True
        elif value.isdigit() and int(value) <= MAX_TIER:
            tiers.add(int(value))
    if non_managers and tiers.issuperset(options):
        return (), False
    return tuple(sorted(tiers)), non_managers
