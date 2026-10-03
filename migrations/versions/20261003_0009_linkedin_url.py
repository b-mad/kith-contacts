"""LinkedIn profile link on each contact.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03
Requirements: C-18 (ADR-0018)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("linkedin_url", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("contact", "linkedin_url")
