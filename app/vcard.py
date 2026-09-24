"""vCard 3.0 export and a tolerant 2.1/3.0/4.0 parser (D-02)."""

from __future__ import annotations

import quopri
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models import Contact

# ---------------------------------------------------------------- writing


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold at 75 octets as RFC 6350 requires, without splitting UTF-8 characters."""
    out: list[str] = []
    current = ""
    for ch in line:
        limit = 75 if not out else 74
        if len((current + ch).encode()) > limit:
            out.append(current)
            current = ""
        current += ch
    out.append(current)
    return "\r\n ".join(out)


_TEL_TYPES = {"mobile": "CELL", "cell": "CELL", "work": "WORK", "home": "HOME", "fax": "FAX"}


def to_vcard(contact: Contact) -> str:
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_escape(contact.display_name)}"]
    lines.append(
        "N:"
        + ";".join(_escape(p or "") for p in (contact.last_name, contact.first_name, "", "", ""))
    )
    if contact.nickname:
        lines.append(f"NICKNAME:{_escape(contact.nickname)}")
    if contact.company or contact.department:
        lines.append(f"ORG:{_escape(contact.company or '')};{_escape(contact.department or '')}")
    if contact.title:
        lines.append(f"TITLE:{_escape(contact.title)}")
    for email in sorted(contact.emails, key=lambda e: not e.is_primary):
        kinds = ["INTERNET"]
        if email.label and email.label.lower() in {"work", "home"}:
            kinds.append(email.label.upper())
        if email.is_primary:
            kinds.append("PREF")
        lines.append(f"EMAIL;TYPE={','.join(kinds)}:{email.email}")
    for phone in contact.phones:
        kind = _TEL_TYPES.get((phone.label or "").lower(), "VOICE")
        lines.append(f"TEL;TYPE={kind}:{phone.number}")
    note = "\n\n".join(
        part
        for part in (
            f"Works on: {contact.works_on}" if contact.works_on else "",
            f"Team: {contact.team}" if contact.team else "",
            contact.notes or "",
        )
        if part
    )
    if note:
        lines.append(f"NOTE:{_escape(note)}")
    if contact.tags:
        lines.append("CATEGORIES:" + ",".join(_escape(t.name) for t in contact.tags))
    stamp = (contact.updated_at or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines += [f"REV:{stamp}", "END:VCARD"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def to_vcards(contacts: Iterable[Contact]) -> str:
    return "".join(to_vcard(c) for c in contacts)


# ---------------------------------------------------------------- reading


@dataclass
class ParsedCard:
    display_name: str = ""
    first_name: str = ""
    last_name: str = ""
    nickname: str = ""
    company: str = ""
    department: str = ""
    title: str = ""
    notes: str = ""
    emails: list[tuple[str, str, bool]] = field(default_factory=list)  # (email, label, pref)
    phones: list[tuple[str, str]] = field(default_factory=list)  # (number, label)
    tags: list[str] = field(default_factory=list)


def _unescape(value: str) -> str:
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _split(value: str, sep: str) -> list[str]:
    """Split on unescaped separators."""
    return [_unescape(p) for p in re.split(rf"(?<!\\){re.escape(sep)}", value)]


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in {" ", "\t"} and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    # vCard 2.1 quoted-printable soft line breaks: "=" at end of line continues it
    merged: list[str] = []
    for line in lines:
        if merged and merged[-1].endswith("=") and "QUOTED-PRINTABLE" in merged[-1].upper():
            merged[-1] = merged[-1][:-1] + line
        else:
            merged.append(line)
    return merged


def _params(spec: str) -> tuple[str, dict[str, list[str]]]:
    parts = spec.split(";")
    name = parts[0].split(".")[-1].upper()  # drop group prefixes like "item1."
    params: dict[str, list[str]] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            params.setdefault(key.upper(), []).extend(
                v.strip('"').upper() for v in value.split(",")
            )
        else:  # vCard 2.1 bare types: TEL;CELL:...
            params.setdefault("TYPE", []).append(part.upper())
    return name, params


def _label(types: list[str], ignore: set[str]) -> str:
    wanted = [t.lower() for t in types if t not in ignore]
    if "cell" in wanted:
        return "mobile"
    return wanted[0] if wanted else ""


def parse_vcards(text: str) -> list[ParsedCard]:
    cards: list[ParsedCard] = []
    card: ParsedCard | None = None
    for line in _unfold(text):
        if ":" not in line:
            continue
        spec, value = line.split(":", 1)
        name, params = _params(spec)
        if "QUOTED-PRINTABLE" in params.get("ENCODING", []):
            value = quopri.decodestring(value.encode()).decode("utf-8", errors="replace")
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            card = ParsedCard()
            continue
        if card is None:
            continue
        if name == "END" and value.strip().upper() == "VCARD":
            if not card.display_name:
                card.display_name = " ".join(p for p in (card.first_name, card.last_name) if p)
            if card.display_name or card.emails:
                cards.append(card)
            card = None
        elif name == "FN":
            card.display_name = _unescape(value).strip()
        elif name == "N":
            parts = [*_split(value, ";"), "", ""]
            card.last_name, card.first_name = parts[0].strip(), parts[1].strip()
        elif name == "NICKNAME":
            card.nickname = _split(value, ",")[0].strip()
        elif name == "ORG":
            parts = [*_split(value, ";"), ""]
            card.company, card.department = parts[0].strip(), parts[1].strip()
        elif name == "TITLE":
            card.title = _unescape(value).strip()
        elif name == "NOTE":
            card.notes = _unescape(value).strip()
        elif name == "EMAIL" and value.strip():
            types = params.get("TYPE", [])
            pref = "PREF" in types or "PREF" in params
            card.emails.append((value.strip(), _label(types, {"INTERNET", "PREF", "X400"}), pref))
        elif name == "TEL" and value.strip():
            number = value.strip().removeprefix("tel:")
            card.phones.append((number, _label(params.get("TYPE", []), {"VOICE", "PREF"})))
        elif name == "CATEGORIES":
            card.tags.extend(t.strip() for t in _split(value, ",") if t.strip())
    return cards
