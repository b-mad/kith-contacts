"""Where each address is: coordinates, IANA time zone and how precisely it was placed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
Requirements: C-22 (ADR-0023)

The values come from offline data in Python (app.geo); the app fills in existing addresses
at start-up, so this migration only adds the columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contact_address", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("contact_address", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("contact_address", sa.Column("time_zone", sa.String(length=64), nullable=True))
    op.add_column(
        "contact_address", sa.Column("place_precision", sa.String(length=10), nullable=True)
    )


def downgrade() -> None:
    for column in ("place_precision", "time_zone", "longitude", "latitude"):
        op.drop_column("contact_address", column)
