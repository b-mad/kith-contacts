"""Server-rendered pages for contacts (C-01 to C-08, C-10, C-14, S-01 to S-05, T-01, M-01).

Forms post back to the server; every POST is protected by a double-submit
CSRF token (N-05, ADR-0008).
"""

from __future__ import annotations

import contextlib
import secrets
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from app.activity import KIND_LABELS, add_activity, delete_activity, parse_date
from app.addresses import country_number, state_name
from app.birthdays import Birthday, month_first, parse_birthday
from app.config import Settings
from app.contacts import (
    ContactError,
    ContactNotFound,
    archive_contact,
    create_contact,
    custom_field_names,
    employee_type_id,
    get_contact,
    home_company,
    list_companies,
    list_contact_types,
    lookup_contacts,
    restore_contact,
    to_out,
    update_contact,
)
from app.db import get_session
from app.geo import find_place, local_time_for, miles_between
from app.keep_in_touch import (
    DUE_SOON_DAYS,
    INTERVAL_LABELS,
    SNOOZE_CHOICES,
    overdue_days,
    reminder_for,
)
from app.lists import add_members, all_lists, find_or_create_list, remove_member
from app.maps import address_text, current_provider, directions_url
from app.models import Activity, Contact, Tag
from app.privacy import hidden_counts, presenting, shown_summary, shows_dates, unfiltered
from app.related import related_contacts
from app.saved_searches import clean_query, list_saved_searches
from app.schemas import ContactCreate, ContactOut, ContactUpdate
from app.search import (
    SORT_KEYS,
    SearchFilters,
    SearchHit,
    SortKey,
    active_lists,
    apply_time_query,
    distinct_values,
    last_interactions,
    query_terms,
    search,
)
from app.semantic import MeaningHit, SemanticService, search_by_meaning
from app.tags import add_tag, related_tags, remove_tag, tag_counts
from app.timephrase import CONTACTED_CHOICES, contacted_since

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


def safe_next(value: object, default: str = "/") -> str:
    """Only same-site relative paths may be redirect targets."""
    text = str(value or "")
    if text.startswith("/") and not text.startswith("//") and "\\" not in text:
        return text
    return default


def with_notice(path: str, notice: str, **params: object) -> str:
    from urllib.parse import urlencode

    joiner = "&" if "?" in path else "?"
    return f"{path}{joiner}{urlencode({'notice': notice, **params})}"


NOTICES = {
    "saved": "Saved.",
    "tagged": "Tagged {n} contact(s) with “{name}”.",
    "untagged": "Tag removed.",
    "listed": "Added {n} contact(s) to “{name}”.",
    "favorite": "Marked as favorite.",
    "unfavorite": "Removed from favorites.",
    "removed": "Removed from the list.",
    "created": "List created.",
    "backup": "Backup saved: {name}",
    "restored": "Restored from {name}. The previous data was saved first.",
    "imported": "Imported {n} contact(s).",
    "type_saved": "Contact types updated.",
    "tag_saved": "Tag updated.",
    "tag_deleted": "Tag deleted.",
    "photo_saved": "Photo saved.",
    "photo_removed": "Photo removed.",
    "activity_added": "Activity logged.",
    "activity_deleted": "Activity deleted.",
    "merged": "Merged “{name}” into this contact.",
    "dismissed": "Marked as different people.",
    "search_saved": "Saved search “{name}”.",
    "search_deleted": "Saved search deleted.",
    "search_renamed": "Saved search renamed.",
    "list_tagged": "Tagged the list “{name}”.",
    "reindexing": "Search by meaning is re-checking every contact in the background.",
    "appearance": "Appearance saved for this instance.",
    "kit_saved": "Keep-in-touch reminder saved.",
    "kit_off": "Keep-in-touch reminder turned off.",
    "snoozed": "Reminder snoozed until {name}.",
    "unsnoozed": "Snooze cancelled.",
    "kit_bulk": "Keep in touch set for {n} contact(s).",
    "kit_bulk_off": "Keep in touch turned off for {n} contact(s).",
    "logged": "Logged. The next reminder for {name} starts from today.",
    "privacy": "Privacy and presenting settings saved.",
    "maps": "Directions now open in {name}.",
    "private_on": "Marked private: hidden while presenting.",
    "private_off": "No longer private.",
    "undone": "Undone.",
    "logged_many": "Logged for {n} contact(s). Keep-in-touch reminders count from today.",
}


