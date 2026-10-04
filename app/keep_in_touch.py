"""Keep-in-touch reminders (C-15, C-16, S-11, ADR-0016).

A contact may have a cadence (every 2 weeks, month, 3 months, 6 months or year). The
reminder is due one cadence after the last interaction — a meeting, call, email or message;
notes don't count (as S-09) — or after the day the cadence was set when nothing is logged.
A snooze moves the current reminder to a later date; logging an interaction clears it.

The due date is never stored: ``due_column()`` computes it in SQL for lists and sorting,
and ``due_date()`` computes the same value in Python for a single card. Months are
calendar months clamped to the month's end (Jan 31 + 1 month = Feb 28/29), which is also
what PostgreSQL's ``date + interval '1 month'`` does.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Literal, get_args

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from app.birthdays import UPCOMING_DAYS, Birthday, upcoming_keys
from app.contacts import ContactError
from app.models import Activity, Contact
from app.timephrase import INTERACTION_KINDS

Interval = Literal["2w", "1m", "3m", "6m", "1y"]
INTERVALS: Final[tuple[str, ...]] = get_args(Interval)
INTERVAL_LABELS: Final[dict[str, str]] = {
    "2w": "Every 2 weeks",
    "1m": "Every month",
    "3m": "Every 3 months",
    "6m": "Every 6 months",
    "1y": "Every year",
}
_MONTHS: Final[dict[str, int]] = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}
_DAYS: Final[dict[str, int]] = {"2w": 14}

SNOOZE_CHOICES: Final[dict[str, str]] = {"1w": "1 week", "2w": "2 weeks", "1m": "1 month"}
DUE_SOON_DAYS: Final = 7  # S-11: "due this week"
MAX_SNOOZE_DAYS: Final = 366


def add_interval(start: date, interval: str) -> date:
    """``start`` plus one cadence; months are calendar months clamped to the month's end."""
    if interval in _DAYS:
        return start + timedelta(days=_DAYS[interval])
    index = start.month - 1 + _MONTHS[interval]
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def due_date(
    interval: str | None,
    *,
    last_interaction: date | None,
    started_on: date | None,
    snoozed_until: date | None,
) -> date | None:
    """When the next reminder is due, or ``None`` when keep-in-touch is off."""
    base = last_interaction or started_on
    if interval is None or base is None:
        return None
    due = add_interval(base, interval)
    return max(due, snoozed_until) if snoozed_until else due


def last_interaction_column() -> Any:
    """Correlated subquery: the contact's newest meeting, call, email or message."""
    return (
        select(func.max(Activity.occurred_on))
        .where(Activity.contact_id == Contact.id, Activity.kind.in_(INTERACTION_KINDS))
        .scalar_subquery()
    )


def due_column() -> Any:
    """SQL twin of ``due_date``: NULL when keep-in-touch is off."""
    base = func.coalesce(last_interaction_column(), Contact.kit_started_on)
    months = case(_MONTHS, value=Contact.kit_interval, else_=0)
    days = case(_DAYS, value=Contact.kit_interval, else_=0)
    due = cast(base + func.make_interval(0, months, 0, days), Date)
    # GREATEST ignores NULLs, so an unset snooze leaves the due date alone.
    return case(
        (Contact.kit_interval.is_(None), None), else_=func.greatest(due, Contact.kit_snoozed_until)
    )


