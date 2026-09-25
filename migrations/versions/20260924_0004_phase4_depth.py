"""Custom fields, activities, saved searches, list tags, duplicate dismissals, merge
snapshots; search document gains custom fields (C) and activity summaries (D).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
Requirements: C-11, C-12, C-13, S-07, L-05, S-01 (ADR-0012)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.search's document: after this migration, and before it.
REBUILD_SQL = """
UPDATE contact AS c SET search_vector =
    setweight(to_tsvector('simple', concat_ws(' ', c.display_name, c.first_name,
        c.last_name, c.nickname)), 'A')
    || setweight(to_tsvector('simple', concat_ws(' ', c.team, c.company,
        (SELECT m.display_name FROM contact m WHERE m.id = c.manager_id),
        (SELECT string_agg(t.name, ' ') FROM contact_tag ct JOIN tag t ON t.id = ct.tag_id
          WHERE ct.contact_id = c.id))), 'B')
    || setweight(to_tsvector('simple', concat_ws(' ', c.title, c.department, c.works_on,
        (SELECT string_agg(cl.name, ' ') FROM list_member lm
           JOIN contact_list cl ON cl.id = lm.list_id WHERE lm.contact_id = c.id),
        (SELECT string_agg(ce.email || ' ' || translate(ce.email, '.@_-+', '     '), ' ')
           FROM contact_email ce WHERE ce.contact_id = c.id),
        (SELECT string_agg(cf.name || ' ' || cf.value, ' ')
           FROM custom_field cf WHERE cf.contact_id = c.id))), 'C')
    || setweight(to_tsvector('simple', concat_ws(' ', c.notes, c.location,
        (SELECT string_agg(a.summary, ' ') FROM activity a WHERE a.contact_id = c.id))), 'D')
"""

PREVIOUS_SQL = """
UPDATE contact AS c SET search_vector =
    setweight(to_tsvector('simple', concat_ws(' ', c.display_name, c.first_name,
        c.last_name, c.nickname)), 'A')
    || setweight(to_tsvector('simple', concat_ws(' ', c.team, c.company,
        (SELECT m.display_name FROM contact m WHERE m.id = c.manager_id),
        (SELECT string_agg(t.name, ' ') FROM contact_tag ct JOIN tag t ON t.id = ct.tag_id
          WHERE ct.contact_id = c.id))), 'B')
    || setweight(to_tsvector('simple', concat_ws(' ', c.title, c.department, c.works_on,
        (SELECT string_agg(cl.name, ' ') FROM list_member lm
           JOIN contact_list cl ON cl.id = lm.list_id WHERE lm.contact_id = c.id),
        (SELECT string_agg(ce.email || ' ' || translate(ce.email, '.@_-+', '     '), ' ')
           FROM contact_email ce WHERE ce.contact_id = c.id))), 'C')
    || setweight(to_tsvector('simple', concat_ws(' ', c.notes, c.location)), 'D')
"""


def upgrade() -> None:
    op.create_table(
        "custom_field",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_custom_field_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_field")),
    )
    op.create_index(
        "uq_custom_field_contact_id_lower_name",
        "custom_field",
        ["contact_id", sa.literal_column("lower(name)")],
        unique=True,
    )

    op.create_table(
        "activity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('meeting', 'call', 'email', 'message', 'note')",
            name=op.f("ck_activity_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_activity_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity")),
    )
    op.create_index("ix_activity_contact_id_occurred_on", "activity", ["contact_id", "occurred_on"])

    op.create_table(
        "saved_search",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_search")),
    )
    op.create_index(
        "uq_saved_search_lower_name",
        "saved_search",
        [sa.literal_column("lower(name)")],
        unique=True,
    )

    op.create_table(
        "list_tag",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["contact_list.id"],
            name=op.f("fk_list_tag_list_id_contact_list"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name=op.f("fk_list_tag_tag_id_tag"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("list_id", "tag_id", name=op.f("pk_list_tag")),
    )
    op.create_index(op.f("ix_list_tag_tag_id"), "list_tag", ["tag_id"])

    op.create_table(
        "duplicate_dismissal",
        sa.Column("contact_a", sa.Integer(), nullable=False),
        sa.Column("contact_b", sa.Integer(), nullable=False),
        sa.CheckConstraint("contact_a < contact_b", name=op.f("ck_duplicate_dismissal_ordered")),
        sa.ForeignKeyConstraint(
            ["contact_a"],
            ["contact.id"],
            name=op.f("fk_duplicate_dismissal_contact_a_contact"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_b"],
            ["contact.id"],
            name=op.f("fk_duplicate_dismissal_contact_b_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("contact_a", "contact_b", name=op.f("pk_duplicate_dismissal")),
    )
    op.create_index(op.f("ix_duplicate_dismissal_contact_b"), "duplicate_dismissal", ["contact_b"])

    op.create_table(
        "contact_merge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kept_id", sa.Integer(), nullable=True),
        sa.Column("merged_name", sa.String(length=200), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "merged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["kept_id"],
            ["contact.id"],
            name=op.f("fk_contact_merge_kept_id_contact"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_merge")),
    )
    op.create_index(op.f("ix_contact_merge_kept_id"), "contact_merge", ["kept_id"])

    op.execute(REBUILD_SQL)


def downgrade() -> None:
    op.drop_table("contact_merge")
    op.drop_table("duplicate_dismissal")
    op.drop_table("list_tag")
    op.drop_table("saved_search")
    op.drop_table("activity")
    op.drop_table("custom_field")
    op.execute(PREVIOUS_SQL)
