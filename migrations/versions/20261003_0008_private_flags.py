"""Private flags for presenting mode on contacts, tags, lists and extra fields.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
Requirements: P-02, P-03 (ADR-0016)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("contact", "tag", "contact_list", "custom_field")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("is_private", sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "is_private")
