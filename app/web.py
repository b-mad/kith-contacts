"""Server-rendered pages for contacts (Phase 1: C-01 to C-08, M-04).

Forms post back to the server; every POST is protected by a double-submit
CSRF token (N-05, ADR-0008).
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.config import Settings
from app.contacts import (
    SORT_KEYS,
    ContactError,
    ContactNotFound,
    SortKey,
    archive_contact,
    create_contact,
    get_contact,
    list_contact_types,
    list_contacts,
    restore_contact,
    to_out,
    update_contact,
)
from app.db import get_session
from app.models import Contact
from app.schemas import ContactCreate, ContactUpdate

CSRF_COOKIE = "contacts_csrf"
CSRF_FIELD = "csrf_token"

SessionDep = Annotated[Session, Depends(get_session)]


async def verify_csrf(request: Request) -> None:
    form = await request.form()
    sent = form.get(CSRF_FIELD)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not (isinstance(sent, str) and cookie and secrets.compare_digest(sent, cookie)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Invalid or missing CSRF token — reload the page"
        )


router = APIRouter(include_in_schema=False)
CsrfChecked = [Depends(verify_csrf)]


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, name, context, status_code=status_code)


def _load(session: Session, contact_id: int) -> Contact:
    try:
        return get_contact(session, contact_id)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found") from None


# ---------------------------------------------------------------- list


@router.get("/", response_class=HTMLResponse)
@router.get("/contacts", response_class=HTMLResponse)
def contact_list(
    request: Request,
    session: SessionDep,
    type: str = "",
    sort: str = "name",
    archived: str = "",
) -> HTMLResponse:
    type_id = int(type) if type.isdigit() else None
    sort_key: SortKey = sort if sort in SORT_KEYS else "name"
    include_archived = archived == "1"
    contacts = list_contacts(
        session, contact_type_id=type_id, sort=sort_key, include_archived=include_archived
    )
    return _render(
        request,
        "contacts/list.html",
        {
            "contacts": [to_out(c) for c in contacts],
            "types": list_contact_types(session),
            "type_id": type_id,
            "sort": sort_key,
            "include_archived": include_archived,
        },
    )


# ---------------------------------------------------------------- form helpers


def _row_values(form: FormData, prefix: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    columns = {f: [str(v) for v in form.getlist(f"{prefix}_{f}")] for f in fields}
    count = max((len(v) for v in columns.values()), default=0)
    return [
        {f: (columns[f][i] if i < len(columns[f]) else "") for f in fields} for i in range(count)
    ]


def parse_contact_form(form: FormData) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn a submitted form into (model input, values to re-render the form with)."""
    scalar = [
        "display_name",
        "first_name",
        "last_name",
        "nickname",
        "contact_type_id",
        "company",
        "title",
        "team",
        "department",
        "location",
        "manager_id",
        "works_on",
        "notes",
        "slack_handle",
        "slack_url",
        "teams_url",
        "pronunciation",
    ]
    values: dict[str, Any] = {f: str(form.get(f, "")).strip() for f in scalar}
    values["manager_label"] = str(form.get("manager_label", "")).strip()
    values["is_favorite"] = form.get("is_favorite") == "on"

    primary_index = str(form.get("primary_email", "0"))
    emails = _row_values(form, "email", ("address", "label"))
    for i, row in enumerate(emails):
        row["is_primary"] = str(i) == primary_index  # type: ignore[assignment]
    phones = _row_values(form, "phone", ("number", "label"))
    values["emails"] = emails
    values["phones"] = phones

    data: dict[str, Any] = {f: values[f] for f in scalar}
    data["manager_id"] = int(values["manager_id"]) if values["manager_id"].isdigit() else None
    data["contact_type_id"] = values["contact_type_id"] or None
    data["is_favorite"] = values["is_favorite"]
    data["emails"] = [
        {"email": r["address"], "label": r["label"], "is_primary": r["is_primary"]}
        for r in emails
        if r["address"].strip()
    ]
    data["phones"] = [
        {"number": r["number"], "label": r["label"]} for r in phones if r["number"].strip()
    ]
    return data, values


FIELD_LABELS = {
    "display_name": "Display name",
    "contact_type_id": "Type",
    "emails": "Email",
    "phones": "Phone",
    "manager_id": "Manager",
    "slack_handle": "Slack handle",
    "slack_url": "Slack link",
    "teams_url": "Teams link",
}


