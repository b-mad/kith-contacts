"""Shared fixtures. Tests run against a real, throwaway PostgreSQL database (ADR-0006)."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.migrate import ensure_contact_types, upgrade_to_head

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)


# Backups made by tests go to a throwaway folder, never to ~/ContactsBackups/test, so a real
# backup's date can't show up on a page under test (Settings lists them) and tests leave no files.
TEST_BACKUP_DIR = Path(tempfile.mkdtemp(prefix="kith-test-backups-"))
atexit.register(shutil.rmtree, TEST_BACKUP_DIR, ignore_errors=True)


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "instance_name": "Test",
        "app_env": "test",
        "database_url": database_url,
        "port": 5199,
        "instance_color": "#bf3989",
        # Tests inject a fake embedder where needed; never load a real model by accident.
        "semantic_search": "off",
        "backup_dir": TEST_BACKUP_DIR,
    }
    values.update(overrides)
    return Settings.model_validate(values)  # values only; ignores env and env files


def _database_url(name: str) -> str:
    return urlsplit(ADMIN_URL)._replace(path="/" + name).geturl()


@pytest.fixture(scope="session")
def admin_url() -> str:
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            pass
    except psycopg.OperationalError as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at {ADMIN_URL}.\n"
            "Start it with `make db-up` or set TEST_DATABASE_ADMIN_URL.\n"
            f"({exc})",
            returncode=3,
        )
    return ADMIN_URL


@pytest.fixture(scope="session")
def database_url(admin_url: str) -> Iterator[str]:
    """A fresh database for this test session, migrated to head, dropped afterwards."""
    name = f"contacts_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _database_url(name)
    try:
        upgrade_to_head(make_settings(url))
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return make_settings(database_url)


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    eng = create_engine(settings.sqlalchemy_url)
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """A connection whose outer transaction is rolled back after each test."""
    with engine.connect() as conn:
        trans = conn.begin()
        yield conn
        trans.rollback()


@pytest.fixture
def db_session(connection: Connection) -> Iterator[Session]:
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture
def client(settings: Settings, db_session: Session) -> Iterator[TestClient]:
    ensure_contact_types(db_session, settings.contact_types)
    app = create_app(settings, run_migrations=False)
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
