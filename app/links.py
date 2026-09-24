"""Communication links shown on contact cards (C-04, M-04, ADR-0007).

Pure functions — no database access — so they are easy to unit test.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import quote

import phonenumbers

TEAMS_CHAT_URL = "https://teams.microsoft.com/l/chat/0/0?users={users}"


def teams_chat_url(emails: Sequence[str]) -> str | None:
    """Teams chat deep link for one or more people (group chat when several)."""
    users = [e.strip() for e in emails if e and e.strip()]
    if not users:
        return None
    return TEAMS_CHAT_URL.format(users=",".join(quote(u, safe="@") for u in users))


def contact_teams_url(explicit_url: str | None, primary_email: str | None) -> str | None:
    """Stored Teams link if present, otherwise one generated from the primary email."""
    if explicit_url:
        return explicit_url
    return teams_chat_url([primary_email]) if primary_email else None


def mailto_url(emails: Sequence[str], cc: Sequence[str] = ()) -> str | None:
    to = [e for e in emails if e]
    if not to:
        return None
    url = "mailto:" + ",".join(quote(e, safe="@") for e in to)
    cc = [e for e in cc if e]
    if cc:
        url += "?cc=" + ",".join(quote(e, safe="@") for e in cc)
    return url


def tel_url(number: str) -> str:
    """``tel:`` link keeping only digits and a leading plus sign."""
    cleaned = re.sub(r"[^\d+]", "", number)
    if cleaned.count("+") > 1 or "+" in cleaned[1:]:
        cleaned = "+" + cleaned.replace("+", "")
    return "tel:" + cleaned


def normalize_phone(raw: str, region: str) -> str:
    """Return E.164 (``+14045550100``) when the number parses, else the trimmed input."""
    text = raw.strip()
    try:
        parsed = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return text
    if phonenumbers.is_valid_number(parsed):
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return text


def display_phone(number: str) -> str:
    """Human-friendly format for E.164 numbers; other values are shown as stored."""
    if not number.startswith("+"):
        return number
    try:
        parsed = phonenumbers.parse(number, None)
    except phonenumbers.NumberParseException:
        return number
    if not phonenumbers.is_valid_number(parsed):
        return number
    fmt = (
        phonenumbers.PhoneNumberFormat.NATIONAL
        if parsed.country_code == 1
        else phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    return phonenumbers.format_number(parsed, fmt)


def slack_handle_display(handle: str | None) -> str | None:
    if not handle:
        return None
    return handle if handle.startswith("@") else "@" + handle
