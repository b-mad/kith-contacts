"""Pages for project lists (L-01 to L-05) and tags (T-02)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.contacts import ContactError, ContactNotFound, primary_email
from app.links import mailto_url
from app.lists import (
    add_list_tag,
    add_members,
    all_lists,
    create_list,
    get_list,
    remove_list_tag,
    remove_member,
    set_list_status,
    set_role_note,
    update_list,
)
from app.models import ContactList
from app.privacy import presenting
from app.tags import tag_counts
from app.web import CsrfChecked, SessionDep, _render, notice_text, with_notice

router = APIRouter(include_in_schema=False)


def _load_list(session: Session, list_id: int) -> ContactList:
    try:
        return get_list(session, list_id)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "List not found") from None


def _fail(session: Session, exc: ContactError) -> HTTPException:
    session.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)


# ---------------------------------------------------------------- index


@router.get("/lists", response_class=HTMLResponse)
def lists_index(
    request: Request, session: SessionDep, archived: str = "", tag: str = ""
) -> HTMLResponse:
    return _render(
        request,
        "lists/index.html",
        {
            "rows": all_lists(session, include_archived=archived == "1", tag=tag or None),
            "include_archived": archived == "1",
            "tag": tag,
            "notice": notice_text(request),
            "error": None,
        },
    )


@router.post("/lists", dependencies=CsrfChecked)
async def create_list_form(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        contact_list = create_list(
            session, str(form.get("name", "")), str(form.get("description", ""))
        )
    except ContactError as exc:
        session.rollback()
        return _render(
            request,
            "lists/index.html",
            {
                "rows": all_lists(session),
                "include_archived": False,
                "notice": None,
                "error": exc.message,
                "form_name": str(form.get("name", "")),
            },
            status_code=422,
        )
    session.commit()
    return RedirectResponse(
        with_notice(f"/lists/{contact_list.id}", "created"), status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------- one list


def _member_rows(contact_list: ContactList) -> list[dict[str, Any]]:
    rows = []
    p = presenting()
    # contact is None for a private contact withheld while presenting (P-02).
    members = [m for m in contact_list.members if m.contact is not None]
    for member in sorted(members, key=lambda m: m.contact.display_name.lower()):
        contact = member.contact
        reachable = p is None or not p.names_only
        rows.append(
            {
                "contact": contact,
                "role_note": (member.role_note or "") if reachable else "",
                "email": primary_email(contact) if reachable else None,
                "phone": contact.phones[0].number if contact.phones and reachable else None,
                "archived": contact.archived_at is not None,
            }
        )
    return rows


@router.get("/lists/{list_id}", response_class=HTMLResponse)
def list_detail(request: Request, list_id: int, session: SessionDep) -> HTMLResponse:
    contact_list = _load_list(session, list_id)
    rows = _member_rows(contact_list)
    emails = [r["email"] for r in rows if r["email"] and not r["archived"]]
    return _render(
        request,
        "lists/detail.html",
        {
            "cl": contact_list,
            "rows": rows,
            "mailto_all": mailto_url(emails),
            "notice": notice_text(request),
            "tags": tag_counts(session),
            "lists": [cl for cl, _ in all_lists(session)],
        },
    )


@router.post("/lists/{list_id}/edit", dependencies=CsrfChecked)
async def edit_list(request: Request, list_id: int, session: SessionDep) -> Response:
    contact_list = _load_list(session, list_id)
    form = await request.form()
    try:
        update_list(
            session,
            contact_list,
            name=str(form.get("name", "")),
            description=str(form.get("description", "")),
        )
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(with_notice(f"/lists/{list_id}", "saved"), status.HTTP_303_SEE_OTHER)


@router.post("/lists/{list_id}/archive", dependencies=CsrfChecked)
def archive_list(list_id: int, session: SessionDep) -> Response:
    set_list_status(session, _load_list(session, list_id), "archived")
    session.commit()
    return RedirectResponse(f"/lists/{list_id}", status.HTTP_303_SEE_OTHER)


@router.post("/lists/{list_id}/restore", dependencies=CsrfChecked)
def restore_list(list_id: int, session: SessionDep) -> Response:
    set_list_status(session, _load_list(session, list_id), "active")
    session.commit()
    return RedirectResponse(f"/lists/{list_id}", status.HTTP_303_SEE_OTHER)


@router.post("/lists/{list_id}/members", dependencies=CsrfChecked)
async def add_member_form(request: Request, list_id: int, session: SessionDep) -> Response:
    """Add one person picked by typing (L-02)."""
    contact_list = _load_list(session, list_id)
    form = await request.form()
    raw_id = str(form.get("contact_id", ""))
    if not raw_id.isdigit():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick a person from the suggestions"
        )
    try:
        add_members(session, contact_list, [int(raw_id)], str(form.get("role_note", "")))
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/lists/{list_id}", "listed", n=1, name=contact_list.name),
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/lists/{list_id}/members/{contact_id}/remove", dependencies=CsrfChecked)
def remove_member_form(list_id: int, contact_id: int, session: SessionDep) -> Response:
    remove_member(session, _load_list(session, list_id), contact_id)
    session.commit()
    return RedirectResponse(with_notice(f"/lists/{list_id}", "removed"), status.HTTP_303_SEE_OTHER)


@router.post("/lists/{list_id}/members/{contact_id}/role", dependencies=CsrfChecked)
async def role_form(
    request: Request, list_id: int, contact_id: int, session: SessionDep
) -> Response:
    """L-03: per-membership role note."""
    contact_list = _load_list(session, list_id)
    form = await request.form()
    try:
        set_role_note(session, contact_list, contact_id, str(form.get("role_note", "")))
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this list") from None
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(with_notice(f"/lists/{list_id}", "saved"), status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------- list tags (L-05)


@router.post("/lists/{list_id}/tags", dependencies=CsrfChecked)
async def add_list_tag_form(request: Request, list_id: int, session: SessionDep) -> Response:
    contact_list = _load_list(session, list_id)
    form = await request.form()
    try:
        tag = add_list_tag(session, contact_list, str(form.get("tag", "")))
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/lists/{list_id}", "list_tagged", name=tag.name),
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/lists/{list_id}/tags/{tag_id}/remove", dependencies=CsrfChecked)
def remove_list_tag_form(list_id: int, tag_id: int, session: SessionDep) -> Response:
    remove_list_tag(session, _load_list(session, list_id), tag_id)
    session.commit()
    return RedirectResponse(with_notice(f"/lists/{list_id}", "untagged"), status.HTTP_303_SEE_OTHER)
