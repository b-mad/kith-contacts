"""Birthdays on contacts; contact types can be private.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04
Requirements: C-20, C-21, P-08 (ADR-0022)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("birthday", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_contact_birthday_format"),
        "contact",
        r"birthday ~ '^(\d{4}-|--)\d{2}-\d{2}$'",
    )
    op.create_index(
        "ix_contact_birthday_month_day",
        "contact",
        [sa.text("right(birthday, 5)")],
        postgresql_where=sa.text("birthday IS NOT NULL"),
    )
    op.add_column(
        "contact_type",
        sa.Column("is_private", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("contact_type", "is_private")
    op.drop_index("ix_contact_birthday_month_day", table_name="contact")
    op.drop_constraint(op.f("ck_contact_birthday_format"), "contact", type_="check")
    op.drop_column("contact", "birthday")
