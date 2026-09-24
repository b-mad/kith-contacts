"""Backups, restore, retention and prod→dev copy (D-04, I-06, I-07, N-06).

These run pg_dump/pg_restore for real against an instance created by the
bootstrap script, so the restore runs as a non-superuser exactly as on the Mac.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app import backup as backup_module
from app.backup import (
    BackupError,
    BackupFile,
    Connection,
    backup,
    dump_command,
    ensure_recent_backup,
    find_backup,
    list_backups,
    prune,
    resolve_tool,
    restore,
    restore_command,
)
from app.config import Settings
from app.db import create_db_engine, make_session_factory
from app.migrate import ensure_contact_types, upgrade_to_head
from app.models import Contact, ContactPhoto
from scripts import backup as cli
from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
from scripts.seed import seed
from tests.conftest import make_settings


def _instance(
    admin_url: str, tmp_path: Path, env: str = "development"
) -> tuple[InstanceSpec, Settings]:
    spec = InstanceSpec(name=f"tb-{uuid.uuid4().hex[:6]}", port=5195, app_env="test")
    info = bootstrap(spec, admin_url, None)
    settings = make_settings(
        info.database_url,
        instance_name=spec.name,
        app_env=env,
        backup_dir=str(tmp_path / "backups"),
    )
    upgrade_to_head(settings)
    return spec, settings


@pytest.fixture
def instance(admin_url: str, tmp_path: Path) -> Iterator[Settings]:
    spec, settings = _instance(admin_url, tmp_path)
    yield settings
    drop_database(spec, admin_url)


def count_contacts(settings: Settings) -> int:
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            return int(session.scalar(select(func.count()).select_from(Contact)) or 0)
    finally:
        engine.dispose()


def add_sample_data(settings: Settings) -> None:
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            ensure_contact_types(session, settings.contact_types)
            seed(session)
            first = session.scalars(select(Contact.id).order_by(Contact.id)).first()
            session.add(
                ContactPhoto(contact_id=first, content_type="image/jpeg", data=b"\xff\xd8photo")
            )
            session.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------- round trip


@pytest.mark.req("D-04", "I-06")
def test_backup_and_restore_round_trip(instance: Settings) -> None:
    add_sample_data(instance)
    made = backup(instance)

    assert made.path.parent == instance.resolved_backup_dir
    assert made.name.startswith(instance.instance_slug + "_")
    assert made.size > 1000
    assert oct(made.path.stat().st_mode & 0o777) == "0o600"

    # lose data, then restore
    engine = create_db_engine(instance)
    with make_session_factory(engine)() as session:
        session.execute(delete(Contact))
        session.commit()
    engine.dispose()
    assert count_contacts(instance) == 0

    safety = restore(instance, made.path)
    upgrade_to_head(instance)

    assert count_contacts(instance) == 50
    assert "before-restore" in safety.name  # the emptied state was kept, just in case
    engine = create_db_engine(instance)
    with make_session_factory(engine)() as session:
        photo = session.scalars(select(ContactPhoto)).one()
        assert photo.data == b"\xff\xd8photo"  # photos are inside the backup (ADR-0011)
        assert session.scalar(select(func.count()).where(Contact.search_vector.is_not(None))) == 50
    engine.dispose()


def test_restore_rejects_missing_or_invalid_files(instance: Settings, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="not found"):
        restore(instance, tmp_path / "nope.dump")
    bogus = tmp_path / "bogus.dump"
    bogus.write_bytes(b"not a dump")
    with pytest.raises(BackupError, match="Not a valid backup"):
        restore(instance, bogus)


def test_failed_dump_leaves_no_partial_file(instance: Settings) -> None:
    broken = make_settings(
        str(instance.database_url).replace("contacts_", "missing_", 1),
        instance_name=instance.instance_name,
        backup_dir=str(instance.resolved_backup_dir),
    )  # auto: local pg_dump where installed, else docker (e.g. a Mac without libpq)
    with pytest.raises(BackupError, match=r"failed|Cannot connect|No usable pg_dump"):
        backup(broken)
    assert list(instance.resolved_backup_dir.glob("*.dump")) == []


@pytest.mark.req("D-04")
def test_missing_pg_dump_gives_a_clear_error(
    instance: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    forced = make_settings(
        str(instance.database_url),
        instance_name=instance.instance_name,
        backup_dir=str(instance.resolved_backup_dir),
        backup_tool="local",
    )
    monkeypatch.setenv("PATH", "")
    with pytest.raises(BackupError, match=r"pg_dump not found.*BACKUP_TOOL=docker"):
        backup(forced)
    assert list(instance.resolved_backup_dir.glob("*.dump")) == []


@pytest.mark.req("D-04")
def test_invalid_file_is_rejected_before_any_safety_backup(
    instance: Settings, tmp_path: Path
) -> None:
    bogus = tmp_path / "bogus.dump"
    bogus.write_bytes(b"PGDM")  # truncated signature
    with pytest.raises(BackupError, match="Not a valid backup"):
        restore(instance, bogus)
    assert list(instance.resolved_backup_dir.glob("*before-restore*.dump")) == []


# ---------------------------------------------------------------- retention (N-06)


def _fake(settings: Settings, when: datetime) -> Path:
    folder = settings.resolved_backup_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{settings.instance_slug}_{when:%Y%m%d-%H%M%S}.dump"
    path.write_bytes(b"x")
    return path


@pytest.mark.req("N-06", "I-06")
def test_prune_keeps_fourteen_days_and_always_the_newest(tmp_path: Path) -> None:
    settings = make_settings("postgresql://u:p@localhost/db", backup_dir=str(tmp_path))
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    old = [_fake(settings, now - timedelta(days=d)) for d in (15, 20)]
    keep = [_fake(settings, now - timedelta(days=d)) for d in (0, 13)]
    (tmp_path / "other-instance_20200101-000000.dump").write_bytes(b"x")
    (tmp_path / f"{settings.instance_slug}_garbage.dump").write_bytes(b"x")

    removed = prune(settings, now=now)

    assert sorted(removed) == sorted(old)
    assert all(p.exists() for p in keep)
    assert (tmp_path / "other-instance_20200101-000000.dump").exists()  # not ours
    # the newest backup survives even when it is ancient
    lonely = make_settings("postgresql://u:p@localhost/db", backup_dir=str(tmp_path / "solo"))
    only = _fake(lonely, now - timedelta(days=400))
    assert prune(lonely, now=now) == []
    assert only.exists()


@pytest.mark.req("I-06")
def test_daily_backup_only_when_newest_is_older_than_a_day(
    instance: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    _fake(instance, now - timedelta(hours=3))
    assert ensure_recent_backup(instance, now=now) is None

    calls: list[datetime | None] = []
    sentinel = BackupFile(Path("x.dump"), now, 1)

    def fake_backup(settings: Settings, now: datetime | None = None) -> BackupFile:
        calls.append(now)
        return sentinel

    monkeypatch.setattr(backup_module, "backup", fake_backup)
    assert ensure_recent_backup(instance, now=now + timedelta(hours=22)) is sentinel
    assert len(calls) == 1


def test_list_and_find_backups(tmp_path: Path) -> None:
    settings = make_settings("postgresql://u:p@localhost/db", backup_dir=str(tmp_path))
    now = datetime(2026, 9, 24, tzinfo=UTC)
    older = _fake(settings, now - timedelta(days=1))
    newer = _fake(settings, now)
    assert [b.path for b in list_backups(settings)] == [newer, older]
    assert find_backup(settings, older.name).path == older
    with pytest.raises(BackupError):
        find_backup(settings, "../../etc/passwd")
    assert (
        list_backups(make_settings("postgresql://u:p@x/db", backup_dir=str(tmp_path / "none")))
        == []
    )


# ---------------------------------------------------------------- tool selection (ADR-0011)


def test_connection_parsing_and_commands(tmp_path: Path) -> None:
    settings = make_settings("postgresql://app%40x:s%23cret@db.local:6543/contacts_dev")
    conn = Connection.from_settings(settings)
    assert (conn.user, conn.password, conn.host, conn.port, conn.database) == (
        "app@x", "s#cret", "db.local", 6543, "contacts_dev",
    )  # fmt: skip
    assert "s#cret" not in conn.libpq_url  # password travels in PGPASSWORD, not argv

    local, to_stdout = dump_command(conn, "local", tmp_path / "f.dump")
    docker, docker_stdout = dump_command(conn, "docker", tmp_path / "f.dump")
    assert local[0] == "pg_dump"
    assert not to_stdout
    assert docker[:2] == ["docker", "compose"]
    assert docker_stdout
    assert "--host=localhost" in docker
    assert "PGDATABASE=contacts_dev" in docker

    restore_docker = restore_command(conn, "docker", tmp_path / "f.dump", None)
    assert restore_docker[-3:-1] == ["sh", "-c"]
    assert 'grep -v " EXTENSION "' in restore_docker[-1]
    with pytest.raises(BackupError):
        restore_command(conn, "local", tmp_path / "f.dump", None)


def test_resolve_tool(monkeypatch: pytest.MonkeyPatch, instance: Settings) -> None:
    assert resolve_tool(instance.model_copy(update={"backup_tool": "docker"})) == "docker"
    monkeypatch.setattr(backup_module, "local_tool_major", lambda program="pg_dump": 99)
    assert resolve_tool(instance) == "local"
    monkeypatch.setattr(backup_module, "local_tool_major", lambda program="pg_dump": 9)
    monkeypatch.setattr("app.backup.shutil.which", lambda name: "/usr/bin/docker")
    assert resolve_tool(instance) == "docker"  # local pg_dump too old for the server
    monkeypatch.setattr("app.backup.shutil.which", lambda name: None)
    with pytest.raises(BackupError, match="brew install libpq"):
        resolve_tool(instance)


# ---------------------------------------------------------------- command line & copy to dev (I-07)


@pytest.mark.req("D-04")
def test_cli_backup_list_restore(
    instance: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    add_sample_data(instance)
    env = tmp_path / "instance.env"
    env.write_text(
        f"INSTANCE_NAME={instance.instance_name}\nAPP_ENV=development\nPORT=5195\n"
        f"DATABASE_URL={instance.database_url}\nBACKUP_DIR={instance.resolved_backup_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INSTANCE_ENV_FILE", str(env))

    assert cli.main(["backup"]) == 0
    assert cli.main(["list"]) == 0
    name = list_backups(instance)[0].name
    assert name in capsys.readouterr().out
    assert cli.main(["restore", name]) == 0
    assert "previous data was saved" in capsys.readouterr().out
    assert cli.main(["prune"]) == 0
    assert cli.main(["restore", "missing.dump"]) == 1


@pytest.mark.req("I-05")
def test_cli_refuses_production_restore_without_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / "prod.env"
    env.write_text(
        "INSTANCE_NAME=Biz\nAPP_ENV=production\nPORT=5170\n"
        "DATABASE_URL=postgresql://u:p@127.0.0.1:1/none\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INSTANCE_ENV_FILE", str(env))
    assert cli.main(["restore", "x.dump"]) == 2
    assert "--yes" in capsys.readouterr().err


@pytest.mark.req("I-07")
def test_copy_production_into_dev_anonymized(admin_url: str, tmp_path: Path) -> None:
    src_spec, source = _instance(admin_url, tmp_path / "src", env="production")
    dst_spec, target = _instance(admin_url, tmp_path / "dst")
    try:
        add_sample_data(source)
        cli.copy_to_dev(source, target, anonymize_data=True)

        engine = create_db_engine(target)
        with make_session_factory(engine)() as session:
            names = session.scalars(select(Contact.display_name)).all()
            dev = session.scalars(select(Contact).where(Contact.team == "Data Platform")).first()
            assert len(names) == 50
            assert all(n.startswith("Contact ") for n in names)
            assert dev is not None
            assert dev.company == "Acme Health"  # context kept so issues reproduce
            assert all(e.email.endswith("@example.invalid") for e in dev.emails)
            assert session.scalar(select(func.count()).select_from(ContactPhoto)) == 0
        engine.dispose()
        assert count_contacts(source) == 50  # the source is untouched

        with pytest.raises(BackupError, match="Refusing to overwrite production"):
            cli.copy_to_dev(target, source, anonymize_data=False)
    finally:
        drop_database(src_spec, admin_url)
        drop_database(dst_spec, admin_url)
