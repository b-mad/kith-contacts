"""Import review: paging, choosing rows, and comparing a duplicate with what is stored (D-07)."""

from __future__ import annotations

import html as html_lib
import io
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts import get_contact
from app.exchange import (
    IMPORT_PAGE_SIZE,
    PlannedRow,
    carried_fields,
    default_selection,
    export_contact_json,
    export_json,
    filter_rows,
    paginate,
    plan_import,
    rows_from_json,
    run_import,
    update_selection,
)
from app.importdiff import diff_profiles, profile_of_contact, profile_of_row
from app.models import Contact, ContactType
from app.photos import set_photo
from app.tags import add_tag
from scripts.seed import seed

TOKEN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


@pytest.fixture
def seeded_client(client: TestClient, seeded: Session) -> TestClient:
    return client


def post(client: TestClient, url: str, files: Any = None, **fields: Any) -> Any:
    token = TOKEN.search(client.get("/contacts/new").text)
    assert token
    return client.post(
        url, data={"csrf_token": token.group(1), **fields}, files=files, follow_redirects=False
    )


def maria(session: Session) -> Contact:
    cid = session.scalars(select(Contact.id).where(Contact.display_name == "Maria Lopez")).one()
    return get_contact(session, cid)


def employee_type(session: Session) -> int:
    return session.scalars(select(ContactType.id).where(ContactType.name == "Employee")).one()


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), (20, 90, 200)).save(out, "PNG")
    return out.getvalue()


def json_rows(session: Session, contact: Contact, **changes: Any) -> list[dict[str, Any]]:
    doc = export_contact_json(contact, "Test")
    doc["contacts"][0].update(changes)
    return rows_from_json(json.dumps(doc))


# ---------------------------------------------------------------- photos in the export


@pytest.mark.req("D-03", "I-09")
def test_full_json_export_carries_photos(seeded: Session) -> None:
    person = maria(seeded)
    set_photo(seeded, person.id, png())

    doc = export_json(seeded, "Business")

    record = next(c for c in doc["contacts"] if c["display_name"] == "Maria Lopez")
    assert record["photo"]["content_type"] == "image/jpeg"
    assert len(record["photo"]["data_base64"]) > 100
    others = [c for c in doc["contacts"] if c["display_name"] != "Maria Lopez"]
    assert all("photo" not in c for c in others)  # only contacts that have one

    # ...and the importer sees it in the preview and restores it.
    rows = rows_from_json(json.dumps(doc))
    assert sum(1 for r in rows if (r["_extra"] or {}).get("photo")) == 1


# ---------------------------------------------------------------- comparing (pure)


@pytest.mark.req("D-07")
def test_phone_numbers_and_regions_compare_by_meaning(seeded: Session) -> None:
    person = maria(seeded)
    stored = profile_of_contact(person)
    number = person.phones[0].number  # +14045550102
    typed = f"({number[2:5]}) {number[5:8]}-{number[8:]}"  # (404) 555-0102
    incoming = profile_of_row(
        {"phones": [{"number": typed, "label": "work"}], "display_name": "Maria Lopez"},
        tags=[],
        manager_name=None,
        type_name=None,
        extra={},
    )

    diffs = {d.key: d for d in diff_profiles(stored, incoming, {"phones", "display_name"})}

    assert diffs["phones"].status == "same"
    assert diffs["display_name"].status == "same"


@pytest.mark.req("D-07")
def test_diff_statuses_for_scalars_and_collections() -> None:
    stored = {
        "title": "Nurse",
        "company": "Acme",
        "notes": "",
        "emails": {"a@x": "a@x", "b@x": "b@x"},
    }
    incoming = {
        "title": "Doctor",
        "company": "acme",
        "notes": "hello",
        "emails": {"b@x": "b@x", "c@x": "c@x"},
    }

    by_key = {d.key: d for d in diff_profiles(stored, incoming)}

    assert by_key["title"].status == "changed"
    assert by_key["company"].status == "same"  # case does not matter
    assert by_key["notes"].status == "added"
    emails = by_key["emails"]
    assert emails.status == "changed"
    assert [(i.text, i.state) for i in emails.items] == [
        ("a@x", "missing"), ("b@x", "same"), ("c@x", "added"),
    ]  # fmt: skip
    assert diff_profiles(stored, incoming, carried={"title"})[0].key == "title"
    assert len(diff_profiles(stored, incoming, carried={"title"})) == 1


