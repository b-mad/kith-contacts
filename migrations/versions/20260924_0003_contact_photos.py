"""Contact photos stored in the database; drop the unused photo_path column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24
Requirements: C-09 (ADR-0011)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_photo",
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=30), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_contact_photo_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("contact_id", name=op.f("pk_contact_photo")),
    )
    # photo_path was reserved in 0001 but never written by the app.
    op.drop_column("contact", "photo_path")


def downgrade() -> None:
    op.add_column(
        "contact",
        sa.Column("photo_path", sa.VARCHAR(length=500), autoincrement=False, nullable=True),
    )
    op.drop_table("contact_photo")
