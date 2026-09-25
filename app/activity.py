"""Activity log (C-13): dated interaction notes on a contact (ADR-0012)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound
from app.models import ACTIVITY_KINDS, Activity, Contact
from app.search import refresh_search

MAX_SUMMARY = 2000
KIND_LABELS = {
    "meeting": "Meeting",
    "call": "Call",
    "email": "Email",
    "message": "Message",
    "note": "Note",
}


def parse_date(raw: str | None, *, today: date | None = None) -> date:
    """A date from an ``<input type=date>`` value; blank means today."""
    today = today or date.today()
    text = (raw or "").strip()
    if not text:
        return today
    try:
        value = date.fromisoformat(text)
    except ValueError:
        raise ContactError("Enter a date like 2026-09-24", "occurred_on") from None
    if value.year < 1900 or value > today + timedelta(days=366):
        raise ContactError("Date is out of range", "occurred_on")
    return value


def add_activity(
    session: Session,
    contact_id: int,
    *,
    kind: str,
    summary: str,
    occurred_on: date | None = None,
    refresh: bool = True,
) -> Activity:
    if session.get(Contact, contact_id) is None:
        raise ContactNotFound(contact_id)
    if kind not in ACTIVITY_KINDS:
        raise ContactError("Choose meeting, call, email, message or note", "kind")
    text = summary.strip()
    if not text:
        raise ContactError("Write a short note about the interaction", "summary")
    if len(text) > MAX_SUMMARY:
        raise ContactError(f"Keep the note under {MAX_SUMMARY} characters", "summary")
    activity = Activity(
        contact_id=contact_id, kind=kind, summary=text, occurred_on=occurred_on or date.today()
    )
    session.add(activity)
    session.flush()
    contact = session.get(Contact, contact_id)
    if contact is not None:
        session.expire(contact, ["activities"])
    if refresh:
        refresh_search(session, [contact_id])
    return activity


def delete_activity(session: Session, contact_id: int, activity_id: int) -> None:
    activity = session.scalars(
        select(Activity).where(Activity.id == activity_id, Activity.contact_id == contact_id)
    ).one_or_none()
    if activity is None:
        raise ContactNotFound(activity_id)
    session.delete(activity)
    session.flush()
    contact = session.get(Contact, contact_id)
    if contact is not None:
        session.expire(contact, ["activities"])
    refresh_search(session, [contact_id])