# ---------------------------------------------------------------- Undo (S-11, ADR-0017)


@dataclass(frozen=True)
class UndoOffer:
    """Undo for the last Log or Snooze: delete the logged activity, restore the snooze."""

    contact_id: int
    activity_id: int | None
    previous_snooze: str  # ISO date, or "" for none


def undo_params(
    contact_id: int, previous: date | None, activity_id: int | None = None
) -> dict[str, object]:
    params: dict[str, object] = {"undo": contact_id, "ps": previous.isoformat() if previous else ""}
    if activity_id is not None:
        params["ua"] = activity_id
    return params


def undo_offer(request: Request) -> UndoOffer | None:
    """The Undo button shown with a "logged" or "snoozed" notice, from the redirect's query."""
    p = request.query_params
    if p.get("notice") not in {"logged", "snoozed"}:
        return None
    contact_id, activity_id = _int(p.get("undo")), _int(p.get("ua"))
    previous = p.get("ps", "")
    if contact_id is None or (previous and _iso_date(previous) is None):
        return None
    return UndoOffer(contact_id, activity_id, previous)


def _iso_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def notice_text(request: Request) -> str | None:
    key = request.query_params.get("notice") or (
        "saved" if request.query_params.get("saved") else ""
    )
    template = NOTICES.get(key)
    if template is None:
        return None
    name = request.query_params.get("name", "")[:100]
    n = request.query_params.get("n", "")
    return template.format(n=n if n.isdigit() else "", name=name)


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def selected_ids(form: FormData) -> list[int]:
    return sorted({int(str(v)) for v in form.getlist("contact_ids") if str(v).isdigit()})


# ---------------------------------------------------------------- list & search (S-01 to S-05)


def _interaction(activity: Activity) -> tuple[str, str]:
    """("Message · Oct 2", "Sent the Q4 schedule") for a result row (S-10)."""
    kind = activity.kind.capitalize()
    summary = _clip(shown_summary(activity.summary), 140)  # P-02
    if not shows_dates():
        return kind, summary
    d = activity.occurred_on
    when = f"{d.strftime('%b')} {d.day}" + ("" if d.year == date.today().year else f", {d.year}")
    return f"{kind} · {when}", summary


def _clip(text: str, limit: int = 180) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _meaning(
    request: Request, session: Session, q: str, filters: SearchFilters, hits: list[SearchHit]
) -> tuple[list[MeaningHit], bool]:
    """S-08: matches by meaning, and whether they go before the keyword results."""
    service: SemanticService | None = getattr(request.app.state, "semantic", None)
    if not q or service is None or not service.ready:
        return [], False
    all_words = [h for h in hits if h.mode == "all"]
    exact = [h for h in hits if h.mode in {"all", "any"}]
    meaning = search_by_meaning(
        session,
        service,
        q,
        filters,
        exclude=[h.contact.id for h in all_words],
        keyword_hits=len(exact),
    )
    return meaning, bool(meaning) and not all_words


SORT_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "Best match"),
    ("name", "Name"),
    ("company", "Company"),
    ("team", "Team"),
    ("type", "Type"),
    ("last_contact", "Last contact"),
    ("updated", "Recently updated"),
)


def _private_count(session: Session, words: str, filters: SearchFilters) -> int:
    """P-04: how many private contacts this search leaves out while presenting."""
    p = presenting()
    if p is None or not p.placeholders:
        return 0
    with Session(bind=session.get_bind()) as other, unfiltered():  # never rendered
        return sum(1 for h in search(other, words, filters) if p.private_contact(h.contact))


NEAR_MILES = (10, 25, 50, 100, 250)  # S-14


@dataclass(frozen=True)
class Near:
    """S-14: where "near" is, as typed and as found."""

    text: str
    miles: int
    label: str | None = None  # "Denver, CO" or a contact's name; None when not found
    latitude: float | None = None
    longitude: float | None = None


