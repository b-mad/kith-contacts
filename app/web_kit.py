"""Keep-in-touch pages and forms (C-15, C-16, S-11, C-17, ADR-0016)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.contacts import ContactError
from app.keep_in_touch import clear_snooze, set_cadence, snooze, snooze_until
from app.web import CsrfChecked, SessionDep, _load, with_notice

router = APIRouter(include_in_schema=False)


def _invalid(session: Session, exc: ContactError) -> HTTPException:
    session.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)


def _back(contact_id: int, notice: str, **params: object) -> Response:
    url = with_notice(f"/contacts/{contact_id}", notice, **params) + "#kit-h"
    return RedirectResponse(url, status.HTTP_303_SEE_OTHER)


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
    form = await request.form()
    try:
        until = snooze_until(
            str(form.get("snooze", "")), str(form.get("until", "")), today=date.today()
        )
        snooze(session, contact, until)
    except ContactError as exc:
        raise _invalid(session, exc) from None
    session.commit()
    return _back(contact_id, "snoozed", name=f"{until.strftime('%b')} {until.day}, {until.year}")


@router.post("/contacts/{contact_id}/keep-in-touch/unsnooze", dependencies=CsrfChecked)
def cancel_snooze(contact_id: int, session: SessionDep) -> Response:
    clear_snooze(session, _load(session, contact_id))
    session.commit()
    return _back(contact_id, "unsnoozed")
