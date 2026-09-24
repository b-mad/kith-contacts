"""Org chart (S-06), related contacts (T-03), tag admin (T-04), types (I-08), photos (C-09)."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contact_types import add_type, delete_type, move_type, rename_type, types_with_counts
from app.contacts import ContactError, ContactNotFound, get_contact
from app.lists import add_members, create_list
from app.models import Contact, ContactPhoto, ContactType, Tag
from app.org import build_org
from app.photos import process_image, remove_photo, set_photo
from app.related import related_contacts
from app.search import search
from app.tags import add_tag, delete_tag, rename_tag, set_tag_color, tag_counts
from scripts.seed import seed


@pytest.fixture
def seeded(db_session: Session) -> Session:
    seed(db_session)
    return db_session


def cid(session: Session, name: str) -> int:
    return session.scalars(select(Contact.id).where(Contact.display_name == name)).one()


# ---------------------------------------------------------------- org chart (S-06)


@pytest.mark.req("S-06")
def test_org_chart_whole_company(seeded: Session) -> None:
    org = build_org(seeded)
    names = [r.name for r in org.roots]
    priya = next(r for r in org.roots if r.name == "Priya Raman")

    assert names[0] == "Priya Raman"  # biggest tree first
    assert {"Daniel Kim", "Paul Bennett"} <= set(names)
    assert [c.name for c in priya.children][:2] == ["Aisha Bello", "Ben Okafor"]
    maria = next(c for c in priya.children if c.name == "Maria Lopez")
    assert maria.total_reports == 5
    assert org.unplaced > 0  # customers and vendors have no org


@pytest.mark.req("S-06")
def test_org_chart_focused_up_and_down(seeded: Session) -> None:
    org = build_org(seeded, cid(seeded, "Maria Lopez"))
    assert [m.name for m in org.chain] == ["Priya Raman"]
    assert [r.name for r in org.roots] == ["Maria Lopez"]
    assert len(org.roots[0].children) == 5

    leaf = build_org(seeded, cid(seeded, "Dev Patel"))
    assert [m.name for m in leaf.chain] == ["Priya Raman", "Maria Lopez"]
    assert leaf.roots[0].children == []


def test_org_chart_unknown_focus_falls_back(seeded: Session) -> None:
    assert build_org(seeded, 999_999).focus_id is None


# ---------------------------------------------------------------- related contacts (T-03)


@pytest.mark.req("T-03")
def test_related_contacts_rank_shared_context(seeded: Session) -> None:
    dev, yuki, chen = (cid(seeded, n) for n in ("Dev Patel", "Yuki Tanaka", "Chen Wei"))
    add_tag(seeded, [dev, yuki], "HL7")
    add_tag(seeded, [dev, yuki], "LIS")
    project = create_list(seeded, "Q4 LIS")
    add_members(seeded, project, [dev, yuki])

    related = related_contacts(seeded, get_contact(seeded, dev))
    top = related[0]

    assert top.contact.display_name == "Yuki Tanaka"  # 2 tags + a list beat same team
    assert top.reasons[:2] == ["tags HL7, LIS", "list Q4 LIS"]
    teammates = {r.contact.display_name: r.reasons for r in related}
    assert "same team" in teammates["Chen Wei"]
    assert "same manager" in teammates["Chen Wei"]
    assert "Maria Lopez" not in teammates  # the manager is already on the card
    assert chen in [r.contact.id for r in related]


def test_related_ignores_big_companies_but_uses_small_ones(seeded: Session) -> None:
    rob = get_contact(seeded, cid(seeded, "Robert Lin"))
    reasons = {r.contact.display_name: r.reasons for r in related_contacts(seeded, rob)}
    assert reasons["Sofia Rossi"] == ["same company"]  # Peachtree Labs is small
    kwame = get_contact(seeded, cid(seeded, "Kwame Mensah"))
    assert all("same company" not in r.reasons for r in related_contacts(seeded, kwame))


# ---------------------------------------------------------------- tag admin (T-04)


@pytest.mark.req("T-04")
def test_rename_tag_updates_search(seeded: Session) -> None:
    dev = cid(seeded, "Dev Patel")
    tag = add_tag(seeded, [dev], "HL7")
    rename_tag(seeded, tag, "Wallaby")
    assert [h.contact.id for h in search(seeded, "wallaby") if not h.fuzzy] == [dev]


@pytest.mark.req("T-04")
def test_rename_into_existing_tag_merges(seeded: Session) -> None:
    dev, yuki, rob = (cid(seeded, n) for n in ("Dev Patel", "Yuki Tanaka", "Robert Lin"))
    keep = add_tag(seeded, [dev, yuki], "HL7")
    old = add_tag(seeded, [yuki, rob], "hl-7")

    merged = rename_tag(seeded, old, "hl7")

    assert merged.id == keep.id
    assert seeded.get(Tag, old.id) is None
    counts = {t.name: t.count for t in tag_counts(seeded)}
    assert counts == {"HL7": 3}


@pytest.mark.req("T-04")
def test_delete_tag_and_colors(seeded: Session) -> None:
    dev = cid(seeded, "Dev Patel")
    tag = add_tag(seeded, [dev], "Temp")
    set_tag_color(seeded, tag, "teal")
    assert tag_counts(seeded)[0].color == "teal"
    with pytest.raises(ContactError):
        set_tag_color(seeded, tag, "#ff0000")  # only palette colors (CSP-safe classes)
    assert delete_tag(seeded, tag) == 1
    assert all(h.contact.id != dev for h in search(seeded, "temp"))
    assert get_contact(seeded, dev).tags == []


# ---------------------------------------------------------------- contact types (I-08)


@pytest.mark.req("I-08", "C-05")
def test_type_admin(db_session: Session) -> None:
    family = add_type(db_session, "  Family ")
    friend = add_type(db_session, "Friend")
    with pytest.raises(ContactError, match="already exists"):
        add_type(db_session, "family")
    rename_type(db_session, friend.id, "Close friend")
    move_type(db_session, friend.id, -1)

    names = [t.name for t, _ in types_with_counts(db_session)]
    assert names.index("Close friend") < names.index("Family")

    db_session.add(Contact(display_name="Mom", contact_type_id=family.id))
    db_session.flush()
    with pytest.raises(ContactError, match="choose a type to move them to"):
        delete_type(db_session, family.id)
    assert delete_type(db_session, family.id, move_to_id=friend.id) == 1
    mom = db_session.scalars(select(Contact).where(Contact.display_name == "Mom")).one()
    assert mom.contact_type_id == friend.id
    with pytest.raises(ContactNotFound):
        rename_type(db_session, 999_999, "x")
    with pytest.raises(ContactError):
        delete_type(db_session, friend.id, move_to_id=friend.id)


def test_cannot_delete_last_type(db_session: Session) -> None:
    for t in db_session.scalars(select(ContactType)).all():
        db_session.delete(t)
    db_session.flush()
    only = add_type(db_session, "Only")
    with pytest.raises(ContactError, match="at least one"):
        delete_type(db_session, only.id)


# ---------------------------------------------------------------- photos (C-09)


def image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (1600, 900), mode: str = "RGB") -> bytes:
    img = Image.new(mode, size, (200, 30, 90) if mode == "RGB" else (200, 30, 90, 128))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    out = io.BytesIO()
    img.save(out, fmt, **({"exif": exif} if fmt == "JPEG" else {}))
    return out.getvalue()


@pytest.mark.req("C-09")
def test_photo_is_resized_and_stripped(seeded: Session) -> None:
    dev = cid(seeded, "Dev Patel")
    photo = set_photo(seeded, dev, image_bytes())

    with Image.open(io.BytesIO(photo.data)) as stored:
        assert stored.size == (512, 288)
        assert stored.format == "JPEG"
        assert not stored.getexif()  # metadata removed
    assert photo.content_type == "image/jpeg"
    assert get_contact(seeded, dev).photo is not None

    transparent = set_photo(seeded, dev, image_bytes("PNG", (100, 100), "RGBA"))
    assert transparent.content_type == "image/png"
    remove_photo(seeded, dev)
    assert seeded.get(ContactPhoto, dev) is None
    remove_photo(seeded, dev)  # removing twice is harmless


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "Choose an image"),
        (b"not an image", "not an image"),
        (b"x" * (10 * 1024 * 1024 + 1), "10 MB"),
    ],
)
def test_bad_photos_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ContactError, match=message):
        process_image(data)


def test_unsupported_image_format_rejected() -> None:
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(out, "BMP")
    with pytest.raises(ContactError, match="JPEG, PNG"):
        process_image(out.getvalue())
