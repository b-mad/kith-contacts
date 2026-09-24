"""Initial schema: contact types, contacts, emails, phones.

Revision ID: 0001
Revises:
Create Date: 2026-09-24
Requirements: C-01, C-02, C-03, C-05, C-06, C-07, C-08 (schema); I-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram matching for typo-tolerant search (S-03, ADR-0003). pg_trgm is a
    # trusted extension, so the instance's database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "contact_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_type")),
        sa.UniqueConstraint("name", name=op.f("uq_contact_type_name")),
    )

    op.create_table(
        "contact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("contact_type_id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("team", sa.String(length=200), nullable=True),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("works_on", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("slack_handle", sa.String(length=100), nullable=True),
        sa.Column("slack_url", sa.String(length=500), nullable=True),
        sa.Column("teams_url", sa.String(length=500), nullable=True),
        sa.Column("photo_path", sa.String(length=500), nullable=True),
        sa.Column("pronunciation", sa.String(length=200), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("manager_id <> id", name=op.f("ck_contact_not_own_manager")),
        sa.ForeignKeyConstraint(
            ["contact_type_id"],
            ["contact_type.id"],
            name=op.f("fk_contact_contact_type_id_contact_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["contact.id"],
            name=op.f("fk_contact_manager_id_contact"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact")),
    )
    op.create_index(op.f("ix_contact_contact_type_id"), "contact", ["contact_type_id"])
    op.create_index(op.f("ix_contact_manager_id"), "contact", ["manager_id"])

    op.create_table(
        "contact_email",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_contact_email_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_email")),
    )
    op.create_index(
        "uq_contact_email_contact_id_lower_email",
        "contact_email",
        ["contact_id", sa.text("lower(email)")],
        unique=True,
    )
    op.create_index(
        "uq_contact_email_one_primary",
        "contact_email",
        ["contact_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "contact_phone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_contact_phone_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_phone")),
    )
    op.create_index(op.f("ix_contact_phone_contact_id"), "contact_phone", ["contact_id"])


def downgrade() -> None:
    op.drop_table("contact_phone")
    op.drop_table("contact_email")
    op.drop_table("contact")
    op.drop_table("contact_type")
    # pg_trgm is left installed: other objects may depend on it and it holds no data.