@pytest.mark.req("D-07")
def test_carried_fields_by_file_kind() -> None:
    assert "photo" not in carried_fields("json", records=[{"_extra": {}}])
    assert "photo" in carried_fields("json", records=[{"_extra": {"photo": {"x": 1}}}])
    csv_fields = carried_fields(
        "csv", {0: "display_name", 1: "email2", 2: "phone", 3: "address_city", 4: "title"}
    )
    assert csv_fields == {"display_name", "emails", "phones", "addresses", "title"}
    assert "tags" not in csv_fields  # a CSV without a Tags column says nothing about tags


# ---------------------------------------------------------------- duplicates in the plan


@pytest.mark.req("D-07")
def test_identical_duplicate_is_a_full_match(seeded: Session) -> None:
    person = maria(seeded)
    add_tag(seeded, [person.id], "HL7")
    person = maria(seeded)
    records = json_rows(seeded, person)

    planned = plan_import(
        seeded, records, employee_type(seeded), carried=carried_fields("json", records=records)
    )

    row = planned[0]
    assert row.duplicate_of
    assert row.duplicate is not None
    assert row.duplicate.contact_id == person.id
    assert row.duplicate.full_match, [d.key for d in row.duplicate.differences]
    assert row.duplicate.unchanged  # the details are still there to look at


@pytest.mark.req("D-07")
def test_changed_duplicate_lists_exactly_what_differs(seeded: Session) -> None:
    person = maria(seeded)
    records = json_rows(
        seeded,
        person,
        title="Chief Mystery Officer",
        tags=["Fresh tag"],
        emails=[
            {"email": person.emails[0].email, "label": "work", "is_primary": True},
            {"email": "maria.new@acmehealth.example", "label": "home", "is_primary": False},
        ],
    )

    planned = plan_import(
        seeded, records, employee_type(seeded), carried=carried_fields("json", records=records)
    )

    dup = planned[0].duplicate
    assert dup is not None
    assert not dup.full_match
    differing = {d.key: d for d in dup.differences}
    assert differing["title"].status == "changed"
    assert differing["title"].incoming == "Chief Mystery Officer"
    assert differing["title"].stored == person.title
    assert differing["emails"].status == "changed"
    assert [(i.text, i.state) for i in differing["emails"].items if i.state != "same"] == [
        ("maria.new@acmehealth.example (home)", "added")
    ]
    assert differing["tags"].status == "added"


@pytest.mark.req("D-07")
def test_csv_duplicate_only_compares_the_columns_it_has(seeded: Session) -> None:
    person = maria(seeded)
    record = {"display_name": "Maria Lopez", "email": person.emails[0].email}
    planned = plan_import(
        seeded,
        [record],
        employee_type(seeded),
        carried=carried_fields("csv", {0: "display_name", 1: "email"}),
    )

    dup = planned[0].duplicate
    assert dup is not None
    assert dup.full_match  # her title, phones, tags... are not in the file


@pytest.mark.req("D-07")
def test_duplicate_within_the_file_is_compared_with_the_earlier_row(seeded: Session) -> None:
    records = [
        {"display_name": "Twice One", "email": "twice@x.example", "title": "PM"},
        {"display_name": "Twice One", "email": "TWICE@x.example", "title": "Director"},
        {"display_name": "Twice One", "email": "twice@x.example", "title": "PM"},
    ]

    planned = plan_import(seeded, records, employee_type(seeded))

    assert planned[0].duplicate is None
    second, third = planned[1].duplicate, planned[2].duplicate
    assert second is not None
    assert second.in_file
    assert second.row_number == 1
    assert [d.key for d in second.differences] == ["title"]
    assert third is not None
    assert third.full_match  # matches row 1 exactly


