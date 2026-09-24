"""Database-level guards in the initial schema (supports C-02 and C-07 in Phase 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Contact, ContactEmail, ContactPhone, ContactType


@pytest.fixture
def vendor_type(db_session: Session) -> ContactType:
    contact_type = ContactType(name="Vendor-test", sort_order=99)
    db_session.add(contact_type)
    db_session.flush()
    return contact_type


def test_contact_needs_only_a_display_name(db_session: Session, vendor_type: ContactType) -> None:
    contact = Contact(display_name="Acme rep", contact_type=vendor_type)
    db_session.add(contact)
    db_session.flush()

    loaded = db_session.scalars(select(Contact).where(Contact.id == contact.id)).one()
    assert loaded.emails == []
    assert loaded.phones == []
    assert loaded.is_favorite is False
    assert loaded.created_at is not None


def test_contact_cannot_be_its_own_manager(db_session: Session, vendor_type: ContactType) -> None:
    contact = Contact(display_name="Loop", contact_type=vendor_type)
    db_session.add(contact)
    db_session.flush()

    contact.manager_id = contact.id
    with pytest.raises(IntegrityError, match="ck_contact_not_own_manager"):
        db_session.flush()


def test_manager_and_reports_relationship(db_session: Session, vendor_type: ContactType) -> None:
    maria = Contact(display_name="Maria", contact_type=vendor_type)
    dev = Contact(display_name="Dev", contact_type=vendor_type, manager=maria)
    db_session.add_all([maria, dev])
    db_session.flush()
    db_session.refresh(maria)

    assert [r.display_name for r in maria.reports] == ["Dev"]


def test_email_unique_per_contact_ignoring_case(
    db_session: Session, vendor_type: ContactType
) -> None:
    contact = Contact(
        display_name="Pat",
        contact_type=vendor_type,
        emails=[ContactEmail(email="pat@example.com"), ContactEmail(email="PAT@example.com")],
    )
    db_session.add(contact)
    with pytest.raises(IntegrityError, match="uq_contact_email_contact_id_lower_email"):
        db_session.flush()


def test_only_one_primary_email_per_contact(db_session: Session, vendor_type: ContactType) -> None:
    contact = Contact(
        display_name="Sam",
        contact_type=vendor_type,
        emails=[
            ContactEmail(email="sam@work.example", is_primary=True),
            ContactEmail(email="sam@home.example", is_primary=True),
        ],
    )
    db_session.add(contact)
    with pytest.raises(IntegrityError, match="uq_contact_email_one_primary"):
        db_session.flush()


def test_deleting_contact_removes_emails_and_phones(
    db_session: Session, vendor_type: ContactType
) -> None:
    contact = Contact(
        display_name="Temp",
        contact_type=vendor_type,
        emails=[ContactEmail(email="t@example.com", is_primary=True)],
        phones=[ContactPhone(number="+14045550100", label="mobile")],
    )
    db_session.add(contact)
    db_session.flush()

    db_session.delete(contact)
    db_session.flush()

    assert db_session.scalars(select(ContactEmail)).all() == []
    assert db_session.scalars(select(ContactPhone)).all() == []
