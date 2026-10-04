"""Postal addresses per contact; the search document gains address city, region, postal
code and country (D).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04
Requirements: C-19 (ADR-0021)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of app.search's document: after this migration, and before it.
REBUILD_SQL = """
UPDATE contact AS c SET search_vector =
    setweight(to_tsvector('simple', concat_ws(' ', c.display_name, c.first_name, c.last_name,
        c.nickname)), 'A')
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
        (SELECT string_agg(a.summary, ' ') FROM activity a WHERE a.contact_id = c.id),
        (SELECT string_agg(concat_ws(' ', ad.city, ad.region, ad.postal_code, ad.country), ' ')
           FROM contact_address ad WHERE ad.contact_id = c.id))), 'D')
"""

PREVIOUS_SQL = """
UPDATE contact AS c SET search_vector =
    setweight(to_tsvector('simple', concat_ws(' ', c.display_name, c.first_name, c.last_name,
        c.nickname)), 'A')
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


def upgrade() -> None:
    op.create_table(
        "contact_address",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=True),
        sa.Column("street", sa.String(length=300), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contact.id"],
            name=op.f("fk_contact_address_contact_id_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_address")),
    )
    op.create_index(op.f("ix_contact_address_contact_id"), "contact_address", ["contact_id"])
    op.create_index(op.f("ix_contact_address_country_code"), "contact_address", ["country_code"])
    op.execute(REBUILD_SQL)


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_address_country_code"), table_name="contact_address")
    op.drop_index(op.f("ix_contact_address_contact_id"), table_name="contact_address")
    op.drop_table("contact_address")
    op.execute(PREVIOUS_SQL)
