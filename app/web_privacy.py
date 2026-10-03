"""Presenting mode: the toggle, Settings > Privacy and presenting, private flags (P-01 to P-07).

The rules live in ``app/privacy.py`` (ADR-0016); these routes only change the cookie and
the stored settings.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Contact, ContactList, CustomField, ListMember, Tag, contact_tag
from app.privacy import (
    CATEGORIES,
    CATEGORY_CHOICES,
    COOKIE,
    LOOK_CHOICES,
    OFF_CHOICES,
    OFF_SECONDS,
    VIEW_CHOICES,
    PrivacySettings,
    current_privacy,
    is_blocked,
    load_privacy,
    parse_names,
    save_privacy,
)
from app.web import (
    CsrfChecked,
    SessionDep,
    _load,
    _render,
    notice_text,
    safe_next,
    with_notice,
)

router = APIRouter(include_in_schema=False)

_CARD = re.compile(r"^/contacts/(\d+)")
ITEM_KINDS = ("tag", "list", "field", "contact")


def set_presenting_cookie(response: Response, on: bool, settings: PrivacySettings) -> None:
    """P-01: one cookie for every instance on this host (cookies ignore the port).

    "Off" is stored too (as a session cookie), so an instance that starts presenting
    (P-07) doesn't switch it straight back on until the browser restarts.
    """
    response.set_cookie(
        COOKIE,
        "1" if on else "0",
        max_age=OFF_SECONDS[settings.off] if on else None,
        httponly=True,
        samesite="strict",
        path="/",
    )


def _landing(session: Session, target: str) -> str:
    """Where to go after turning presenting on: not a page it would hide."""
    if is_blocked(target.split("?", 1)[0]):
        return "/"
    card = _CARD.match(target)
    if card:
        private = session.scalar(
            select(Contact.is_private)
            .where(Contact.id == int(card.group(1)))
            .execution_options(include_private=True)
        )
        if private:
            return "/"
    return target


@router.post("/presenting", dependencies=CsrfChecked)
async def toggle_presenting(request: Request, session: SessionDep) -> Response:
    """P-01: the header button and ⇧P post here."""
    form = await request.form()
    on = form.get("on") == "1"
    target = safe_next(form.get("next"), "/")
    if on:
        target = _landing(session, target)
    response = RedirectResponse(target, status.HTTP_303_SEE_OTHER)
    set_presenting_cookie(response, on, current_privacy(request.app.state))
    return response


# ---------------------------------------------------------------- settings (P-03, P-07)


def _items(session: Session, settings: PrivacySettings) -> dict[str, Any]:
    everything = {"include_private": True}
    tag_rows = session.execute(
        select(Tag, func.count(contact_tag.c.contact_id))
        .outerjoin(contact_tag, contact_tag.c.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(func.lower(Tag.name))
        .execution_options(**everything)
    ).all()
    list_rows = session.execute(
        select(ContactList, func.count(ListMember.contact_id))
        .outerjoin(ListMember, ListMember.list_id == ContactList.id)
        .where(ContactList.status == "active")
        .group_by(ContactList.id)
        .order_by(func.lower(ContactList.name))
        .execution_options(**everything)
    ).all()
    field_rows = session.execute(
        select(func.min(CustomField.name), func.count(), func.bool_or(CustomField.is_private))
        .group_by(func.lower(CustomField.name))
        .order_by(func.lower(func.min(CustomField.name)))
        .execution_options(**everything)
    ).all()
    contacts = session.scalars(
        select(Contact)
        .where(Contact.is_private.is_(True))
        .order_by(func.lower(Contact.display_name))
        .execution_options(**everything)
    ).all()
    return {
        "tags": [(t, n) for t, n in tag_rows],
        "lists": [(cl, n) for cl, n in list_rows],
        "fields": [
            (name, n, bool(flagged) or name.lower() in settings.fields)
            for name, n, flagged in field_rows
        ],
        "private_contacts": contacts,
    }


@router.get("/settings/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, session: SessionDep) -> HTMLResponse:
    settings = load_privacy(session)
    return _render(
        request,
        "settings/privacy.html",
        {
            "s": settings,
            "category_choices": CATEGORY_CHOICES,
            "off_choices": OFF_CHOICES,
            "look_choices": LOOK_CHOICES,
            "view_choices": VIEW_CHOICES,
            "notice": notice_text(request),
            **_items(session, settings),
        },
    )


@router.post("/settings/privacy", dependencies=CsrfChecked)
async def save_privacy_form(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    current = load_privacy(session)

    def choice(key: str, options: tuple[tuple[str, str, str], ...], default: str) -> str:
        value = str(form.get(key, ""))
        return value if value in {v for v, _, _ in options} else default

    saved = save_privacy(
        session,
        PrivacySettings(
            hidden=frozenset(str(v) for v in form.getlist("hidden") if v in CATEGORIES),
            labels=parse_names(str(form.get("labels", ""))),
            fields=current.fields,
            look=choice("look", LOOK_CHOICES, current.look),
            off=choice("off", OFF_CHOICES, current.off),
            start=form.get("start") == "1",
            view=choice("view", VIEW_CHOICES, current.view),
        ),
    )
    session.commit()
    request.app.state.privacy = saved
    return RedirectResponse(with_notice("/settings/privacy", "privacy"), status.HTTP_303_SEE_OTHER)


@router.post("/settings/privacy/item", dependencies=CsrfChecked)
async def mark_item(request: Request, session: SessionDep) -> Response:
    """P-03: mark a tag, list, extra field (by name) or contact private, or visible again."""
    form = await request.form()
    kind = str(form.get("kind", ""))
    private = form.get("private") == "1"
    key = str(form.get("key", "")).strip()
    if kind not in ITEM_KINDS or not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown item")
    if kind == "field":
        name = " ".join(key.split()).lower()[:50]
        session.execute(
            update(CustomField)
            .where(func.lower(CustomField.name) == name)
            .values(is_private=private)
            .execution_options(synchronize_session=False)
        )
        settings = load_privacy(session)
        names = [n for n in settings.fields if n != name] + ([name] if private else [])
        request.app.state.privacy = save_privacy(session, replace(settings, fields=tuple(names)))
    else:
        if not key.isdigit():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown item")
        models: dict[str, type[Tag] | type[ContactList] | type[Contact]] = {
            "tag": Tag,
            "list": ContactList,
            "contact": Contact,
        }
        model = models[kind]
        found = session.execute(
            update(model)
            .where(model.id == int(key))
            .values(is_private=private)
            .execution_options(synchronize_session=False)
        )
        if not getattr(found, "rowcount", 0):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    session.commit()
    target = safe_next(form.get("next"), "/settings/privacy#items-h")
    return RedirectResponse(target, status.HTTP_303_SEE_OTHER)


@router.post("/contacts/{contact_id}/private", dependencies=CsrfChecked)
async def mark_contact(request: Request, contact_id: int, session: SessionDep) -> Response:
    """P-03: the card's "Private contact" switch."""
    form = await request.form()
    contact = _load(session, contact_id)
    contact.is_private = form.get("private") == "1"
    session.commit()
    notice = "private_on" if contact.is_private else "private_off"
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", notice), status.HTTP_303_SEE_OTHER
    )
