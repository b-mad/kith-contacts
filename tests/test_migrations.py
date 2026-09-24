"""Migrations run per instance and fail fast (I-04); models and migrations stay in sync."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from psycopg import sql
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.migrate import (
    MigrationError,
    alembic_config,
    current_revision,
    ensure_contact_types,
    head_revision,
    upgrade_to_head,
)
from app.models import Base, ContactType
from tests.conftest import _database_url, make_settings

PHASE_1_TABLES = {
    "contact_type",
    "contact",
    "contact_email",
    "contact_phone",
    "tag",
    "contact_tag",
    "contact_list",
    "list_member",
}


@pytest.fixture
def scratch_settings(admin_url: str) -> Iterator[Settings]:
    """An empty database for tests that migrate up and down."""
    name = "contacts_test_migrations"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield make_settings(_database_url(name))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _engine(settings: Settings) -> Engine:
    return create_engine(settings.sqlalchemy_url)


@pytest.mark.req("I-04")
def test_upgrade_creates_schema_and_extension(scratch_settings: Settings) -> None:
    upgrade_to_head(scratch_settings)

    engine = _engine(scratch_settings)
    try:
        assert set(inspect(engine).get_table_names()) >= PHASE_1_TABLES
        assert current_revision(engine) == head_revision()
        with engine.connect() as conn:
            ext = conn.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"))
        assert ext == "pg_trgm"
    finally:
        engine.dispose()


@pytest.mark.req("I-04")
def test_upgrade_is_idempotent(scratch_settings: Settings) -> None:
    upgrade_to_head(scratch_settings)
    upgrade_to_head(scratch_settings)  # second start of the same instance is a no-op


def test_downgrade_to_base_and_upgrade_again(scratch_settings: Settings) -> None:
    cfg = alembic_config(scratch_settings.sqlalchemy_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = _engine(scratch_settings)
    try:
        assert PHASE_1_TABLES.isdisjoint(inspect(engine).get_table_names())
        command.upgrade(cfg, "head")
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()


def test_models_match_migrations(engine: Engine) -> None:
    """Autogenerate finds nothing to do: app/models.py and migrations agree."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


@pytest.mark.req("I-04")
def test_unreachable_database_raises_migration_error() -> None:
    settings = make_settings("postgresql://nobody:nothing@127.0.0.1:1/none")
    with pytest.raises(MigrationError, match="Could not migrate database for instance 'Test'"):
        upgrade_to_head(settings)


@pytest.mark.req("C-05")
def test_contact_types_seeded_once_from_settings(db_session: Session) -> None:
    db_session.execute(text("DELETE FROM contact_type"))

    inserted = ensure_contact_types(db_session, ("Family", "Friend", "Service provider"))
    again = ensure_contact_types(db_session, ("Employee",))

    names = db_session.scalars(select(ContactType.name).order_by(ContactType.sort_order)).all()
    assert inserted == 3
    assert again == 0
    assert names == ["Family", "Friend", "Service provider"]
