"""JSON API for contacts (Phase 1). Writes require ``Content-Type: application/json``,
which browsers cannot send cross-site without a CORS preflight (CSRF defence, N-05)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.contacts import (
    SortKey,
    archive_contact,
    create_contact,
    get_contact,
    list_contact_types,
    list_contacts,
    lookup_contacts,
    restore_contact,
    to_out,
    update_contact,
)
from app.db import get_session
from app.schemas import ContactCreate, ContactOut, ContactRef, ContactTypeOut, ContactUpdate


def require_json(request: Request) -> None:
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json"
        )


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

router = APIRouter(prefix="/api", tags=["contacts"])
write_router = APIRouter(prefix="/api", tags=["contacts"], dependencies=[Depends(require_json)])


@router.get("/contact-types", response_model=list[ContactTypeOut])
def contact_types(session: SessionDep) -> Any:
    return list_contact_types(session)


@router.get("/contacts", response_model=list[ContactOut])
def contacts(
    session: SessionDep,
    type: Annotated[int | None, Query(description="contact type id")] = None,
    sort: SortKey = "name",
    include_archived: bool = False,
) -> list[ContactOut]:
    rows = list_contacts(
        session, contact_type_id=type, sort=sort, include_archived=include_archived
    )
    return [to_out(c) for c in rows]


@router.get("/contacts/lookup", response_model=list[ContactRef])
def lookup(
    session: SessionDep,
    q: Annotated[str, Query(max_length=100)] = "",
    exclude: int | None = None,
) -> Any:
    """Manager picker suggestions (C-07)."""
    return lookup_contacts(session, q, exclude_id=exclude)


@router.get("/contacts/{contact_id}", response_model=ContactOut)
def read_contact(contact_id: int, session: SessionDep) -> ContactOut:
    return to_out(get_contact(session, contact_id))


@write_router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create(body: ContactCreate, session: SessionDep, settings: SettingsDep) -> ContactOut:
    contact = create_contact(session, body, phone_region=settings.phone_region)
    session.commit()
    return to_out(contact)


@write_router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update(
    contact_id: int, body: ContactUpdate, session: SessionDep, settings: SettingsDep
) -> ContactOut:
    contact = update_contact(
        session, get_contact(session, contact_id), body, phone_region=settings.phone_region
    )
    session.commit()
    return to_out(contact)


@router.delete("/contacts/{contact_id}", response_model=ContactOut)
def archive(contact_id: int, session: SessionDep) -> ContactOut:
    """Archive (soft delete) — C-01. DELETE cannot be sent cross-site without CORS preflight."""
    contact = archive_contact(session, get_contact(session, contact_id))
    session.commit()
    return to_out(get_contact(session, contact.id))


@write_router.post("/contacts/{contact_id}/restore", response_model=ContactOut)
def restore(contact_id: int, session: SessionDep) -> ContactOut:
    contact = restore_contact(session, get_contact(session, contact_id))
    session.commit()
    return to_out(get_contact(session, contact.id))


def error_body(message: str, field: str | None) -> JSONResponse:
    loc: list[str] = ["body", field] if field else ["body"]
    return JSONResponse(
        {"detail": [{"loc": loc, "msg": message, "type": "value_error"}]},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
