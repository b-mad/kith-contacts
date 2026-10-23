"""A record of exports: when, what kind and which choices, with no contact data.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23
Requirements: D-10 (ADR-0034)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("contact_count", sa.Integer(), nullable=False),
        sa.Column("include_private", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("encrypted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("detail", sa.String(length=300), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("export_log")