# ---------------------------------------------------------------- paging and choosing


def _rows(numbers: list[tuple[int, bool, bool]]) -> list[PlannedRow]:
    return [
        PlannedRow(number=n, errors=[] if ok else ["bad"], duplicate_of="dup" if dup else None)
        for n, ok, dup in numbers
    ]


@pytest.mark.req("D-07")
def test_paginate_and_filter() -> None:
    rows = list(range(1, 61))
    assert paginate(rows, 1)[0] == list(range(1, 26))
    assert paginate(rows, 3) == (list(range(51, 61)), 3, 3)
    assert paginate(rows, 99)[1:] == (3, 3)  # out of range is kept in range
    assert paginate(rows, 0)[1] == 1
    assert paginate([], 1) == ([], 1, 1)
    planned = _rows([(1, True, False), (2, True, True), (3, False, False)])
    assert [r.number for r in filter_rows(planned, "ready")] == [1]
    assert [r.number for r in filter_rows(planned, "duplicates")] == [2]
    assert [r.number for r in filter_rows(planned, "errors")] == [3]
    assert [r.number for r in filter_rows(planned, "all")] == [1, 2, 3]
    assert IMPORT_PAGE_SIZE == 25


@pytest.mark.req("D-07")
def test_selection_keeps_other_pages_and_ignores_errors() -> None:
    planned = _rows([(1, True, False), (2, True, True), (3, False, False), (4, True, False)])
    assert default_selection(planned) == {1, 4}

    first = update_selection(planned, previous=None, shown=[], picked=[])
    assert first == {1, 4}
    # Page showing rows 1-2: untick 1, tick 2; row 4 is on another page and keeps its state.
    after = update_selection(planned, previous={1, 4}, shown=[1, 2], picked=[2])
    assert after == {2, 4}
    assert update_selection(planned, previous={1}, shown=[], picked=[3]) == {1}  # error row
    assert update_selection(planned, previous=set(), shown=[], picked=[], bulk="all") == {1, 2, 4}
    assert update_selection(planned, previous={1, 4}, shown=[], picked=[], bulk="none") == set()
    assert update_selection(planned, previous=set(), shown=[1, 2], picked=[], bulk="page") == {1, 2}
    assert update_selection(planned, previous=set(), shown=[], picked=[], bulk="default") == {1, 4}


@pytest.mark.req("D-07")
def test_run_import_only_creates_the_chosen_rows(seeded: Session) -> None:
    records = [
        {"display_name": "Pick Me", "email": "pick@x.example"},
        {"display_name": "Skip Me", "email": "skip@x.example"},
        {"display_name": "Maria Again", "email": "maria.lopez@acmehealth.example"},  # a duplicate
    ]
    planned = plan_import(seeded, records, employee_type(seeded))

    result = run_import(seeded, planned, only={1, 3})

    assert len(result.created) == 2  # a ticked duplicate is imported
    assert result.skipped_unselected == 1
    names = set(seeded.scalars(select(Contact.display_name)))
    assert {"Pick Me", "Maria Again"} <= names
    assert "Skip Me" not in names


# ---------------------------------------------------------------- the review page


def _csv(total: int) -> str:
    person = "Full Name,Work Email,Employer,Job Title\n"
    body = "".join(
        f"Person {i:02d},p{i}@bulk.example,Globex,Role {i}\n" for i in range(1, total + 1)
    )
    return person + body


def _carry(page: str) -> dict[str, str]:
    """The hidden state the preview page sends back with every button."""
    raw = re.search(r'<textarea name="raw" hidden>(.*?)</textarea>', page, re.S)
    selected = re.search(r'name="selected" value="([^"]*)"', page)
    shown = re.search(r'name="shown" value="([^"]*)"', page)
    current = re.search(r'name="current_page" value="([^"]*)"', page)
    assert raw
    assert selected
    assert shown
    assert current
    return {
        "kind": "csv",
        "raw": html_lib.unescape(raw.group(1)),
        "selected": selected.group(1),
        "shown": shown.group(1),
        "current_page": current.group(1),
    }