def errors_from_validation(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err["loc"]
        field = str(loc[0]) if loc else "__all__"
        msg = err["msg"].removeprefix("Value error, ")
        if field in {"emails", "phones"} and len(loc) > 1 and isinstance(loc[1], int):
            msg = f"{FIELD_LABELS[field]} {loc[1] + 1}: {msg}"
        errors.setdefault(field, msg)
    return errors


def unresolved_manager(values: dict[str, Any]) -> dict[str, str]:
    """A typed manager name that was never picked would silently save no manager."""
    if values.get("manager_label") and not values.get("manager_id"):
        return {"manager_id": "Pick the manager from the suggestions, or clear the field"}
    return {}


def _form_context(
    session: Session,
    values: dict[str, Any],
    *,
    contact_id: int | None = None,
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    emails = values.get("emails") or []
    phones = values.get("phones") or []
    return {
        "values": values,
        "emails": emails or [{"address": "", "label": "", "is_primary": True}],
        "phones": phones or [{"number": "", "label": ""}],
        "types": list_contact_types(session),
        "contact_id": contact_id,
        "errors": errors or {},
    }


def _values_from_contact(contact: Contact) -> dict[str, Any]:
    out = to_out(contact)
    values: dict[str, Any] = {
        f: (getattr(contact, f) or "")
        for f in [
            "display_name",
            "first_name",
            "last_name",
            "nickname",
            "company",
            "title",
            "team",
            "department",
            "location",
            "works_on",
            "notes",
            "slack_handle",
            "slack_url",
            "teams_url",
            "pronunciation",
        ]
    }
    values["contact_type_id"] = str(contact.contact_type_id)
    values["is_favorite"] = contact.is_favorite
    values["manager_id"] = str(contact.manager_id or "")
    values["manager_label"] = out.manager.display_name if out.manager else ""
    values["emails"] = [
        {"address": e.email, "label": e.label or "", "is_primary": e.is_primary} for e in out.emails
    ]
    values["phones"] = [{"number": p.number, "label": p.label or ""} for p in out.phones]
    return values


def _manager_label(session: Session, manager_id: str) -> str:
    if not manager_id.isdigit():
        return ""
    try:
        return get_contact(session, int(manager_id)).display_name
    except ContactNotFound:
        return ""


# ---------------------------------------------------------------- create


@router.get("/contacts/new", response_class=HTMLResponse)
def new_contact(request: Request, session: SessionDep, manager: str = "") -> HTMLResponse:
    types = list_contact_types(session)
    values: dict[str, Any] = {
        "contact_type_id": str(types[0].id) if types else "",
        "manager_id": manager if manager.isdigit() else "",
        "manager_label": _manager_label(session, manager),
    }
    return _render(request, "contacts/form.html", _form_context(session, values))


@router.post("/contacts", dependencies=CsrfChecked)
async def create_contact_form(request: Request, session: SessionDep) -> Response:
    data, values = parse_contact_form(await request.form())
    if errors := unresolved_manager(values):
        return _render(
            request, "contacts/form.html", _form_context(session, values, errors=errors), 422
        )
    try:
        contact = create_contact(
            session,
            ContactCreate.model_validate(data),
            phone_region=_settings(request).phone_region,
        )
    except ValidationError as exc:
        errors = errors_from_validation(exc)
    except ContactError as exc:
        session.rollback()
        errors = {exc.field or "__all__": exc.message}
    else:
        session.commit()
        return RedirectResponse(f"/contacts/{contact.id}?saved=1", status.HTTP_303_SEE_OTHER)
    return _render(
        request,
        "contacts/form.html",
        _form_context(session, values, errors=errors),
        status_code=422,
    )


# ---------------------------------------------------------------- card


@router.get("/contacts/{contact_id}", response_class=HTMLResponse)
def contact_card(
    request: Request, contact_id: int, session: SessionDep, saved: str = ""
) -> HTMLResponse:
    contact = _load(session, contact_id)
    return _render(request, "contacts/card.html", {"c": to_out(contact), "saved": saved == "1"})


# ---------------------------------------------------------------- edit


@router.get("/contacts/{contact_id}/edit", response_class=HTMLResponse)
def edit_contact(request: Request, contact_id: int, session: SessionDep) -> HTMLResponse:
    contact = _load(session, contact_id)
    return _render(
        request,
        "contacts/form.html",
        _form_context(session, _values_from_contact(contact), contact_id=contact_id),
    )


@router.post("/contacts/{contact_id}/edit", dependencies=CsrfChecked)
async def update_contact_form(request: Request, contact_id: int, session: SessionDep) -> Response:
    contact = _load(session, contact_id)
    data, values = parse_contact_form(await request.form())
    if errors := unresolved_manager(values):
        return _render(
            request,
            "contacts/form.html",
            _form_context(session, values, contact_id=contact_id, errors=errors),
            422,
        )
    try:
        body = ContactUpdate.model_validate(ContactCreate.model_validate(data).model_dump())
        update_contact(session, contact, body, phone_region=_settings(request).phone_region)
    except ValidationError as exc:
        errors = errors_from_validation(exc)
    except ContactError as exc:
        session.rollback()
        errors = {exc.field or "__all__": exc.message}
    else:
        session.commit()
        return RedirectResponse(f"/contacts/{contact_id}?saved=1", status.HTTP_303_SEE_OTHER)
    return _render(
        request,
        "contacts/form.html",
        _form_context(session, values, contact_id=contact_id, errors=errors),
        status_code=422,
    )


# ---------------------------------------------------------------- archive / restore


@router.post("/contacts/{contact_id}/archive", dependencies=CsrfChecked)
def archive_contact_form(contact_id: int, session: SessionDep) -> Response:
    archive_contact(session, _load(session, contact_id))
    session.commit()
    return RedirectResponse(f"/contacts/{contact_id}", status.HTTP_303_SEE_OTHER)


@router.post("/contacts/{contact_id}/restore", dependencies=CsrfChecked)
def restore_contact_form(contact_id: int, session: SessionDep) -> Response:
    restore_contact(session, _load(session, contact_id))
    session.commit()
    return RedirectResponse(f"/contacts/{contact_id}", status.HTTP_303_SEE_OTHER)
