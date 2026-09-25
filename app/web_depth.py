"""Phase 4 pages: duplicates and merge (C-12), saved searches (S-07) (ADR-0012)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.contacts import ContactError, ContactNotFound, get_contact
from app.duplicates import (
    Side,
    conflicts,
    dismiss_pair,
    find_duplicates,
    merge_contacts,
    merge_preview_rows,
    merged_counts,
)
from app.models import SavedSearch
from app.saved_searches import (
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
    rename_saved_search,
    save_search,
)
from app.web import CsrfChecked, SessionDep, _render, notice_text, with_notice

router = APIRouter(include_in_schema=False)


def _pair(session: Any, a: int, b: int) -> tuple[Any, Any]:
    if a == b:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick two different contacts")
    try:
        return get_contact(session, a), get_contact(session, b)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found") from None


# ---------------------------------------------------------------- duplicates (C-12)


@router.get("/duplicates", response_class=HTMLResponse)
def duplicates_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "duplicates/index.html",
        {"pairs": find_duplicates(session), "notice": notice_text(request)},
    )


@router.post("/duplicates/dismiss", dependencies=CsrfChecked)
async def dismiss(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    a, b = str(form.get("a", "")), str(form.get("b", ""))
    if not (a.isdigit() and b.isdigit()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick two contacts")
    try:
        dismiss_pair(session, int(a), int(b))
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found") from None
    session.commit()
    return RedirectResponse(with_notice("/duplicates", "dismissed"), status.HTTP_303_SEE_OTHER)


@router.get("/duplicates/merge", response_class=HTMLResponse)
def merge_page(request: Request, session: SessionDep, a: int, b: int) -> HTMLResponse:
    ca, cb = _pair(session, a, b)
    return _render(
        request,
        "duplicates/merge.html",
        {
            "a": ca,
            "b": cb,
            "rows": merge_preview_rows(ca, cb),
            "counts": merged_counts(ca, cb),
        },
    )


@router.post("/duplicates/merge", dependencies=CsrfChecked)
async def merge(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    a_raw, b_raw = str(form.get("a", "")), str(form.get("b", ""))
    if not (a_raw.isdigit() and b_raw.isdigit()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick two contacts")
    ca, cb = _pair(session, int(a_raw), int(b_raw))
    keep, other = (cb, ca) if form.get("keep") == "b" else (ca, cb)
    # Each conflicting field's radio says "a" or "b"; translate to kept/other.
    choices: dict[str, Side] = {}
    for name in conflicts(keep, other):
        picked = str(form.get(f"choice_{name}", ""))
        side_contact = ca if picked == "a" else cb if picked == "b" else keep
        choices[name] = "keep" if side_contact is keep else "other"
    merged_name = other.display_name
    try:
        kept = merge_contacts(session, keep.id, other.id, choices)
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{kept.id}", "merged", name=merged_name),
        status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------- saved searches (S-07)


def _saved(session: Any, search_id: int) -> SavedSearch:
    try:
        return get_saved_search(session, search_id)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found") from None


def _fail(session: Any, exc: ContactError) -> HTTPException:
    session.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)


@router.get("/saved-searches", response_class=HTMLResponse)
def saved_searches_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "saved/index.html",
        {"saved": list_saved_searches(session), "notice": notice_text(request)},
    )


@router.post("/saved-searches", dependencies=CsrfChecked)
async def create_saved_search(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        saved = save_search(session, str(form.get("name", "")), str(form.get("query", "")))
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/?{saved.query}", "search_saved", name=saved.name),
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/saved-searches/{search_id}/rename", dependencies=CsrfChecked)
async def rename_saved(request: Request, search_id: int, session: SessionDep) -> Response:
    saved = _saved(session, search_id)
    form = await request.form()
    try:
        rename_saved_search(session, saved, str(form.get("name", "")))
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(
        with_notice("/saved-searches", "search_renamed"), status.HTTP_303_SEE_OTHER
    )


@router.post("/saved-searches/{search_id}/delete", dependencies=CsrfChecked)
def delete_saved(search_id: int, session: SessionDep) -> Response:
    delete_saved_search(session, _saved(session, search_id))
    session.commit()
    return RedirectResponse(
        with_notice("/saved-searches", "search_deleted"), status.HTTP_303_SEE_OTHER
    )
