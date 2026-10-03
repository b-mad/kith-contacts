"""Search by meaning: per-contact index state and embedded text chunks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
Requirements: S-08 (ADR-0013)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_doc",
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("doc_hash", sa.String(length=64), nullable=False),
        sa.Column("stale", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_semantic_doc_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("contact_id", name=op.f("pk_semantic_doc")),
    )
    op.create_table(
        "semantic_chunk",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_semantic_chunk_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_chunk")),
    )
    op.create_index(op.f("ix_semantic_chunk_contact_id"), "semantic_chunk", ["contact_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_semantic_chunk_contact_id"), table_name="semantic_chunk")
    op.drop_table("semantic_chunk")
    op.drop_table("semantic_doc")
