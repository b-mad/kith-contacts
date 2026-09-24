"""SQLAlchemy models — data model in docs/requirements.md §6.

Migration 0001 created the Phase 1 tables; 0002 adds tags, lists and the
search vector (Phase 2).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list[ListMember]] = relationship(
        back_populates="contact_list", cascade="all, delete-orphan"
    )


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
        Index("ix_contact_search_vector", "search_vector", postgresql_using="gin"),
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
    photo_path: Mapped[str | None] = mapped_column(String(500))
    pronunciation: Mapped[str | None] = mapped_column(String(200))
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # S-01: weighted full-text document, maintained by app.search.refresh_search.
    search_vector: Mapped[str | None] = deferred(mapped_column(TSVECTOR))

    contact_type: Mapped[ContactType] = relationship()
    tags: Mapped[list[Tag]] = relationship(
        secondary=contact_tag, back_populates="contacts", order_by="Tag.name"
    )
    memberships: Mapped[list[ListMember]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
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
