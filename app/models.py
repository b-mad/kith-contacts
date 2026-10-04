"""SQLAlchemy models — data model in docs/requirements.md §6.

Migration 0001 created the Phase 1 tables; 0002 adds tags, lists and the
search vector (Phase 2); 0003 photos (Phase 3); 0004 custom fields, activities,
saved searches, list tags, duplicate dismissals and merge snapshots (Phase 4);
0005 search by meaning (Phase 5); 0006 per-instance app settings (Phase 6);
0007 keep-in-touch reminders (Phase 7); 0008 private flags for presenting mode (Phase 7).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship

# Deterministic constraint names keep Alembic migrations stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ContactType(Base):
    """Per-instance list of contact types (C-05, I-08)."""

    __tablename__ = "contact_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # P-08: while presenting, every contact of a private type is withheld (ADR-0022).
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


list_tag = Table(
    "list_tag",
    Base.metadata,
    Column("list_id", ForeignKey("contact_list.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True),
)

contact_tag = Table(
    "contact_tag",
    Base.metadata,
    Column("contact_id", ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Tag(Base):
    """Free-form label (T-01). Names are unique ignoring case."""

    __tablename__ = "tag"
    __table_args__ = (Index("uq_tag_lower_name", func.lower(text("name")), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(7))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # P-03

    contacts: Mapped[list[Contact]] = relationship(secondary=contact_tag, back_populates="tags")


class ContactList(Base):
    """A project list (L-01)."""

    __tablename__ = "contact_list"
    __table_args__ = (
        Index("uq_contact_list_lower_name", func.lower(text("name")), unique=True),
        CheckConstraint("status IN ('active', 'archived')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # P-03
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list[ListMember]] = relationship(
        back_populates="contact_list", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=list_tag, order_by="Tag.name")


class ListMember(Base):
    """Membership of a contact in a list, with a per-project role note (L-02, L-03)."""

    __tablename__ = "list_member"

    list_id: Mapped[int] = mapped_column(
        ForeignKey("contact_list.id", ondelete="CASCADE"), primary_key=True
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role_note: Mapped[str | None] = mapped_column(String(200))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contact_list: Mapped[ContactList] = relationship(back_populates="members")
    contact: Mapped[Contact] = relationship(back_populates="memberships")


class Contact(Base):
    __tablename__ = "contact"
    __table_args__ = (
        CheckConstraint("manager_id <> id", name="not_own_manager"),
        CheckConstraint(r"birthday ~ '^(\d{4}-|--)\d{2}-\d{2}$'", name="birthday_format"),
        CheckConstraint(
            "kit_interval IN ('2w', '1m', '3m', '6m', '1y')", name="kit_interval_known"
        ),
        Index("ix_contact_search_vector", "search_vector", postgresql_using="gin"),
        # C-21: Reconnect looks birthdays up by month and day.
        Index(
            "ix_contact_birthday_month_day",
            func.right(text("birthday"), 5),
            postgresql_where=text("birthday IS NOT NULL"),
        ),
        Index(
            "ix_contact_display_name_trgm",
            func.lower(text("display_name")),
            postgresql_using="gin",
            postgresql_ops={"lower(display_name)": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    nickname: Mapped[str | None] = mapped_column(String(100))
    contact_type_id: Mapped[int] = mapped_column(
        ForeignKey("contact_type.id", ondelete="RESTRICT"), index=True
    )
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("contact.id", ondelete="SET NULL"), index=True
    )
    works_on: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    slack_handle: Mapped[str | None] = mapped_column(String(100))
    slack_url: Mapped[str | None] = mapped_column(String(500))
    teams_url: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))  # C-18, migration 0009
    # C-20: "YYYY-MM-DD", or "--MM-DD" without a year (ADR-0022, migration 0011).
    birthday: Mapped[str | None] = mapped_column(String(10))
    pronunciation: Mapped[str | None] = mapped_column(String(200))
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Keep-in-touch reminders (C-15, C-16, ADR-0016). The due date is computed, never stored.
    kit_interval: Mapped[str | None] = mapped_column(String(3))  # None = off
    kit_started_on: Mapped[date | None] = mapped_column(Date)
    kit_snoozed_until: Mapped[date | None] = mapped_column(Date)
    # P-03: a private contact is left out of everything while presenting (ADR-0016).
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # S-01: weighted full-text document, maintained by app.search.refresh_search.
    search_vector: Mapped[str | None] = deferred(mapped_column(TSVECTOR))

    contact_type: Mapped[ContactType] = relationship()
    tags: Mapped[list[Tag]] = relationship(
        secondary=contact_tag, back_populates="contacts", order_by="Tag.name"
    )
    memberships: Mapped[list[ListMember]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
    photo: Mapped[ContactPhoto | None] = relationship(cascade="all, delete-orphan")
    manager: Mapped[Contact | None] = relationship(
        remote_side="Contact.id", back_populates="reports"
    )
    reports: Mapped[list[Contact]] = relationship(back_populates="manager")
    emails: Mapped[list[ContactEmail]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
    phones: Mapped[list[ContactPhone]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
    addresses: Mapped[list[ContactAddress]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", order_by="ContactAddress.id"
    )
    custom_fields: Mapped[list[CustomField]] = relationship(
        cascade="all, delete-orphan", order_by="CustomField.sort_order, CustomField.id"
    )
    activities: Mapped[list[Activity]] = relationship(
        cascade="all, delete-orphan",
        order_by="Activity.occurred_on.desc(), Activity.id.desc()",
    )


class ContactPhoto(Base):
    """C-09: one photo per contact, stored in the database so backups include it (ADR-0011)."""

    __tablename__ = "contact_photo"

    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(30))
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ContactEmail(Base):
    __tablename__ = "contact_email"
    __table_args__ = (
        Index(
            "uq_contact_email_contact_id_lower_email",
            "contact_id",
            func.lower(text("email")),
            unique=True,
        ),
        Index(
            "uq_contact_email_one_primary",
            "contact_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    label: Mapped[str | None] = mapped_column(String(50))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    contact: Mapped[Contact] = relationship(back_populates="emails")


class ContactPhone(Base):
    __tablename__ = "contact_phone"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(50))

    contact: Mapped[Contact] = relationship(back_populates="phones")


class ContactAddress(Base):
    """C-19: a postal address; country and region normalised on save (ADR-0021)."""

    __tablename__ = "contact_address"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str | None] = mapped_column(String(50))
    street: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    # C-22: where it is, from offline data (ADR-0023); NULL precision = not looked up yet.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    time_zone: Mapped[str | None] = mapped_column(String(64))
    place_precision: Mapped[str | None] = mapped_column(String(10))

    contact: Mapped[Contact] = relationship(back_populates="addresses")


class CustomField(Base):
    """C-11: a key/value pair on a contact (ADR-0012)."""

    __tablename__ = "custom_field"
    __table_args__ = (
        Index(
            "uq_custom_field_contact_id_lower_name",
            "contact_id",
            func.lower(text("name")),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(500))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # P-03
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


ACTIVITY_KINDS = ("meeting", "call", "email", "message", "note")


class Activity(Base):
    """C-13: a dated interaction note (ADR-0012)."""

    __tablename__ = "activity"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('meeting', 'call', 'email', 'message', 'note')", name="kind_valid"
        ),
        Index("ix_activity_contact_id_occurred_on", "contact_id", "occurred_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    occurred_on: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedSearch(Base):
    """S-07: a named search-page query string (ADR-0012)."""

    __tablename__ = "saved_search"
    __table_args__ = (Index("uq_saved_search_lower_name", func.lower(text("name")), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DuplicateDismissal(Base):
    """C-12: a pair the user marked "not a duplicate"; stored with contact_a < contact_b."""

    __tablename__ = "duplicate_dismissal"
    __table_args__ = (CheckConstraint("contact_a < contact_b", name="ordered"),)

    contact_a: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True
    )
    contact_b: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ContactMerge(Base):
    """C-12: JSON snapshot of a contact removed by a merge, so it can be recovered."""

    __tablename__ = "contact_merge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kept_id: Mapped[int | None] = mapped_column(
        ForeignKey("contact.id", ondelete="SET NULL"), index=True
    )
    merged_name: Mapped[str] = mapped_column(String(200))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SemanticDoc(Base):
    """S-08: one row per contact indexed for search by meaning (ADR-0013)."""

    __tablename__ = "semantic_doc"

    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(100))
    doc_hash: Mapped[str] = mapped_column(String(64))
    stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SemanticChunk(Base):
    """S-08: a short text from a contact and its embedding (float32 bytes)."""

    __tablename__ = "semantic_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class AppSetting(Base):
    """A-03: one per-instance preference, e.g. theme = "dark" (ADR-0015)."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