def _format(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


@dataclass(frozen=True)
class Reminder:
    """A contact's keep-in-touch state on a given day."""

    interval: str
    due: date
    today: date
    last_interaction: date | None
    snoozed_until: date | None

    @property
    def days(self) -> int:
        """Days until due; negative when overdue."""
        return (self.due - self.today).days

    @property
    def state(self) -> str:
        if self.days < 0:
            return "overdue"
        if self.days == 0:
            return "today"
        return "soon" if self.days <= DUE_SOON_DAYS else "later"

    @property
    def label(self) -> str:
        return INTERVAL_LABELS[self.interval]

    @property
    def describe(self) -> str:
        if self.days < 0:
            return f"Overdue by {_days(-self.days)}"
        if self.days == 0:
            return "Due today"
        return f"Due in {_days(self.days)}"

    @property
    def due_text(self) -> str:
        return _format(self.due)

    @property
    def snoozed_text(self) -> str | None:
        return _format(self.snoozed_until) if self.snoozed_until else None


def last_interaction(session: Session, contact_id: int) -> date | None:
    result: date | None = session.scalar(
        select(func.max(Activity.occurred_on)).where(
            Activity.contact_id == contact_id, Activity.kind.in_(INTERACTION_KINDS)
        )
    )
    return result


def reminder_for(session: Session, contact: Contact, *, today: date) -> Reminder | None:
    if contact.kit_interval is None:
        return None
    last = last_interaction(session, contact.id)
    due = due_date(
        contact.kit_interval,
        last_interaction=last,
        started_on=contact.kit_started_on,
        snoozed_until=contact.kit_snoozed_until,
    )
    if due is None:
        return None
    return Reminder(contact.kit_interval, due, today, last, contact.kit_snoozed_until)


def set_cadence(
    session: Session, contacts: Iterable[Contact], interval: str | None, *, today: date
) -> int:
    """C-15: turn keep-in-touch on, change it, or turn it off (``None``). Returns the count."""
    if interval is not None and interval not in INTERVALS:
        raise ContactError("Choose how often to keep in touch", "interval")
    count = 0
    for contact in contacts:
        if interval is None:
            contact.kit_interval = contact.kit_started_on = contact.kit_snoozed_until = None
        else:
            if contact.kit_interval is None:
                contact.kit_started_on = today  # the clock starts now if nothing is logged
            contact.kit_interval = interval
            contact.kit_snoozed_until = None
        count += 1
    session.flush()
    return count


def snooze_until(choice: str, raw_date: str, *, today: date) -> date:
    """C-16: a snooze target from a preset (1w, 2w, 1m) or an explicit date."""
    if raw_date.strip():
        try:
            until = date.fromisoformat(raw_date.strip())
        except ValueError:
            raise ContactError("Enter a date like 2026-11-01", "until") from None
    elif choice == "1w":
        until = today + timedelta(days=7)
    elif choice == "2w":
        until = today + timedelta(days=14)
    elif choice == "1m":
        until = add_interval(today, "1m")
    else:
        raise ContactError("Choose how long to snooze", "snooze")
    if until <= today:
        raise ContactError("Snooze to a date after today", "until")
    if until > today + timedelta(days=MAX_SNOOZE_DAYS):
        raise ContactError("Snooze for a year at most", "until")
    return until


def snooze(session: Session, contact: Contact, until: date) -> None:
    """C-16: move only the current reminder; logging an interaction clears it."""
    if contact.kit_interval is None:
        raise ContactError("Turn on keep in touch first", "interval")
    contact.kit_snoozed_until = until
    session.flush()


def clear_snooze(session: Session, contact: Contact) -> None:
    contact.kit_snoozed_until = None
    session.flush()


def _due_by(today: date, within_days: int) -> Any:
    return [
        Contact.kit_interval.is_not(None),
        Contact.archived_at.is_(None),
        due_column() <= today + timedelta(days=within_days),
    ]


def due_reminders(
    session: Session,
    *,
    today: date,
    within_days: int = DUE_SOON_DAYS,
    limit: int | None = None,
) -> list[tuple[Contact, Reminder]]:
    """S-11: people due within ``within_days`` (overdue included), most overdue first."""
    due = due_column()
    last = last_interaction_column()
    from app.search import _with_details  # app.search imports this module lazily

    rows = session.execute(
        _with_details(select(Contact))  # the page renders every row: load details in bulk
        .add_columns(due, last)
        .where(*_due_by(today, within_days))
        .order_by(due, func.lower(Contact.display_name))
        .limit(limit)
    ).all()
    result = []
    for contact, due_on, last_on in rows:
        if contact.kit_interval is None:  # pragma: no cover - excluded by the query
            continue
        reminder = Reminder(contact.kit_interval, due_on, today, last_on, contact.kit_snoozed_until)
        result.append((contact, reminder))
    return result


@dataclass(frozen=True)
class BirthdaySoon:
    """C-21: one birthday coming up."""

    on: date
    days: int  # 0 = today
    turns: int | None  # the age they turn, when the year is known

    @property
    def when(self) -> str:
        if self.days == 0:
            return "Today"
        if self.days == 1:
            return "Tomorrow"
        return f"In {self.days} days"

    @property
    def date_text(self) -> str:
        return f"{self.on.strftime('%A')}, {calendar.month_name[self.on.month]} {self.on.day}"


def upcoming_birthdays(
    session: Session, *, today: date, days: int = UPCOMING_DAYS
) -> list[tuple[Contact, BirthdaySoon]]:
    """C-21: active contacts whose birthday falls in the next ``days`` days, soonest first."""
    from app.search import _with_details  # app.search imports this module lazily

    contacts = session.scalars(
        _with_details(select(Contact)).where(
            Contact.archived_at.is_(None),
            func.right(Contact.birthday, 5).in_(upcoming_keys(today, days)),
        )
    ).all()
    found = []
    for contact in contacts:
        if contact.birthday is None:  # pragma: no cover - excluded by the query
            continue
        birthday = Birthday.of(contact.birthday)
        on = birthday.next_on(today)
        if (on - today).days < days:
            found.append((contact, BirthdaySoon(on, (on - today).days, birthday.age_on(on))))
    return sorted(found, key=lambda pair: (pair[1].on, pair[0].display_name.lower()))


def count_due(session: Session, *, today: date, within_days: int = DUE_SOON_DAYS) -> int:
    """S-11: the number shown beside Reconnect in the navigation."""
    count: int = (
        session.scalar(
            select(func.count()).select_from(Contact).where(*_due_by(today, within_days))
        )
        or 0
    )
    return count


def next_reminder(session: Session, *, today: date) -> tuple[Contact, Reminder] | None:
    """The soonest reminder after the due window, for an empty Reconnect page."""
    rows = due_reminders(session, today=today, within_days=MAX_SNOOZE_DAYS * 2)
    return next(((c, r) for c, r in rows if r.days > DUE_SOON_DAYS), None)


def overdue_days(session: Session, contact_ids: Iterable[int], *, today: date) -> dict[int, int]:
    """S-11: days overdue for each listed contact whose reminder is past due."""
    ids = sorted(set(contact_ids))
    if not ids:
        return {}
    due = due_column()
    rows = session.execute(
        select(Contact.id, due).where(Contact.id.in_(ids), Contact.kit_interval.is_not(None))
    ).tuples()
    return {cid: (today - day).days for cid, day in rows if day is not None and day < today}
