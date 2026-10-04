"""Run database migrations for one instance (requirement I-04)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.backup import BackupError, BackupFile, backup
from app.config import Settings
from app.models import ContactType

ROOT = Path(__file__).resolve().parent.parent


class MigrationError(RuntimeError):
    """Raised when the database cannot be brought to the latest schema."""


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    # ConfigParser treats "%" as interpolation; escape it for passwords.
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def pending_from(settings: Settings) -> str | None:
    """The revision an existing schema would be upgraded from, or None (new or up to date)."""
    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    try:
        current = current_revision(engine)
    finally:
        engine.dispose()
    if current is None or current == head_revision():
        return None
    return current


def backup_before_upgrade(settings: Settings) -> BackupFile | None:
    """I-11: a production instance backs up before migrating an existing schema.

    Refuses (MigrationError) when that backup fails, so the upgrade never runs unprotected.
    """
    if not settings.is_production:
        return None
    try:
        if pending_from(settings) is None:
            return None
        return backup(settings, label="before-upgrade")
    except (BackupError, OSError, SQLAlchemyError) as exc:
        raise MigrationError(
            f"Not upgrading instance '{settings.instance_name}': "
            f"the backup before upgrading failed: {exc}"
        ) from exc


def upgrade_to_head(settings: Settings) -> BackupFile | None:
    """Apply all pending migrations; raise MigrationError on any failure.

    Returns the before-upgrade backup when one was taken (I-11).
    """
    safety = backup_before_upgrade(settings)
    try:
        command.upgrade(alembic_config(settings.sqlalchemy_url), "head")
    except Exception as exc:
        raise MigrationError(
            f"Could not migrate database for instance '{settings.instance_name}': {exc}"
        ) from exc
    return safety


def ensure_contact_types(session: Session, names: tuple[str, ...]) -> int:
    """Seed the instance's contact types when the table is empty (C-05).

    Returns the number of types inserted. Once types exist they are managed
    in the app (I-08), so the env file only sets the initial list.
    """
    if session.scalar(select(ContactType.id).limit(1)) is not None:
        return 0
    session.add_all(ContactType(name=name, sort_order=i) for i, name in enumerate(names))
    session.commit()
    return len(names)


def head_revision() -> str:
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config("postgresql://unused")).get_current_head()
    if head is None:  # pragma: no cover - there is always at least one migration
        raise MigrationError("No migrations found")
    return head


def current_revision(engine: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
