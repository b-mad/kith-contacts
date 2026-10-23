"""A time zone set by hand for a contact, used when no address gives one.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
Requirements: C-26 (ADR-0035)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("time_zone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("contact", "time_zone")
