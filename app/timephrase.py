"""Time phrases in the search box (S-10, ADR-0014).

``parse_time_query("who did I meet last week", today)`` finds the period
("last week" → Monday to Sunday of the previous week), activity kinds from verbs
("meet" → meetings), and the words left to search (none here).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

RECENT_DAYS = 30
CONTACTED_CHOICES = (7, 30, 90, 365)  # S-09 filter options, in days
INTERACTION_KINDS = ("meeting", "call", "email", "message")  # notes are not interactions

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_MONTHS["sept"] = 9
_MONTH = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "few": 3,
                 "couple": 2, "couple of": 2}  # fmt: skip
_COUNT = r"(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|few|couple(?: of)?)"
_UNIT = r"(day|week|month|year)s?"

_VERB_KINDS = {
    "met": "meeting", "meet": "meeting", "meeting": "meeting", "meetings": "meeting",
    "called": "call", "phoned": "call", "calls": "call",
    "emailed": "email", "e-mailed": "email", "emails": "email",
    "messaged": "message", "texted": "message", "pinged": "message", "messages": "message",
    "call": "call", "phone": "call", "email": "email", "message": "message", "text": "message",
}  # fmt: skip
_FILLER = {
    "who", "whom", "whose", "what", "which", "that", "have", "has", "had", "i", "ive", "me",
    "my", "we", "our", "us", "did", "do", "does", "done", "been", "was", "were", "is", "are",
    "talk", "talked", "talking", "spoke", "speak", "spoken", "chat", "chatted", "interact",
    "interacted", "interacting", "interaction", "interactions", "contact", "contacted",
    "connected", "reached", "reach", "out", "touch", "in", "with", "to", "about", "the", "a",
    "an", "and", "or", "of", "on", "at", "for", "from", "people", "person", "someone",
    "anyone", "everyone", "everybody", "somebody", "show", "list", "find", "all", "ever",
    "saw", "seen", "see", "heard", "hear", "back", "any", "recent", "latest", "last",
    "lately", "recently", "ve", "s", "d", "ll", "re", "m",
}  # fmt: skip


@dataclass(frozen=True)
class TimeQuery:
    start: date
    end: date
    label: str  # e.g. "recently (last 30 days)"
    phrase: str  # the words as typed, e.g. "recently"
    remainder: str  # the query without the phrase, as typed
    terms: tuple[str, ...]  # words still to search, filler removed
    kinds: tuple[str, ...]  # activity kinds, or () for any interaction


def _fmt(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _span(start: date, end: date) -> str:
    if start == end:
        return _fmt(start)
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day} to {_fmt(end)}"
    return f"{_fmt(start)} to {_fmt(end)}"


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _count(raw: str) -> int:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw, 1)


def _shift_months(d: date, months: int) -> date:
    month_index = d.year * 12 + d.month - 1 - months
    year, month = divmod(month_index, 12)
    day = min(d.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def _rolling(today: date, n: int, unit: str) -> date:
    if unit == "day":
        return today - timedelta(days=n - 1)
    if unit == "week":
        return today - timedelta(days=7 * n - 1)
    if unit == "month":
        return _shift_months(today, n) + timedelta(days=1)
    return _shift_months(today, 12 * n) + timedelta(days=1)


def _period(match: re.Match[str], kind: str, today: date) -> tuple[date, date, str] | None:
    """(start, end, label) for one matched pattern."""
    g = tuple(part.lower() if part else part for part in match.groups())
    if kind == "rolling":
        n, unit = _count(g[0]), g[1]
        start = _rolling(today, n, unit)
        noun = unit if n == 1 else f"{n} {unit}s"
        return start, today, f"in the last {noun}"
    if kind == "rolling1":  # "in the last month" = the last 30 days or so, not the calendar month
        start = _rolling(today, 1, g[0])
        return start, today, f"in the last {g[0]}"
    if kind == "day":
        d = today if g[0] == "today" else today - timedelta(days=1)
        return d, d, g[0]
    if kind == "this_last":
        which, unit = g
        if which == "past":
            n_days = {"week": 7, "month": 30, "quarter": 91, "year": 365}[unit]
            return today - timedelta(days=n_days - 1), today, f"in the past {unit}"
        if unit == "week":
            monday = today - timedelta(days=today.weekday())
            if which == "this":
                return monday, today, "this week"
            return monday - timedelta(days=7), monday - timedelta(days=1), "last week"
        if unit == "month":
            if which == "this":
                return today.replace(day=1), today, "this month"
            prev = today.replace(day=1) - timedelta(days=1)
            start, end = _month_range(prev.year, prev.month)
            return start, end, "last month"
        if unit == "quarter":
            q_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
            if which == "this":
                return q_start, today, "this quarter"
            prev_end = q_start - timedelta(days=1)
            prev_start = date(prev_end.year, 3 * ((prev_end.month - 1) // 3) + 1, 1)
            return prev_start, prev_end, "last quarter"
        if which == "this":
            return date(today.year, 1, 1), today, "this year"
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year"
    if kind == "recent":
        return today - timedelta(days=RECENT_DAYS - 1), today, g[0]
    if kind == "since_iso":
        try:
            start = date.fromisoformat(g[0])
        except ValueError:
            return None
        return (start, today, f"since {_fmt(start)}") if start <= today else None
    if kind == "since_month":
        month = _MONTHS[g[0]]
        day = int(g[1]) if g[1] else 1
        year = int(g[2]) if g[2] else today.year
        try:
            start = date(year, month, day)
        except ValueError:
            return None
        if not g[2] and start > today:
            start = start.replace(year=year - 1)
        return (start, today, f"since {_fmt(start)}") if start <= today else None
    # in/during <month> [year]
    month = _MONTHS[g[0]]
    year = int(g[1]) if g[1] else today.year
    if not g[1] and date(year, month, 1) > today:
        year -= 1
    start, end = _month_range(year, month)
    return start, min(end, today), f"in {calendar.month_name[month]} {year}"


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        ("rolling",
         rf"\b(?:(?:in|over|during|within)\s+)?(?:the\s+)?(?:last|past)\s+{_COUNT}\s+{_UNIT}\b"),
        ("rolling1",
         r"\b(?:in|over|during|within)\s+the\s+(?:last|past)\s+(day|week|month|year)\b"),
        ("this_last", r"\b(this|last|past)\s+(week|month|quarter|year)\b"),
        ("day", r"\b(today|yesterday)\b"),
        ("recent", r"\b(recently|lately|of late)\b"),
        ("since_iso", r"\bsince\s+(\d{4}-\d{2}-\d{2})\b"),
        ("since_month",
         rf"\bsince\s+{_MONTH}(?:\s+(\d{{1,2}})(?:st|nd|rd|th)?)?(?:,?\s+(\d{{4}}))?\b"),
        ("in_month", rf"\b(?:in|during)\s+{_MONTH}(?:,?\s+(\d{{4}}))?\b"),
    )
)  # fmt: skip

_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")


def parse_time_query(q: str, today: date | None = None) -> TimeQuery | None:
    """The first time phrase in ``q`` as a date range, or None when there is none."""
    today = today or date.today()
    found: tuple[re.Match[str], str] | None = None
    for kind, pattern in _PATTERNS:
        match = pattern.search(q)
        if match and (found is None or match.start() < found[0].start()):
            found = (match, kind)
    if found is None:
        return None
    match, kind = found
    period = _period(match, kind, today)
    if period is None:
        return None
    start, end, label = period
    remainder = " ".join((q[: match.start()] + " " + q[match.end() :]).split())
    words = [w.lower().replace("'", "") for w in _WORD.findall(remainder.lower())]
    kinds = sorted({_VERB_KINDS[w] for w in words if w in _VERB_KINDS})
    terms = tuple(w for w in words if w not in _FILLER and w not in _VERB_KINDS)
    if label in {"recently", "lately", "of late"}:
        label = f"{label} (last {RECENT_DAYS} days)"
    elif not label.startswith(("since", "in ")) or label.startswith("in the"):
        label = f"{label} ({_span(start, end)})"
    return TimeQuery(
        start=start,
        end=end,
        label=label,
        phrase=match.group(0).strip(),
        remainder=remainder,
        terms=terms,
        kinds=tuple(kinds),
    )


def contacted_since(days: int, today: date | None = None) -> date:
    """S-09: first day of "contacted in the last N days"."""
    return (today or date.today()) - timedelta(days=days - 1)