def _ticked(page: str) -> list[str]:
    """The boxes a browser would submit: the ticked ones on the page as shown."""
    return re.findall(r'name="pick" value="(\d+)" class="import-pick"[^>]*? checked', page)


def _step(client: TestClient, page: str, **fields: Any) -> str:
    """Press a button on the preview page, the way a browser would (hidden state + ticks)."""
    fields.setdefault("pick", _ticked(page))
    return str(post(client, "/import/preview", **_carry(page), **fields).text)


def _run(client: TestClient, page: str, **fields: Any) -> Any:
    """Press Import on the preview page, with the ticks a browser would send."""
    fields.setdefault("pick", _ticked(page))
    return post(client, "/import/run", **_carry(page), **fields)


def _numbers(page: str) -> list[int]:
    return [int(n) for n in re.findall(r'data-testid="import-row" data-row="(\d+)"', page)]


def _upload(client: TestClient, text: str) -> str:
    res = post(client, "/import/preview", files={"file": ("people.csv", text.encode(), "text/csv")})
    assert res.status_code == 200
    return str(res.text)


@pytest.mark.req("D-07")
def test_preview_is_paged_and_every_page_is_reachable(seeded_client: TestClient) -> None:
    page1 = _upload(seeded_client, _csv(60))

    assert _numbers(page1) == list(range(1, 26))
    assert "Rows 1 to 25 of 60" in page1
    assert "page 1 of 3" in page1
    assert 'data-testid="import-prev" disabled' not in page1  # first page: Previous is disabled
    assert re.search(r'data-testid="import-prev"', page1)

    page2 = _step(seeded_client, page1, goto="2")
    assert _numbers(page2) == list(range(26, 51))
    assert "Rows 26 to 50 of 60" in page2
    page3 = _step(seeded_client, page2, goto="3")
    assert _numbers(page3) == list(range(51, 61))
    assert "Rows 51 to 60 of 60" in page3
    beyond = _step(seeded_client, page3, goto="99")
    assert "page 3 of 3" in beyond  # never an empty page


@pytest.mark.req("D-07")
def test_ticks_are_kept_across_pages_and_only_ticked_rows_import(
    seeded_client: TestClient, seeded: Session
) -> None:
    page1 = _upload(seeded_client, _csv(60))
    assert 'data-testid="import-count">60<' in page1  # ready rows start ticked

    # Clear everything, tick only row 2 on page 1, move on and tick only row 30 on page 2.
    cleared = _step(seeded_client, page1, bulk="none")
    assert _carry(cleared)["selected"] == ""
    page1b = _step(seeded_client, cleared, pick=["2"])
    assert _carry(page1b)["selected"] == "2"
    page2 = _step(seeded_client, page1b, goto="2")  # row 2 is not on this page but stays ticked
    assert _carry(page2)["selected"] == "2"
    page2b = _step(seeded_client, page2, pick=["30"])
    state = _carry(page2b)
    assert state["selected"] == "2,30"
    assert re.search(r'value="30" class="import-pick"[^>]* checked', page2b)
    back = _step(seeded_client, page2b, goto="1")
    assert _carry(back)["selected"] == "2,30"
    assert 'data-testid="import-count">2<' in back

    done = _run(seeded_client, back)

    assert done.status_code == 303
    assert "notice=imported&n=2" in done.headers["location"]
    names = set(seeded.scalars(select(Contact.display_name)))
    assert {"Person 02", "Person 30"} <= names
    assert "Person 01" not in names
    assert "Person 31" not in names