def _near(session: Session, text: str, miles_raw: str | None) -> Near | None:
    text = " ".join(text.split())[:100]
    if not text:
        return None
    miles = int(miles_raw) if miles_raw and miles_raw.isdigit() else 50
    miles = miles if miles in NEAR_MILES else 50
    if text.startswith("contact:") and text[8:].isdigit():  # "People near" on a card
        try:
            out = to_out(get_contact(session, int(text[8:])))
        except ContactNotFound:
            return Near(text, miles)
        place = next((a for a in out.addresses if a.latitude is not None), None)
        if place is None or place.longitude is None:
            return Near(text, miles)
        return Near(text, miles, out.display_name, place.latitude, place.longitude)
    found = find_place(text)
    if found is None:
        return Near(text, miles)
    return Near(text, miles, text, found.latitude, found.longitude)


def _ids(raw: str | None) -> tuple[int, ...]:
    """S-13: "3,5,8" -> (3, 5, 8); at most 500, the rest ignored."""
    return tuple(int(v) for v in (raw or "").split(",") if v.strip().isdigit())[:500]


def _distance(c: ContactOut, near: Near) -> float | None:
    if near.latitude is None or near.longitude is None:
        return None
    miles = [
        miles_between(near.latitude, near.longitude, a.latitude, a.longitude)
        for a in c.addresses
        if a.latitude is not None and a.longitude is not None
    ]
    return min(miles) if miles else None


def _search_context(request: Request, session: Session) -> dict[str, Any]:
    # A chip's remove button submits clear=<filter> (works without JavaScript): drop it.
    cleared = set(request.query_params.getlist("clear"))
    if "near" in cleared:
        cleared.add("within")
    p = {k: v for k, v in request.query_params.items() if k not in cleared and k != "clear"}
    q = p.get("q", "").strip()[:200]
    view = "map" if p.get("view") == "map" else "list"  # S-13
    near = _near(session, p.get("near", ""), p.get("within"))  # S-14
    manager_id = _int(p.get("manager"))
    list_id = _int(p.get("list"))
    contacted = _int(p.get("contacted"))
    contacted = contacted if contacted in CONTACTED_CHOICES else None
    due = p.get("due") == "1"  # S-11
    filters = SearchFilters(
        type_id=_int(p.get("type")),
        company=p.get("company") or None,
        team=p.get("team") or None,
        manager_id=manager_id,
        tag=p.get("tag") or None,
        list_id=list_id,
        favorites=p.get("favorites") == "1",
        include_archived=p.get("archived") == "1",
        active_from=contacted_since(contacted) if contacted else None,
        due_by=date.today() + timedelta(days=DUE_SOON_DAYS) if due else None,
        ids=_ids(p.get("ids")),
        near_lat=near.latitude if near else None,
        near_lon=near.longitude if near else None,
        near_miles=near.miles if near else 50,
        unplaced=p.get("unplaced") == "1",
    )
    if near is not None and near.label is None:  # not found: match nobody, and say so
        filters = replace(filters, ids=(-1,))
    # S-10: a time phrase ("recently", "last week") becomes a period filter.
    words, period_filters, time_query = apply_time_query(q, filters)
    sort_raw = p.get("sort", "")
    default_sort: SortKey = "relevance" if words else "last_contact" if time_query else "name"
    sort: SortKey = next((k for k in SORT_KEYS if k == sort_raw), default_sort)
    # The map shows everyone who matches; the list is enough with the first 200 (N-03).
    hits = search(session, words, period_filters, sort=sort, limit=2000 if view == "map" else 200)
    meaning, meaning_first = _meaning(request, session, words, period_filters, hits)
    if meaning_first:  # keywords only matched some words: show the meaning matches first
        shown = {m.contact.id for m in meaning}
        hits = [h for h in hits if h.contact.id not in shown]
    listed = [h.contact.id for h in hits] + [m.contact.id for m in meaning]
    last_contact = (
        {cid: a.occurred_on for cid, a in last_interactions(session, listed).items()}
        if shows_dates()
        else {}
    )
    in_period = (
        last_interactions(session, listed, period_filters) if period_filters.has_period else {}
    )
    manager = None
    if manager_id is not None:
        try:
            manager = get_contact(session, manager_id)
        except ContactNotFound:
            manager = None
    list_name = next(
        (cl.name for cl, _ in all_lists(session, include_archived=True) if cl.id == list_id), None
    )
    rows = [(to_out(h.contact), h.matched, h.fuzzy, h.hidden) for h in hits]
    distances: dict[int, float] = {}
    if near is not None and near.label is not None:
        distances = {c.id: d for c, *_ in rows if (d := _distance(c, near)) is not None}
        if not sort_raw:  # nearest first unless a sort was chosen
            rows.sort(key=lambda row: distances.get(row[0].id, float("inf")))
    return {
        "q": q,
        "view": view,
        "near": near,
        "near_miles": NEAR_MILES,
        "distances": distances,
        "selected_ids": filters.ids if filters.ids != (-1,) else (),
        "map_query": request.url.include_query_params(view="map").query,
        "list_query": request.url.remove_query_params("view").query,
        "filters": filters,
        "sort": sort,
        "sort_choice": sort_raw if sort_raw in SORT_KEYS else "",
        "sort_choices": SORT_CHOICES,
        "terms": query_terms(words),
        "hits": rows,
        "private_count": _private_count(session, words, period_filters),
        "last_contact": last_contact,
        "overdue": overdue_days(session, listed, today=date.today()),  # S-11
        "in_period": {cid: _interaction(a) for cid, a in in_period.items()},
        "contacted": contacted,
        "contacted_choices": CONTACTED_CHOICES,
        "time_query": time_query,
        "today_year": date.today().year,
        "meaning": [(to_out(m.contact), m.source_label, _clip(m.text)) for m in meaning],
        "meaning_first": meaning_first,
        "types": list_contact_types(session),
        "companies": distinct_values(session, Contact.company),
        "teams": distinct_values(session, Contact.team),
        "tags": tag_counts(session),
        "lists": active_lists(session),
        "manager": manager,
        "list_name": list_name,
        "notice": notice_text(request),
        "saved": list_saved_searches(session),
        "current_query": clean_query(dict(p)),
        "related_tags": related_tags(session, filters.tag) if filters.tag else [],
    }


