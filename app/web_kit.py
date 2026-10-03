"""Keep-in-touch pages and forms (C-15, C-16, S-11, C-17, ADR-0016)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import add_activity
from app.contacts import ContactError, to_out
from app.keep_in_touch import (
    Reminder,
    clear_snooze,
    count_due,
    due_reminders,
    next_reminder,
    set_cadence,
    snooze,
    snooze_until,
)
from app.models import Contact
from app.search import last_interactions, refresh_search
from app.web import (
    CsrfChecked,
    SessionDep,
    _interaction,
    _load,
    _render,
    notice_text,
    safe_next,
    selected_ids,
    undo_params,
    with_notice,
)

router = APIRouter(include_in_schema=False)
RECONNECT_LIMIT = 100


def _invalid(session: Session, exc: ContactError) -> HTTPException:
    session.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)


def _back(contact_id: int, notice: str, next_: object = None, **params: object) -> Response:
    """Back to the card's Keep in touch section, or to ``next`` (e.g. the Reconnect page)."""
    if next_:
        target = safe_next(next_, "/reconnect")
        return RedirectResponse(with_notice(target, notice, **params), status.HTTP_303_SEE_OTHER)
    url = with_notice(f"/contacts/{contact_id}", notice, **params) + "#kit-h"
    return RedirectResponse(url, status.HTTP_303_SEE_OTHER)


@router.get("/reconnect", response_class=HTMLResponse)
def reconnect(request: Request, session: SessionDep) -> HTMLResponse:
    """S-11: who is overdue, then who is due this week."""
    today = date.today()
    # N-03: the page stays quick however many are due; the rest are one click away.
    due = due_reminders(session, today=today, limit=RECONNECT_LIMIT)
    total = count_due(session, today=today) if len(due) == RECONNECT_LIMIT else len(due)
    last = last_interactions(session, [c.id for c, _ in due])

    def row(contact: Contact, reminder: Reminder) -> dict[str, Any]:
        found = last.get(contact.id)
        return {
            "c": to_out(contact),
            "reminder": reminder,
            "last": _interaction(found) if found else None,
        }

    overdue = [row(c, r) for c, r in due if r.days < 0]
    this_week = [row(c, r) for c, r in due if r.days >= 0]
    upcoming = next_reminder(session, today=today) if not due else None
    return _render(
        request,
        "reconnect/index.html",
        {
            "overdue": overdue,
            "this_week": this_week,
            "upcoming": upcoming,
            "shown": len(due),
            "total": total,
            "notice": notice_text(request),
        },
    )


@router.post("/selection/keep-in-touch", dependencies=CsrfChecked)
async def keep_in_touch_selection(request: Request, session: SessionDep) -> Response:
    """C-15: set (or turn off) a cadence for every selected contact."""
    form = await request.form()
    ids = selected_ids(form)
    back = safe_next(form.get("next"))
    if not ids:
        return RedirectResponse(back, status.HTTP_303_SEE_OTHER)
    interval = str(form.get("interval", "")).strip() or None
    contacts = session.scalars(select(Contact).where(Contact.id.in_(ids))).all()
    try:
        count = set_cadence(session, contacts, interval, today=date.today())
    except ContactError as exc:
        raise _invalid(session, exc) from None
    session.commit()
    notice = "kit_bulk" if interval else "kit_bulk_off"
    return RedirectResponse(with_notice(back, notice, n=count), status.HTTP_303_SEE_OTHER)


@router.post("/selection/log", dependencies=CsrfChecked)
async def log_selection(request: Request, session: SessionDep) -> Response:
    """C-17: after Compose for a selection, log that email (or Teams message) for each person."""
    form = await request.form()
    ids = selected_ids(form)
    back = safe_next(form.get("next"))
    kind = str(form.get("kind", ""))
    if kind not in {"email", "message"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Log an email or a message")
    summary = str(form.get("summary", "")).strip() or "Emailed"
    known = set(session.scalars(select(Contact.id).where(Contact.id.in_(ids))))
    try:
        for contact_id in sorted(known):
            add_activity(session, contact_id, kind=kind, summary=summary, refresh=False)
    except ContactError as exc:
        raise _invalid(session, exc) from None
    refresh_search(session, known)
    session.commit()
    return RedirectResponse(
        with_notice(back, "logged_many", n=len(known)), status.HTTP_303_SEE_OTHER
    )


@router.post("/contacts/{contact_id}/keep-in-touch", dependencies=CsrfChecked)
async def save_cadence(request: Request, contact_id: int, session: SessionDep) -> Response:
    """C-15: set, change or turn off how often to keep in touch."""
    contact = _load(session, contact_id)
    interval = str((await request.form()).get("interval", "")).strip() or None
    try:
        set_cadence(session, [contact], interval, today=date.today())
    except ContactError as exc:
        raise _invalid(session, exc) from None
    session.commit()
    return _back(contact_id, "kit_saved" if interval else "kit_off")


@router.post("/contacts/{contact_id}/keep-in-touch/snooze", dependencies=CsrfChecked)
async def snooze_reminder(request: Request, contact_id: int, session: SessionDep) -> Response:
    """C-16: move the current reminder to a later date."""
    contact = _load(session, contact_id)
    before = contact.kit_snoozed_until  # for Undo (S-11)
    form = await request.form()
    try:
        until = snooze_until(
            str(form.get("snooze", "")), str(form.get("until", "")), today=date.today()
        )
        snooze(session, contact, until)
    except ContactError as exc:
        raise _invalid(session, exc) from None
    session.commit()
    when = f"{until.strftime('%b')} {until.day}, {until.year}"
    return _back(
        contact_id, "snoozed", form.get("next"), name=when, **undo_params(contact_id, before)
    )


@router.post("/contacts/{contact_id}/keep-in-touch/unsnooze", dependencies=CsrfChecked)
def cancel_snooze(contact_id: int, session: SessionDep) -> Response:
    clear_snooze(session, _load(session, contact_id))
    session.commit()
    return _back(contact_id, "unsnoozed")
