"""Settings, backups, import/export, org chart, tag and type admin, photos (Phase 3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Forms yield Starlette's UploadFile (FastAPI's is a subclass, so isinstance needs this one).
from starlette.datastructures import FormData, UploadFile

from app.appearance import (
    DENSITY_CHOICES,
    PALETTE_CHOICES,
    THEME_CHOICES,
    current_appearance,
    forget_appearance,
    instance_defaults,
    save_appearance,
)
from app.backup import BackupError, backup, find_backup, list_backups, prune, restore
from app.birthdays import month_first
from app.contact_types import add_type, delete_type, move_type, rename_type, types_with_counts
from app.contacts import ContactError, ContactNotFound, list_contact_types
from app.exchange import (
    FIELD_GROUPS,
    FIELD_HELP,
    FIELD_LABELS,
    FIELDS,
    GOOGLE_HEADERS,
    IMPORT_PAGE_SIZE,
    SHOW_FILTERS,
    PlannedRow,
    carried_fields,
    export_contact_json,
    export_csv,
    export_json,
    filter_rows,
    guess_mapping,
    mapping_guide,
    paginate,
    plan_import,
    read_csv,
    rows_from_csv,
    rows_from_json,
    rows_from_vcards,
    run_import,
    update_selection,
)
from app.importdiff import COMPARED_SUMMARY
from app.maps import PROVIDERS, save_provider
from app.migrate import upgrade_to_head
from app.models import Contact, ContactPhoto, Tag
from app.org import build_org
from app.photos import remove_photo, set_photo
from app.privacy import forget_privacy
from app.schemas import AppearanceIn
from app.search import active_lists
from app.semantic import index_counts, mark_all_stale
from app.tags import (
    TAG_COLORS,
    delete_tag,
    list_tag_counts,
    rename_tag,
    set_tag_color,
    tag_counts,
)
from app.vcard import parse_vcards, to_vcard, to_vcards
from app.web import (
    CsrfChecked,
    SessionDep,
    _load,
    _render,
    _settings,
    notice_text,
    safe_next,
    with_notice,
)

router = APIRouter(include_in_schema=False)


def _fail(session: Session, exc: ContactError) -> HTTPException:
    session.rollback()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _download(body: str | bytes, filename: str, media_type: str) -> Response:
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------- settings & backups (D-04, I-06)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: SessionDep) -> HTMLResponse:
    settings = _settings(request)
    return _render(
        request,
        "settings/index.html",
        {
            "backups": list_backups(settings),
            "backup_status": request.app.state.backup_status,
            "backup_dir": settings.resolved_backup_dir,
            "retention": settings.backup_retention_days,
            "contact_count": session.scalar(select(func.count()).select_from(Contact)),
            "semantic": request.app.state.semantic,
            "semantic_counts": index_counts(session, request.app.state.semantic.model_id),
            "notice": notice_text(request),
            "error": request.query_params.get("error"),
            "chosen": current_appearance(request.app.state),
            "theme_choices": THEME_CHOICES,
            "palette_choices": PALETTE_CHOICES,
            "density_choices": DENSITY_CHOICES,
        },
    )


@router.post("/settings/maps", dependencies=CsrfChecked)
async def save_maps_form(request: Request, session: SessionDep) -> Response:
    """M-06: Google Maps or Apple Maps for directions (ADR-0023)."""
    form = await request.form()
    try:
        saved = save_provider(session, str(form.get("provider", "")))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown maps app") from None
    session.commit()
    request.app.state.maps_provider = saved
    name = next(label for value, label, _ in PROVIDERS if value == saved)
    return RedirectResponse(
        with_notice("/settings", "maps", name=name) + "#maps-h", status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/appearance", dependencies=CsrfChecked)
async def save_appearance_form(request: Request, session: SessionDep) -> Response:
    """A-01 to A-05: save the theme, palette and/or density for this instance (ADR-0015).

    A plain form post redirects (works without JavaScript); app.js asks for JSON instead.
    """
    form = await request.form()
    wants_json = "application/json" in request.headers.get("accept", "")
    try:
        choice = AppearanceIn.model_validate(
            {key: str(form[key]) for key in ("theme", "palette", "density") if key in form}
        )
    except ValidationError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown theme, palette or density"
        ) from None
    saved = save_appearance(
        session,
        theme=choice.theme,
        palette=choice.palette,
        density=choice.density,
        defaults=instance_defaults(request.app.state),
    )
    session.commit()
    request.app.state.appearance = saved
    if wants_json:
        return JSONResponse(
            {"theme": saved.theme, "palette": saved.palette, "density": saved.density}
        )
    if form.get("next"):
        return RedirectResponse(safe_next(form.get("next"), "/"), status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        with_notice("/settings", "appearance") + "#appearance-h", status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/semantic/rebuild", dependencies=CsrfChecked)
def rebuild_semantic(session: SessionDep) -> Response:
    """S-08: re-check every contact's embeddings (the background task does the work)."""
    mark_all_stale(session)
    session.commit()
    return RedirectResponse(
        with_notice("/settings", "reindexing") + "#semantic-h", status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/backups", dependencies=CsrfChecked)
def backup_now(request: Request) -> Response:
    settings = _settings(request)
    try:
        made = backup(settings)
        prune(settings)
    except BackupError as exc:
        return RedirectResponse(
            with_notice("/settings", "", error=str(exc)[:300]), status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        with_notice("/settings", "backup", name=made.name), status.HTTP_303_SEE_OTHER
    )


@router.get("/settings/backups/{name}")
def download_backup(request: Request, name: str) -> FileResponse:
    try:
        item = find_backup(_settings(request), name)
    except BackupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found") from None
    return FileResponse(item.path, filename=item.name, media_type="application/octet-stream")


@router.post("/settings/backups/{name}/restore", dependencies=CsrfChecked)
async def restore_backup(request: Request, name: str) -> Response:
    settings = _settings(request)
    form = await request.form()
    if str(form.get("confirm", "")).strip() != settings.instance_name:
        return RedirectResponse(
            with_notice(
                "/settings", "", error=f"Type “{settings.instance_name}” to confirm the restore."
            ),
            status.HTTP_303_SEE_OTHER,
        )
    try:
        item = find_backup(settings, name)
        request.app.state.engine.dispose()  # drop pooled connections to the old tables
        restore(settings, item.path)
        upgrade_to_head(settings)
        forget_appearance(request.app.state)  # the restored database has its own choice
        forget_privacy(request.app.state)
    except BackupError as exc:
        return RedirectResponse(
            with_notice("/settings", "", error=str(exc)[:300]), status.HTTP_303_SEE_OTHER
        )
    finally:
        request.app.state.engine.dispose()
    return RedirectResponse(
        with_notice("/settings", "restored", name=name), status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------- export (D-02, D-03)


@router.get("/export/contacts.csv")
def export_contacts_csv(request: Request, session: SessionDep) -> Response:
    name = f"{_settings(request).instance_slug}-contacts-{_stamp()}.csv"
    return _download("﻿" + export_csv(session), name, "text/csv; charset=utf-8")


@router.get("/export/contacts.json")
def export_contacts_json(request: Request, session: SessionDep) -> Response:
    settings = _settings(request)
    body = json.dumps(export_json(session, settings.instance_name), indent=2, ensure_ascii=False)
    return _download(body, f"{settings.instance_slug}-contacts-{_stamp()}.json", "application/json")


@router.get("/export/contacts.vcf")
def export_contacts_vcf(request: Request, session: SessionDep) -> Response:
    from app.exchange import _all_contacts

    contacts = [c for c in _all_contacts(session) if c.archived_at is None]
    name = f"{_settings(request).instance_slug}-contacts-{_stamp()}.vcf"
    return _download(to_vcards(contacts), name, "text/vcard; charset=utf-8")


@router.get("/contacts/{contact_id}/vcard")
def contact_vcard(contact_id: int, session: SessionDep) -> Response:
    contact = _load(session, contact_id)
    safe = (
        "".join(ch if ch.isalnum() else "-" for ch in contact.display_name).strip("-") or "contact"
    )
    return _download(to_vcard(contact), f"{safe}.vcf", "text/vcard; charset=utf-8")


@router.get("/contacts/{contact_id}/export.json")
def contact_json(request: Request, contact_id: int, session: SessionDep) -> Response:
    """I-09: one contact with everything (and its photo), to import into another instance."""
    contact = _load(session, contact_id)
    safe = (
        "".join(ch if ch.isalnum() else "-" for ch in contact.display_name).strip("-") or "contact"
    )
    body = json.dumps(
        export_contact_json(contact, _settings(request).instance_name), indent=2, ensure_ascii=False
    )
    return _download(body, f"{safe}.json", "application/json")


# ---------------------------------------------------------------- import (D-01, D-02, I-09)


SHOW_LABELS = {
    "all": "All rows",
    "ready": "Ready to import",
    "duplicates": "Possible duplicates",
    "errors": "Rows with errors",
}


def _import_context(
    session: Session,
    *,
    kind: str,
    raw: str,
    headers: list[str],
    mapping: dict[int, str],
    planned: list[PlannedRow],
    default_type_id: int,
    list_name: str,
    selected: set[int],
    page: int = 1,
    show: str = "all",
) -> dict[str, Any]:
    ok = [r for r in planned if r.ok and not r.duplicate_of]
    dups = [r for r in planned if r.ok and r.duplicate_of]
    show = show if show in SHOW_FILTERS else "all"
    rows = filter_rows(planned, show)
    page_rows, page, pages = paginate(rows, page)
    on_page = {r.number for r in page_rows}
    return {
        "kind": kind,
        "raw": raw,
        "headers": headers,
        "mapping": mapping,
        "field_labels": FIELD_LABELS,
        "field_groups": FIELD_GROUPS,
        "planned": planned,
        "preview": page_rows,
        "page": page,
        "pages": pages,
        "page_size": IMPORT_PAGE_SIZE,
        "first_shown": (page - 1) * IMPORT_PAGE_SIZE + 1 if rows else 0,
        "last_shown": (page - 1) * IMPORT_PAGE_SIZE + len(page_rows),
        "filtered_total": len(rows),
        "show": show,
        "show_label": SHOW_LABELS[show],
        "show_filters": [(key, SHOW_LABELS[key]) for key in SHOW_FILTERS],
        "selected": selected,
        "selected_csv": ",".join(str(n) for n in sorted(selected)),
        "shown_csv": ",".join(str(r.number) for r in page_rows),
        "selected_elsewhere": len(selected - on_page),
        "compared": COMPARED_SUMMARY,
        "counts": {
            "total": len(planned),
            "ready": len(ok),
            "duplicates": len(dups),
            "identical": sum(1 for r in dups if r.duplicate and r.duplicate.full_match),
            "differ": sum(1 for r in dups if r.duplicate and not r.duplicate.full_match),
            "importable": sum(1 for r in planned if r.ok),
            "errors": sum(1 for r in planned if not r.ok),
            "selected": len(selected),
        },
        "types": list_contact_types(session),
        "default_type_id": default_type_id,
        "list_name": list_name,
        "error": None,
    }


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "import/upload.html",
        {"types": list_contact_types(session), "error": None, "lists": active_lists(session)},
    )


@router.get("/import/help", response_class=HTMLResponse)
def import_help(request: Request) -> HTMLResponse:
    """D-06: what the column mapping means and where each export's columns go."""
    guide = mapping_guide(GOOGLE_HEADERS)
    return _render(
        request,
        "import/help.html",
        {
            "fields": [
                (FIELD_LABELS[key], FIELD_HELP[key], spellings) for key, spellings in FIELDS.items()
            ],
            "google_mapped": [(column, label) for column, label in guide if label],
            "google_ignored": [column for column, label in guide if not label],
        },
    )


async def _read_upload(form: FormData) -> tuple[str, str]:
    """(kind, text) from a new upload or the carried-over raw data."""
    upload = form.get("file")
    if isinstance(upload, UploadFile) and upload.filename:
        data = await upload.read()
        await upload.close()
        name = upload.filename.lower()
        if name.endswith((".vcf", ".vcard")) or data[:11].upper().startswith(b"BEGIN:VCARD"):
            return "vcard", data.decode("utf-8-sig", errors="replace")
        if name.endswith(".json") or data.lstrip()[:1] == b"{":
            return "json", data.decode("utf-8-sig", errors="replace")
        read_csv(data)  # validates size/shape early
        try:
            return "csv", data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return "csv", data.decode("cp1252", errors="replace")
    if isinstance(upload, UploadFile):
        await upload.close()  # an empty file field still opens a temp file
    raw = str(form.get("raw", ""))
    if not raw.strip():
        raise ContactError("Choose a CSV, vCard or JSON file to import", "file")
    return str(form.get("kind", "csv")), raw


def _ints(raw: object) -> set[int]:
    return {int(part) for part in str(raw).split(",") if part.strip().isdigit()}


def _selection(planned: list[PlannedRow], form: FormData) -> set[int]:
    """D-07: the rows to import. The first preview picks the ready rows; after that the form
    carries the selection, with this page's ticks applied over it."""
    return update_selection(
        planned,
        previous=_ints(form.get("selected", "")) if "selected" in form else None,
        shown=_ints(form.get("shown", "")),
        picked={int(str(v)) for v in form.getlist("pick") if str(v).isdigit()},
        bulk=str(form.get("bulk", "")),
    )


def _page_number(form: FormData) -> int:
    raw = str(form.get("goto") or form.get("current_page") or "1")
    return int(raw) if raw.isdigit() else 1


def _plan(
    session: Session, form: FormData, kind: str, raw: str, region: str = "US"
) -> dict[str, Any]:
    types = list_contact_types(session)
    default_type = str(form.get("default_type_id", ""))
    default_type_id = int(default_type) if default_type.isdigit() else types[0].id
    if kind == "json":  # I-09: an export from this app, possibly another instance
        records = rows_from_json(raw)
        headers: list[str] = []
        mapping: dict[int, str] = {}
    elif kind == "vcard":
        records = rows_from_vcards(parse_vcards(raw))
        headers = []
        mapping = {}
    else:
        headers, body = read_csv(raw.encode("utf-8"))
        if any(k.startswith("map_") for k in form):
            mapping = {
                i: str(form.get(f"map_{i}"))
                for i in range(len(headers))
                if str(form.get(f"map_{i}", "")) in FIELD_LABELS
            }
        else:
            mapping = guess_mapping(headers)
        records = rows_from_csv(body, mapping, headers)
    planned = plan_import(
        session,
        records,
        default_type_id,
        month_first=month_first(region),
        phone_region=region,
        carried=carried_fields(kind, mapping, records),
    )
    return _import_context(
        session,
        kind=kind,
        raw=raw,
        headers=headers,
        mapping=mapping,
        planned=planned,
        default_type_id=default_type_id,
        list_name=str(form.get("list_name", "")),
        selected=_selection(planned, form),
        page=_page_number(form),
        show=str(form.get("show", "all")),
    )


@router.post("/import/preview", response_class=HTMLResponse, dependencies=CsrfChecked)
async def import_preview(request: Request, session: SessionDep) -> HTMLResponse:
    form = await request.form()
    try:
        kind, raw = await _read_upload(form)
        context = _plan(session, form, kind, raw, _settings(request).phone_region)
    except ContactError as exc:
        return _render(
            request,
            "import/upload.html",
            {
                "types": list_contact_types(session),
                "error": exc.message,
                "lists": active_lists(session),
            },
            status_code=422,
        )
    return _render(request, "import/preview.html", context)


@router.post("/import/run", dependencies=CsrfChecked)
async def import_run(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        kind, raw = await _read_upload(form)
        context = _plan(session, form, kind, raw, _settings(request).phone_region)
        explicit = "selected" in form  # the review page sends its selection (D-07)
        if explicit and not context["selected"]:
            context["error"] = "Select at least one contact to import."
            return _render(request, "import/preview.html", context, status_code=422)
        result = run_import(
            session,
            context["planned"],
            include_duplicates=form.get("include_duplicates") == "on",
            only=context["selected"] if explicit else None,
            list_name=str(form.get("list_name", "")) or None,
            phone_region=_settings(request).phone_region,
        )
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    target = f"/lists/{result.list_id}" if result.list_id else "/?sort=updated"
    return RedirectResponse(
        with_notice(target, "imported", n=len(result.created)), status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------- org chart (S-06)


@router.get("/org", response_class=HTMLResponse)
def org_chart(request: Request, session: SessionDep, root: int | None = None) -> HTMLResponse:
    return _render(request, "org/index.html", {"org": build_org(session, root)})


# ---------------------------------------------------------------- tag admin (T-04)


@router.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "tags/index.html",
        {
            "tags": tag_counts(session),
            "list_counts": list_tag_counts(session),
            "colors": TAG_COLORS,
            "notice": notice_text(request),
        },
    )


def _tag(session: Session, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return tag


@router.post("/tags/{tag_id}/edit", dependencies=CsrfChecked)
async def edit_tag(request: Request, tag_id: int, session: SessionDep) -> Response:
    tag = _tag(session, tag_id)
    form = await request.form()
    try:
        set_tag_color(session, tag, str(form.get("color", "")) or None)
        name = str(form.get("name", "")).strip()
        if name and name != tag.name:
            rename_tag(session, tag, name)
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(with_notice("/tags", "tag_saved"), status.HTTP_303_SEE_OTHER)


@router.post("/tags/{tag_id}/delete", dependencies=CsrfChecked)
def remove_tag_everywhere(tag_id: int, session: SessionDep) -> Response:
    delete_tag(session, _tag(session, tag_id))
    session.commit()
    return RedirectResponse(with_notice("/tags", "tag_deleted"), status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------- contact types (I-08)


@router.get("/settings/types", response_class=HTMLResponse)
def types_page(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(
        request,
        "settings/types.html",
        {"rows": types_with_counts(session), "notice": notice_text(request), "error": None},
    )


def _types_error(request: Request, session: Session, exc: ContactError) -> HTMLResponse:
    session.rollback()
    return _render(
        request,
        "settings/types.html",
        {"rows": types_with_counts(session), "notice": None, "error": exc.message},
        status_code=422,
    )


def _types_saved() -> Response:
    return RedirectResponse(with_notice("/settings/types", "type_saved"), status.HTTP_303_SEE_OTHER)


@router.post("/settings/types", dependencies=CsrfChecked)
async def create_type(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    try:
        add_type(session, str(form.get("name", "")))
    except ContactError as exc:
        return _types_error(request, session, exc)
    session.commit()
    return _types_saved()


@router.post("/settings/types/{type_id}/rename", dependencies=CsrfChecked)
async def rename_type_form(request: Request, type_id: int, session: SessionDep) -> Response:
    form = await request.form()
    try:
        rename_type(session, type_id, str(form.get("name", "")))
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found") from None
    except ContactError as exc:
        return _types_error(request, session, exc)
    session.commit()
    return _types_saved()


@router.post("/settings/types/{type_id}/move", dependencies=CsrfChecked)
async def move_type_form(request: Request, type_id: int, session: SessionDep) -> Response:
    form = await request.form()
    try:
        move_type(session, type_id, -1 if form.get("direction") == "up" else 1)
    except (ContactNotFound, StopIteration):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found") from None
    session.commit()
    return _types_saved()


@router.post("/settings/types/{type_id}/delete", dependencies=CsrfChecked)
async def delete_type_form(request: Request, type_id: int, session: SessionDep) -> Response:
    form = await request.form()
    move_to = str(form.get("move_to", ""))
    try:
        delete_type(session, type_id, int(move_to) if move_to.isdigit() else None)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Type not found") from None
    except ContactError as exc:
        return _types_error(request, session, exc)
    session.commit()
    return _types_saved()


# ---------------------------------------------------------------- photos (C-09)


@router.get("/contacts/{contact_id}/photo")
def contact_photo(request: Request, contact_id: int, session: SessionDep) -> Response:
    photo = session.scalars(
        select(ContactPhoto).where(ContactPhoto.contact_id == contact_id)
    ).first()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No photo")
    etag = f'"{contact_id}-{int(photo.updated_at.timestamp())}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(
        photo.data,
        media_type=photo.content_type,
        headers={"ETag": etag, "Cache-Control": "private, no-cache"},
    )


@router.post("/contacts/{contact_id}/photo", dependencies=CsrfChecked)
async def upload_photo(request: Request, contact_id: int, session: SessionDep) -> Response:
    _load(session, contact_id)
    form = await request.form()
    upload = form.get("photo")
    data = b""
    if isinstance(upload, UploadFile):
        data = await upload.read()
        await upload.close()
    try:
        set_photo(session, contact_id, data)
    except ContactError as exc:
        raise _fail(session, exc) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "photo_saved"), status.HTTP_303_SEE_OTHER
    )


@router.post("/contacts/{contact_id}/photo/remove", dependencies=CsrfChecked)
def delete_photo(contact_id: int, session: SessionDep) -> Response:
    _load(session, contact_id)
    remove_photo(session, contact_id)
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "photo_removed"), status.HTTP_303_SEE_OTHER
    )