@router.get("/", response_class=HTMLResponse)
@router.get("/contacts", response_class=HTMLResponse)
def contact_list(request: Request, session: SessionDep) -> HTMLResponse:
    return _render(request, "contacts/list.html", _search_context(request, session))


HOME_LABELS = frozenset({"home", "personal"})
WORK_LABELS = frozenset({"work", "business", "office"})


def _kind_matches(label: str | None, kind: str) -> bool:
    name = (label or "").strip().lower()
    if kind == "home":
        return name in HOME_LABELS
    if kind == "work":
        return name in WORK_LABELS
    return True


@router.get("/map/data")
def map_data(request: Request, session: SessionDep) -> JSONResponse:
    """S-13: the people of a search (same filters as the list) as map points, with counts by
    state and country. Built from ``to_out``, so presenting mode applies (P-02)."""
    context = _search_context(request, session)
    kind = request.query_params.get("addr", "all")
    kind = kind if kind in {"home", "work"} else "all"
    points: list[dict[str, Any]] = []
    states: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    unplaced = 0
    provider = current_provider(request.app.state)
    for c, *_ in context["hits"]:
        mine = [a for a in c.addresses if _kind_matches(a.label, kind)]
        placed = [a for a in mine if a.latitude is not None and a.longitude is not None]
        if not placed:
            unplaced += 1
            continue
        for region in {state_name(a.region) for a in placed if a.country_code == "US"} - {None}:
            states[str(region)] += 1
        for numeric in {country_number(a.country_code) for a in placed} - {None}:
            countries[str(numeric)] += 1
        local = local_time_for(c.addresses)
        for a in placed:
            text = address_text(a)
            points.append(
                {
                    "id": c.id,
                    "name": c.display_name,
                    "url": f"/contacts/{c.id}",
                    "lat": a.latitude,
                    "lon": a.longitude,
                    "label": a.label or "",
                    "place": ", ".join(p for p in (a.city, a.region) if p) or a.country or "",
                    "precision": a.place_precision,
                    "time": f"{local.text} {local.abbreviation}" if local else "",
                    "directions": directions_url([text], provider),
                }
            )
    return JSONResponse(
        {
            "points": points,
            "states": dict(states),
            "countries": dict(countries),
            "people": len(context["hits"]),
            "unplaced": unplaced,
            "kind": kind,
            "near": (
                {
                    "lat": near.latitude,
                    "lon": near.longitude,
                    "miles": near.miles,
                    "label": near.label,
                }
                if (near := context["near"]) is not None and near.label is not None
                else None
            ),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/contacts/results", response_class=HTMLResponse)
def contact_results(request: Request, session: SessionDep) -> HTMLResponse:
    """The results table only — fetched while typing (S-05)."""
    return _render(request, "contacts/_results.html", _search_context(request, session))


# ---------------------------------------------------------------- selection actions (M-01)


@router.post("/selection/tag", dependencies=CsrfChecked)
async def tag_selection(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    ids = selected_ids(form)
    back = safe_next(form.get("next"))
    if not ids:
        return RedirectResponse(back, status.HTTP_303_SEE_OTHER)
    try:
        tag = add_tag(session, ids, str(form.get("tag", "")))
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    return RedirectResponse(
        with_notice(back, "tagged", n=len(ids), name=tag.name), status.HTTP_303_SEE_OTHER
    )


@router.post("/selection/list", dependencies=CsrfChecked)
async def list_selection(request: Request, session: SessionDep) -> Response:
    form = await request.form()
    ids = selected_ids(form)
    back = safe_next(form.get("next"))
    if not ids:
        return RedirectResponse(back, status.HTTP_303_SEE_OTHER)
    try:
        contact_list = find_or_create_list(session, str(form.get("list_name", "")))
        add_members(session, contact_list, ids, str(form.get("role_note", "")))
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/lists/{contact_list.id}", "listed", n=len(ids), name=contact_list.name),
        status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------- form helpers


# C-19: one address row on the form, in display order.
ADDRESS_PARTS = ("label", "street", "city", "region", "postal_code", "country")


def _row_values(form: FormData, prefix: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    columns = {f: [str(v) for v in form.getlist(f"{prefix}_{f}")] for f in fields}
    count = max((len(v) for v in columns.values()), default=0)
    return [
        {f: (columns[f][i] if i < len(columns[f]) else "") for f in fields} for i in range(count)
    ]


def parse_contact_form(
    form: FormData, *, month_first: bool = True
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn a submitted form into (model input, values to re-render the form with).

    ``month_first``: how this instance writes dates, for a typed birthday like 3/4 (C-20).
    """
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
        "linkedin_url",
        "pronunciation",
        "birthday",
    ]
    values: dict[str, Any] = {f: str(form.get(f, "")).strip() for f in scalar}
    values["manager_label"] = str(form.get("manager_label", "")).strip()
    # C-14: company comes from the dropdown, or the "add new" box.
    new_company = " ".join(str(form.get("company_new", "")).split())
    if values["company"] == NEW_COMPANY or (not values["company"] and new_company):
        values["company"] = new_company
    values["company_new"] = new_company if values["company"] == new_company else ""
    values["is_favorite"] = form.get("is_favorite") == "on"

    primary_index = str(form.get("primary_email", "0"))
    emails = _row_values(form, "email", ("address", "label"))
    for i, row in enumerate(emails):
        row["is_primary"] = str(i) == primary_index  # type: ignore[assignment]
    phones = _row_values(form, "phone", ("number", "label"))
    addresses = _row_values(form, "address", ADDRESS_PARTS)
    fields = _row_values(form, "field", ("name", "value"))
    values["emails"] = emails
    values["phones"] = phones
    values["addresses"] = addresses
    values["fields"] = fields

    data: dict[str, Any] = {f: values[f] for f in scalar}
    # C-20: read 3/4 the instance's way; an unreadable value is left for validation to flag.
    with contextlib.suppress(ValueError):
        data["birthday"] = parse_birthday(values["birthday"], month_first=month_first)
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
    # C-19: a row with only a label is dropped; anything else is validated.
    data["addresses"] = [
        dict(r) for r in addresses if any(r[k].strip() for k in ADDRESS_PARTS if k != "label")
    ]
    # C-11: a row with only a name or only a value is sent so validation can flag it.
    data["custom_fields"] = [
        {"name": r["name"], "value": r["value"]}
        for r in fields
        if r["name"].strip() or r["value"].strip()
    ]
    return data, values


NEW_COMPANY = "__new__"

FIELD_LABELS = {
    "display_name": "Display name",
    "contact_type_id": "Type",
    "emails": "Email",
    "phones": "Phone",
    "addresses": "Address",
    "custom_fields": "Field",
    "manager_id": "Manager",
    "slack_handle": "Slack handle",
    "slack_url": "Slack link",
    "teams_url": "Teams link",
    "linkedin_url": "LinkedIn profile",
    "birthday": "Birthday",
}


def errors_from_validation(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err["loc"]
        field = str(loc[0]) if loc else "__all__"
        msg = err["msg"].removeprefix("Value error, ")
        if (
            field in {"emails", "phones", "addresses", "custom_fields"}
            and len(loc) > 1
            and isinstance(loc[1], int)
        ):
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
    home: str | None = None,
) -> dict[str, Any]:
    emails = values.get("emails") or []
    phones = values.get("phones") or []
    companies = list_companies(session)
    current = values.get("company") or ""
    if current and current not in companies and not values.get("company_new"):
        companies = sorted([*companies, current], key=str.lower)
    return {
        "companies": companies,
        "new_company": NEW_COMPANY,
        "home_company": home or "",
        "employee_type_id": employee_type_id(session),
        "values": values,
        "emails": emails or [{"address": "", "label": "", "is_primary": True}],
        "phones": phones or [{"number": "", "label": ""}],
        "addresses": values.get("addresses") or [dict.fromkeys(ADDRESS_PARTS, "")],
        "fields": values.get("fields") or [{"name": "", "value": ""}],
        "field_names": custom_field_names(session),
        "types": list_contact_types(session),
        "contact_id": contact_id,
        "errors": errors or {},
    }


def _values_from_contact(contact: Contact) -> dict[str, Any]:
    out = to_out(contact, detail=True)
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
            "linkedin_url",
            "pronunciation",
        ]
    }
    values["birthday"] = Birthday.of(contact.birthday).text() if contact.birthday else ""
    values["contact_type_id"] = str(contact.contact_type_id)
    values["is_favorite"] = contact.is_favorite
    values["manager_id"] = str(contact.manager_id or "")
    values["manager_label"] = out.manager.display_name if out.manager else ""
    values["emails"] = [
        {"address": e.email, "label": e.label or "", "is_primary": e.is_primary} for e in out.emails
    ]
    values["phones"] = [{"number": p.number, "label": p.label or ""} for p in out.phones]
    values["addresses"] = [{k: getattr(a, k) or "" for k in ADDRESS_PARTS} for a in out.addresses]
    values["fields"] = [{"name": f.name, "value": f.value} for f in out.custom_fields or []]
    return values


def _home(request: Request, session: Session) -> str | None:
    return home_company(session, _settings(request).home_company)


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
    home = home_company(session, _settings(request).home_company)
    first_type = types[0].id if types else None
    values: dict[str, Any] = {
        "contact_type_id": str(first_type or ""),
        "manager_id": manager if manager.isdigit() else "",
        "manager_label": _manager_label(session, manager),
        # C-14: a new employee defaults to the home company
        "company": home if home and first_type == employee_type_id(session) else "",
    }
    return _render(request, "contacts/form.html", _form_context(session, values, home=home))


@router.post("/contacts", dependencies=CsrfChecked)
async def create_contact_form(request: Request, session: SessionDep) -> Response:
    data, values = parse_contact_form(
        await request.form(), month_first=month_first(_settings(request).phone_region)
    )
    if errors := unresolved_manager(values):
        return _render(
            request,
            "contacts/form.html",
            _form_context(session, values, errors=errors, home=_home(request, session)),
            422,
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
        return RedirectResponse(f"/contacts/{contact.id}?notice=saved", status.HTTP_303_SEE_OTHER)
    return _render(
        request,
        "contacts/form.html",
        _form_context(session, values, errors=errors, home=_home(request, session)),
        status_code=422,
    )


# ---------------------------------------------------------------- card


@router.get("/contacts/{contact_id}", response_class=HTMLResponse)
def contact_card(request: Request, contact_id: int, session: SessionDep) -> HTMLResponse:
    contact = _load(session, contact_id)
    return _render(
        request,
        "contacts/card.html",
        {
            "c": to_out(contact, detail=True),
            "kinds": KIND_LABELS,
            "today": date.today().isoformat(),
            "notice": notice_text(request),
            "all_tags": [t.name for t in tag_counts(session)],
            "all_lists": active_lists(session),
            "roles": {m.list_id: m.role_note for m in contact.memberships},
            "related": related_contacts(session, contact),
            "reminder": reminder_for(session, contact, today=date.today()),
            "kit_interval": contact.kit_interval,
            "kit_intervals": INTERVAL_LABELS,
            "snooze_choices": SNOOZE_CHOICES,
            "hidden": hidden_counts(session, contact, presenting()),  # P-02 placeholders
            "is_private": contact.is_private,
            "type_private": contact.contact_type.is_private,  # P-08
        },
    )


# ---------------------------------------------------------------- command palette (S-12)

PALETTE_LIMIT = 6


@router.get("/palette")
def palette(session: SessionDep, q: str = "") -> JSONResponse:
    """S-12: people, lists, tags and saved searches for the Ctrl/⌘ + K palette.

    Reads go through the same session as every page, so presenting mode applies (P-02).
    """
    term = " ".join(q.split())[:100]
    if not term:
        return JSONResponse({"people": [], "lists": [], "tags": [], "saved": []})
    lowered = term.lower()
    people = []
    for contact in lookup_contacts(session, term, limit=PALETTE_LIMIT):
        c = to_out(contact)
        people.append(
            {
                "id": c.id,
                "name": c.display_name,
                "sub": " · ".join(x for x in (c.title, c.company) if x),
                "url": f"/contacts/{c.id}",
            }
        )
    lists = [
        {"id": cl.id, "name": cl.name, "url": f"/lists/{cl.id}"}
        for cl in active_lists(session)
        if lowered in cl.name.lower()
    ][:PALETTE_LIMIT]
    tags = [
        {"name": t.name, "count": t.count, "url": f"/?tag={quote(t.name)}"}
        for t in tag_counts(session)
        if lowered in t.name.lower()
    ][:PALETTE_LIMIT]
    saved = [
        {"name": s.name, "url": f"/?{s.query}"}
        for s in list_saved_searches(session)
        if lowered in s.name.lower()
    ][:PALETTE_LIMIT]
    return JSONResponse({"people": people, "lists": lists, "tags": tags, "saved": saved})


@router.get("/contacts/{contact_id}/preview", response_class=HTMLResponse)
def contact_preview(request: Request, contact_id: int, session: SessionDep) -> HTMLResponse:
    """The search page's preview pane (S-02, ADR-0015): key facts without leaving the results."""
    contact = _load(session, contact_id)
    c = to_out(contact, detail=True)
    return _render(
        request,
        "contacts/_preview.html",
        {
            "c": c,
            "recent": (c.activities or [])[:PREVIEW_ACTIVITIES],
            "kinds": KIND_LABELS,
            "reminder": reminder_for(session, contact, today=date.today()),
            "hidden": hidden_counts(session, contact, presenting()),
        },
    )


PREVIEW_ACTIVITIES = 3


@router.post("/contacts/{contact_id}/favorite", dependencies=CsrfChecked)
def toggle_favorite(contact_id: int, session: SessionDep) -> Response:
    """C-10."""
    contact = _load(session, contact_id)
    contact.is_favorite = not contact.is_favorite
    session.commit()
    notice = "favorite" if contact.is_favorite else "unfavorite"
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", notice), status.HTTP_303_SEE_OTHER
    )


@router.post("/contacts/{contact_id}/tags", dependencies=CsrfChecked)
async def add_contact_tag(request: Request, contact_id: int, session: SessionDep) -> Response:
    """T-01."""
    _load(session, contact_id)
    form = await request.form()
    try:
        tag = add_tag(session, [contact_id], str(form.get("tag", "")))
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "tagged", n=1, name=tag.name),
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/contacts/{contact_id}/tags/{tag_id}/remove", dependencies=CsrfChecked)
def remove_contact_tag(contact_id: int, tag_id: int, session: SessionDep) -> Response:
    _load(session, contact_id)
    if session.get(Tag, tag_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    remove_tag(session, contact_id, tag_id)
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "untagged"), status.HTTP_303_SEE_OTHER
    )


@router.post("/contacts/{contact_id}/lists", dependencies=CsrfChecked)
async def add_contact_to_list(request: Request, contact_id: int, session: SessionDep) -> Response:
    """L-02 from the card."""
    _load(session, contact_id)
    form = await request.form()
    try:
        contact_list = find_or_create_list(session, str(form.get("list_name", "")))
        add_members(session, contact_list, [contact_id], str(form.get("role_note", "")))
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "listed", n=1, name=contact_list.name),
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/contacts/{contact_id}/lists/{list_id}/remove", dependencies=CsrfChecked)
def remove_contact_from_list(contact_id: int, list_id: int, session: SessionDep) -> Response:
    from app.lists import get_list

    try:
        contact_list = get_list(session, list_id)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "List not found") from None
    remove_member(session, contact_list, contact_id)
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "removed"), status.HTTP_303_SEE_OTHER
    )


