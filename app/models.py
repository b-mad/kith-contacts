"""SQLAlchemy models — data model in docs/requirements.md §6.

Phase 0 creates the Phase 1 tables. Tags, lists and the search vector arrive
in Phase 2 with their own migrations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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


class Contact(Base):
    __tablename__ = "contact"
    __table_args__ = (CheckConstraint("manager_id <> id", name="not_own_manager"),)

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

    contact_type: Mapped[ContactType] = relationship()
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
