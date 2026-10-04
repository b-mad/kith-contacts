"""Birthdays: parsing typed and imported dates, display, and what's coming up
(C-20, C-21, ADR-0022). Pure functions.

A birthday is stored as ``YYYY-MM-DD`` or, when the year is unknown, ``--MM-DD``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

PATTERN = r"^(\d{4}-|--)\d{2}-\d{2}$"  # also the database CHECK constraint
UPCOMING_DAYS = 14  # C-21: Reconnect looks two weeks ahead

# Regions that write dates month first (3/14/1980); everyone else reads 14/3/1980.
MONTH_FIRST_REGIONS = frozenset({"US", "PH", "FM", "MH", "PW"})
_NO_YEAR = {1604, 1900, 0}  # Apple's "year unknown" marker, Outlook's 1900, and none

_MONTHS = {
    name.lower(): number
    for number in range(1, 13)
    for name in (calendar.month_name[number], calendar.month_abbr[number])
}
_MONTHS["sept"] = 9


def month_first(region: str) -> bool:
    return region.upper() in MONTH_FIRST_REGIONS


def _canonical(year: int | None, month: int, day: int) -> str:
    try:
        date(2000 if year is None else year, month, day)  # 2000 is a leap year: 29 Feb is fine
    except ValueError:
        raise ValueError("not a real date") from None
    if year is not None and not 1800 < year <= date.today().year:
        raise ValueError("the year looks wrong")
    return f"{year:04d}-{month:02d}-{day:02d}" if year is not None else f"--{month:02d}-{day:02d}"


def _year(text: str | None) -> int | None:
    if not text:
        return None
    value = int(text)
    if len(text) == 2:  # 80 -> 1980, 05 -> 2005
        value += 2000 if value <= date.today().year % 100 else 1900
    return None if value in _NO_YEAR else value


def parse_birthday(text: str, *, month_first: bool = True) -> str | None:
    """A birthday as typed or exported, in canonical form; None when it says "no birthday".

    Raises ValueError for text that isn't a date.
    """
    # A leading ' is this app's CSV formula guard (D-03) or a spreadsheet's text marker.
    raw = " ".join(text.strip().lstrip("'").split())
    raw = re.sub(r"T.*$", "", raw)  # vCard: 1980-03-14T00:00:00Z
    if not raw or raw in {"0/0/00", "00/00/0000", "0000-00-00", "--"}:
        return None
    if m := re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", raw):  # 1980-03-14, 19800314
        return _canonical(_year(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"--(\d{2})-?(\d{2})", raw):  # --03-14, --0314
        return _canonical(None, int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", raw):  # 1980/3/14
        return _canonical(_year(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?", raw):
        first, second = int(m[1]), int(m[2])
        month, day = (first, second) if month_first else (second, first)
        if month == 0 and day == 0:
            return None
        return _canonical(_year(m[3]), month, day)
    words = re.findall(r"[A-Za-z]+|\d+", raw)
    month_words = [w for w in words if w.lower() in _MONTHS]
    numbers = [w for w in words if w.isdigit()]
    if len(month_words) == 1 and 1 <= len(numbers) <= 2:  # March 14, 14 Mar 1980
        day_text = next((n for n in numbers if len(n) <= 2), None)
        if day_text is None:  # "March 1980": no day
            raise ValueError("needs a day")
        year_text = next((n for n in numbers if n is not day_text), None)
        return _canonical(_year(year_text), _MONTHS[month_words[0].lower()], int(day_text))
    raise ValueError("not a date")


@dataclass(frozen=True)
class Birthday:
    year: int | None
    month: int
    day: int

    @classmethod
    def of(cls, value: str) -> Birthday:
        """From the stored form."""
        year, month, day = (
            value.rsplit("-", 2) if not value.startswith("--") else ("", *value[2:].split("-"))
        )
        return cls(int(year) if year else None, int(month), int(day))

    def text(self) -> str:
        """'March 14, 1980' or 'March 14'."""
        base = f"{calendar.month_name[self.month]} {self.day}"
        return f"{base}, {self.year}" if self.year else base

    def next_on(self, today: date) -> date:
        """The next birthday on or after ``today``; 29 Feb is kept on 28 Feb in other years."""
        for year in (today.year, today.year + 1):
            day = self.day
            if self.month == 2 and day == 29 and not calendar.isleap(year):
                day = 28
            when = date(year, self.month, day)
            if when >= today:
                return when
        raise AssertionError("unreachable")  # pragma: no cover

    def age_on(self, when: date) -> int | None:
        if self.year is None:
            return None
        return when.year - self.year - ((when.month, when.day) < (self.month, self.day))


def upcoming_keys(today: date, days: int = UPCOMING_DAYS) -> list[str]:
    """``MM-DD`` endings to look for over the next ``days`` days (29 Feb in other years too)."""
    keys: list[str] = []
    for offset in range(days):
        when = today + timedelta(days=offset)
        keys.append(f"{when.month:02d}-{when.day:02d}")
        if when.month == 2 and when.day == 28 and not calendar.isleap(when.year):
            keys.append("02-29")
    return keys


def describe(value: str, today: date) -> str:
    """Card text: 'March 14, 1980 · age 46' or 'March 14'."""
    birthday = Birthday.of(value)
    age = birthday.age_on(today)
    return birthday.text() + (f" · age {age}" if age is not None else "")