# ---------------------------------------------------------------- edit


@router.get("/contacts/{contact_id}/edit", response_class=HTMLResponse)
def edit_contact(request: Request, contact_id: int, session: SessionDep) -> HTMLResponse:
    contact = _load(session, contact_id)
    return _render(
        request,
        "contacts/form.html",
        _form_context(
            session,
            _values_from_contact(contact),
            contact_id=contact_id,
            home=_home(request, session),
        ),
    )


@router.post("/contacts/{contact_id}/edit", dependencies=CsrfChecked)
async def update_contact_form(request: Request, contact_id: int, session: SessionDep) -> Response:
    contact = _load(session, contact_id)
    data, values = parse_contact_form(
        await request.form(), month_first=month_first(_settings(request).phone_region)
    )
    if errors := unresolved_manager(values):
        return _render(
            request,
            "contacts/form.html",
            _form_context(
                session, values, contact_id=contact_id, errors=errors, home=_home(request, session)
            ),
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
        return RedirectResponse(f"/contacts/{contact_id}?notice=saved", status.HTTP_303_SEE_OTHER)
    return _render(
        request,
        "contacts/form.html",
        _form_context(
            session, values, contact_id=contact_id, errors=errors, home=_home(request, session)
        ),
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


# ---------------------------------------------------------------- activity log (C-13)


@router.post("/contacts/{contact_id}/activities", dependencies=CsrfChecked)
async def add_activity_form(request: Request, contact_id: int, session: SessionDep) -> Response:
    before = _load(session, contact_id).kit_snoozed_until  # for Undo (S-11)
    form = await request.form()
    try:
        activity = add_activity(
            session,
            contact_id,
            kind=str(form.get("kind", "")),
            summary=str(form.get("summary", "")),
            occurred_on=parse_date(str(form.get("occurred_on", ""))),
        )
    except ContactError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from None
    session.commit()
    if form.get("next"):  # C-17 / S-11: logged from the Reconnect page or the log prompt
        contact = _load(session, contact_id)
        target = safe_next(form.get("next"), f"/contacts/{contact_id}")
        path, _, fragment = target.partition("#")
        url = with_notice(
            path,
            "logged",
            name=contact.display_name,
            **undo_params(contact_id, before, activity_id=activity.id),
        )
        return RedirectResponse(
            url + (f"#{fragment}" if fragment else ""), status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "activity_added") + "#activity-h",
        status.HTTP_303_SEE_OTHER,
    )


@router.post("/contacts/{contact_id}/undo", dependencies=CsrfChecked)
async def undo_last(request: Request, contact_id: int, session: SessionDep) -> Response:
    """S-11: undo a Log (removes that activity) or a Snooze; the earlier snooze comes back."""
    contact = _load(session, contact_id)
    form = await request.form()
    activity_id = _int(str(form.get("activity_id", "")))
    previous = str(form.get("previous_snooze", ""))
    restored = _iso_date(previous) if previous else None
    if previous and restored is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid date")
    if activity_id is not None:
        try:
            delete_activity(session, contact_id, activity_id)
        except ContactNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found") from None
    contact.kit_snoozed_until = restored
    session.commit()
    target = safe_next(form.get("next"), f"/contacts/{contact_id}")
    return RedirectResponse(with_notice(target, "undone"), status.HTTP_303_SEE_OTHER)


@router.post("/contacts/{contact_id}/activities/{activity_id}/delete", dependencies=CsrfChecked)
def delete_activity_form(contact_id: int, activity_id: int, session: SessionDep) -> Response:
    try:
        delete_activity(session, contact_id, activity_id)
    except ContactNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found") from None
    session.commit()
    return RedirectResponse(
        with_notice(f"/contacts/{contact_id}", "activity_deleted") + "#activity-h",
        status.HTTP_303_SEE_OTHER,
    )
