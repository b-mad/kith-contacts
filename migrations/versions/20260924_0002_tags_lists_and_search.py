"""Tags, project lists and the context-search vector.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
Requirements: T-01, T-02, L-01 to L-04, S-01 to S-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Frozen copy of app.search's document at the time of this migration, used to
# backfill existing contacts. Later changes to the document need a new migration.
BACKFILL_SQL = """
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

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_list",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name=op.f("ck_contact_list_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_list")),
    )
    op.create_index(
        "uq_contact_list_lower_name",
        "contact_list",
        [sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag")),
    )
    op.create_index("uq_tag_lower_name", "tag", [sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "contact_tag",
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_contact_tag_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name=op.f("fk_contact_tag_tag_id_tag"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("contact_id", "tag_id", name=op.f("pk_contact_tag")),
    )
    op.create_index(op.f("ix_contact_tag_tag_id"), "contact_tag", ["tag_id"], unique=False)
    op.create_table(
        "list_member",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("role_note", sa.String(length=200), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_list_member_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["contact_list.id"],
            name=op.f("fk_list_member_list_id_contact_list"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "contact_id", name=op.f("pk_list_member")),
    )
    op.create_index(op.f("ix_list_member_contact_id"), "list_member", ["contact_id"], unique=False)
    op.add_column("contact", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    op.create_index(
        "ix_contact_display_name_trgm",
        "contact",
        [sa.literal_column("lower(display_name)")],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"lower(display_name)": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_contact_search_vector",
        "contact",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    # Existing contacts (e.g. entries made in Phase 1) become searchable immediately.
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.drop_index("ix_contact_search_vector", table_name="contact", postgresql_using="gin")
    op.drop_index(
        "ix_contact_display_name_trgm",
        table_name="contact",
        postgresql_using="gin",
        postgresql_ops={"lower(display_name)": "gin_trgm_ops"},
    )
    op.drop_column("contact", "search_vector")
    op.drop_index(op.f("ix_list_member_contact_id"), table_name="list_member")
    op.drop_table("list_member")
    op.drop_index(op.f("ix_contact_tag_tag_id"), table_name="contact_tag")
    op.drop_table("contact_tag")
    op.drop_index("uq_tag_lower_name", table_name="tag")
    op.drop_table("tag")
    op.drop_index("uq_contact_list_lower_name", table_name="contact_list")
    op.drop_table("contact_list")
