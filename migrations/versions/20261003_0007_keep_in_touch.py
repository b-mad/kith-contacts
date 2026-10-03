"""Keep-in-touch reminders: cadence, start date and snooze on each contact.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
Requirements: C-15, C-16, S-11 (ADR-0016)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contact", sa.Column("kit_interval", sa.String(length=3), nullable=True))
    op.add_column("contact", sa.Column("kit_started_on", sa.Date(), nullable=True))
    op.add_column("contact", sa.Column("kit_snoozed_until", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_contact_kit_interval_known"),
        "contact",
        "kit_interval IN ('2w', '1m', '3m', '6m', '1y')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_contact_kit_interval_known"), "contact", type_="check")
    op.drop_column("contact", "kit_snoozed_until")
    op.drop_column("contact", "kit_started_on")
    op.drop_column("contact", "kit_interval")