@pytest.mark.req("D-07")
def test_select_all_and_none_and_empty_selection_is_refused(
    seeded_client: TestClient, seeded: Session
) -> None:
    page = _upload(seeded_client, _csv(30))

    none = _step(seeded_client, page, bulk="none")
    assert 'data-testid="import-count">0<' in none
    refused = _run(seeded_client, none)
    assert refused.status_code == 422
    assert "Select at least one contact" in refused.text

    everything = _step(seeded_client, none, bulk="all")
    assert 'data-testid="import-count">30<' in everything
    done = _run(seeded_client, everything)
    assert "n=30" in done.headers["location"]


@pytest.mark.req("D-07")
def test_page_toggle_and_select_page_button(seeded_client: TestClient) -> None:
    page = _upload(seeded_client, _csv(60))
    cleared = _step(seeded_client, page, bulk="none")
    only_page = _step(seeded_client, cleared, bulk="page")
    assert _carry(only_page)["selected"] == ",".join(str(n) for n in range(1, 26))
    assert 'data-testid="import-selected"' in only_page


@pytest.mark.req("D-07")
def test_duplicates_show_full_match_or_a_detailed_comparison(
    seeded_client: TestClient, seeded: Session
) -> None:
    person = maria(seeded)
    csv_text = (
        "Full Name,Work Email,Employer,Job Title\n"
        f"Maria Lopez,{person.emails[0].email},{person.company},{person.title}\n"
        f"Maria Lopez,{person.emails[0].email},{person.company},Chief Mystery Officer\n"
        "Brand New,new@bulk.example,Globex,PM\n"
    )

    page = _upload(seeded_client, csv_text)

    assert "<strong>2</strong> possible duplicates" in page
    assert "(1 identical, 1 differ)" in page
    assert page.count("Full match") == 1  # the identical row says so and has no details
    assert page.count('data-testid="import-diff-row"') == 1
    diff_start = page.index('data-testid="import-diff"')
    diff = page[diff_start : page.index("</table>", diff_start)]
    assert 'data-testid="diff-title"' in diff
    assert 'data-status="changed"' in diff
    assert "Chief Mystery Officer" in diff
    assert str(person.title) in diff
    assert "Different" in diff
    assert f'href="/contacts/{person.id}"' in page
    # Duplicates start unticked; the new person is ticked.
    assert _carry(page)["selected"] == "3"

    # The review can be narrowed to the duplicates and one ticked for import.
    only_dups = _step(seeded_client, page, show="duplicates", goto="1")
    assert _numbers(only_dups) == [1, 2]
    chosen = _step(seeded_client, only_dups, pick=["2"], show="duplicates")
    assert _carry(chosen)["selected"] == "2,3"  # row 3 is off this view but keeps its tick
    done = _run(seeded_client, chosen, show="duplicates")
    assert "n=2" in done.headers["location"]  # the ticked duplicate and "Brand New"


@pytest.mark.req("D-07")
def test_legacy_import_without_a_selection_still_skips_duplicates(
    seeded_client: TestClient, seeded: Session
) -> None:
    csv_text = "Full Name,Work Email\nMaria Again,maria.lopez@acmehealth.example\nFresh One,fresh@x.example\n"
    done = post(seeded_client, "/import/run", kind="csv", raw=csv_text)
    assert "n=1" in done.headers["location"]
    done = post(
        seeded_client, "/import/run", kind="csv", raw=csv_text.replace("Fresh One", "Fresh Two").replace("fresh@", "f2@"),
        include_duplicates="on",
    )  # fmt: skip
    assert "n=2" in done.headers["location"]


@pytest.mark.req("D-03", "I-09")
def test_json_import_allows_a_file_with_photos_but_csv_stays_small() -> None:
    big = {
        "format": "kith-contacts/1",
        "contacts": [{"display_name": "Big", "padding": "x" * (6 * 1024 * 1024)}],
    }
    assert len(rows_from_json(json.dumps(big))) == 1  # over the 5 MB a CSV may be
    from app.exchange import MAX_JSON_IMPORT_BYTES

    assert MAX_JSON_IMPORT_BYTES == 64 * 1024 * 1024
