"""Container deployment: provisioning, entry point, before-upgrade backups, restore on first
start and the version (I-10, I-11, I-12, I-14, ADR-0019)."""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import func, select

from app import container
from app.backup import backup, list_backups, restore_newest_into_empty
from app.config import Settings
from app.db import create_db_engine, make_session_factory
from app.migrate import (
    MigrationError,
    alembic_config,
    current_revision,
    head_revision,
    upgrade_to_head,
)
from app.models import Contact
from app.version import app_version
from scripts.bootstrap_instance import (
    BootstrapError,
    database_name,
    ensure_database,
    role_name,
)
from tests.conftest import make_settings


def _drop(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name(name))
            )
        )
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name(name))))


@pytest.fixture
def name(admin_url: str) -> Iterator[str]:
    value = f"tc-{uuid.uuid4().hex[:6]}"
    yield value
    _drop(admin_url, value)


def _settings(url: str, tmp_path: Path, env: str = "production", **extra: object) -> Settings:
    return make_settings(
        url,
        instance_name="Work",
        app_env=env,
        backup_dir=str(tmp_path / "backups"),
        backup_tool="local",
        **extra,
    )


def _count(settings: Settings) -> int:
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            return int(session.scalar(select(func.count()).select_from(Contact)) or 0)
    finally:
        engine.dispose()


# ---------------------------------------------------------------- provisioning (I-10, I-02)


@pytest.mark.req("I-10", "I-02")
def test_ensure_database_creates_then_reuses_the_saved_password(admin_url: str, name: str) -> None:
    url, created = ensure_database(name, admin_url)
    assert created
    assert urlsplit(url).username == role_name(name)
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT current_database()").fetchone() == (database_name(name),)

    again, created_again = ensure_database(name, admin_url, url)
    assert (again, created_again) == (url, False)
    with psycopg.connect(again):
        pass


@pytest.mark.req("I-10")
def test_ensure_database_resets_a_lost_password(admin_url: str, name: str) -> None:
    old, _ = ensure_database(name, admin_url)
    new, created = ensure_database(name, admin_url, None)  # the instance volume was replaced
    assert not created
    assert new != old
    with psycopg.connect(new):
        pass
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(old, connect_timeout=3)


@pytest.mark.req("I-10", "I-02")
def test_one_instance_cannot_open_another_instances_database(admin_url: str) -> None:
    a, b = f"tc-{uuid.uuid4().hex[:6]}", f"tc-{uuid.uuid4().hex[:6]}"
    try:
        url_a, _ = ensure_database(a, admin_url)
        ensure_database(b, admin_url)
        other = urlsplit(url_a)._replace(path="/" + database_name(b)).geturl()
        with pytest.raises(psycopg.OperationalError, match="permission denied"):
            psycopg.connect(other, connect_timeout=3)
    finally:
        _drop(admin_url, a)
        _drop(admin_url, b)


@pytest.mark.req("I-10")
def test_ensure_database_rejects_odd_names(admin_url: str) -> None:
    with pytest.raises(BootstrapError):
        ensure_database("Work; DROP", admin_url)


# ---------------------------------------------------------------- entry point (I-10)


@pytest.mark.req("I-10")
def test_admin_password_is_made_once_and_private(tmp_path: Path) -> None:
    assert container.ensure_admin_password(tmp_path)
    path = tmp_path / container.ADMIN_PASSWORD_FILE
    first = path.read_text()
    assert len(first) >= 40
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not container.ensure_admin_password(tmp_path)
    assert path.read_text() == first


@pytest.mark.req("I-10")
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("work", ("work",)),
        ("work,personal", ("work", "personal")),
        (" Personal , work,work", ("personal", "work")),
    ],
)
def test_contact_books_come_from_the_compose_profiles(
    value: str, expected: tuple[str, ...]
) -> None:
    assert container.parse_instances(value) == expected


@pytest.mark.req("I-10")
@pytest.mark.parametrize("value", ["", "work,family", " , "])
def test_unknown_or_missing_contact_books_are_refused(value: str) -> None:
    with pytest.raises(container.ContainerError):
        container.parse_instances(value)


@pytest.mark.req("I-10")
def test_setup_writes_each_instance_its_own_url(admin_url: str, tmp_path: Path) -> None:
    names = (f"tc-{uuid.uuid4().hex[:6]}", f"tc-{uuid.uuid4().hex[:6]}")
    said: list[str] = []
    try:
        backups = tmp_path / "backups"
        created = container.setup_instances(names, admin_url, tmp_path, backups, say=said.append)
        assert created == dict.fromkeys(names, True)
        for name in names:
            url_file = tmp_path / name / container.URL_FILE
            assert urlsplit(url_file.read_text()).path == "/" + database_name(name)
            assert (backups / name).is_dir()
            if os.geteuid() == 0:  # as in the container: handed to the app user
                assert url_file.stat().st_uid == container.APP_UID
                assert (backups / name).stat().st_uid == container.APP_UID
        again = container.setup_instances(names, admin_url, tmp_path, None, say=said.append)
        assert again == dict.fromkeys(names, False)
        assert said[-1].endswith("database ready")
    finally:
        for name in names:
            _drop(admin_url, name)


@pytest.mark.req("I-10")
def test_environment_drops_blank_settings_and_reads_the_saved_url(tmp_path: Path) -> None:
    (tmp_path / container.URL_FILE).write_text("postgresql://u:p@db:5432/x\n")
    env = {"INSTANCE_NAME": "Work", "HOME_COMPANY": "", "DEFAULT_PALETTE": " ", "OTHER": ""}
    container.prepare_environment(env, tmp_path)
    assert env == {
        "INSTANCE_NAME": "Work",
        "OTHER": "",
        "DATABASE_URL": "postgresql://u:p@db:5432/x",
    }
    given = {"DATABASE_URL": "postgresql://given@h/db"}
    container.prepare_environment(given, tmp_path / "missing")
    assert given["DATABASE_URL"] == "postgresql://given@h/db"
    with pytest.raises(container.ContainerError, match="setup step"):
        container.prepare_environment({}, tmp_path / "missing")


@pytest.mark.req("I-10")
def test_wait_for_database_gives_up_with_a_clear_message() -> None:
    said: list[str] = []
    with pytest.raises(container.ContainerError, match="did not become reachable"):
        container.wait_for_database(
            "postgresql://x:y@127.0.0.1:1/none", timeout=0.3, interval=0.1, say=said.append
        )
    assert said == ["Waiting for the database to start…"]


@pytest.mark.req("I-10")
def test_health_check_fails_when_nothing_answers() -> None:
    assert container.health("1") == 1


@pytest.mark.req("I-10")
def test_unknown_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert container.main(["dance"]) == 2
    assert "usage" in capsys.readouterr().out


# ---------------------------------------------------------------- before-upgrade backup (I-11)


@pytest.fixture
def older(admin_url: str, name: str, tmp_path: Path) -> Settings:
    """A production instance one migration behind, with a contact in it."""
    url, _ = ensure_database(name, admin_url)
    settings = _settings(url, tmp_path)
    upgrade_to_head(settings)
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            from app.models import ContactType

            kind = ContactType(name="Employee", sort_order=0)
            session.add(kind)
            session.flush()
            session.add(Contact(display_name="Maria Lopez", contact_type_id=kind.id))
            session.commit()
    finally:
        engine.dispose()
    command.downgrade(alembic_config(settings.sqlalchemy_url), "-1")
    return settings


@pytest.mark.req("I-11", "I-04")
def test_production_backs_up_before_migrating(older: Settings) -> None:
    safety = upgrade_to_head(older)
    assert safety is not None
    assert safety.name.endswith("_before-upgrade.dump")
    assert safety.size > 0
    engine = create_db_engine(older)
    try:
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()
    assert upgrade_to_head(older) is None  # nothing pending: no second backup
    assert len(list_backups(older)) == 1


@pytest.mark.req("I-11")
def test_development_and_new_databases_skip_the_backup(older: Settings, tmp_path: Path) -> None:
    dev = older.model_copy(update={"app_env": "development"})
    assert upgrade_to_head(dev) is None
    assert list_backups(older) == []


@pytest.mark.req("I-11")
def test_a_failed_backup_stops_the_upgrade(older: Settings, tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the backup folder should be")
    settings = older.model_copy(update={"backup_dir": blocked})
    with pytest.raises(MigrationError, match="backup before upgrading failed"):
        upgrade_to_head(settings)
    engine = create_db_engine(older)
    try:
        assert current_revision(engine) != head_revision()  # left untouched
    finally:
        engine.dispose()


# ---------------------------------------------------------------- restore on first start (I-12)


@pytest.mark.req("I-12", "D-04")
def test_a_new_database_is_filled_from_the_newest_backup(admin_url: str, tmp_path: Path) -> None:
    old_name, new_name = f"tc-{uuid.uuid4().hex[:6]}", f"tc-{uuid.uuid4().hex[:6]}"
    try:
        old_url, _ = ensure_database(old_name, admin_url)
        old = _settings(old_url, tmp_path)
        upgrade_to_head(old)
        engine = create_db_engine(old)
        try:
            with make_session_factory(engine)() as session:
                from app.models import ContactType

                kind = ContactType(name="Employee", sort_order=0)
                session.add(kind)
                session.flush()
                session.add(Contact(display_name="Moved Person", contact_type_id=kind.id))
                session.commit()
        finally:
            engine.dispose()
        made = backup(old)

        # "another computer": a brand-new database, same instance name and backup folder
        new_url, created = ensure_database(new_name, admin_url)
        assert created
        new = _settings(new_url, tmp_path)
        said: list[str] = []
        restored = container.restore_on_first_start(new, say=said.append)
        assert restored is not None
        assert restored.name == made.name
        assert said == [f"New database: restored the newest backup, {made.name}"]
        upgrade_to_head(new)
        assert _count(new) == 1
        assert len(list_backups(new)) == 1  # no safety backup of an empty database

        # second start: the database has tables now, so nothing is restored again
        assert restore_newest_into_empty(new) is None
    finally:
        _drop(admin_url, old_name)
        _drop(admin_url, new_name)


@pytest.mark.req("I-12")
def test_an_empty_folder_means_a_fresh_start(admin_url: str, name: str, tmp_path: Path) -> None:
    url, _ = ensure_database(name, admin_url)
    assert container.restore_on_first_start(_settings(url, tmp_path), say=print) is None


@pytest.mark.req("I-12")
def test_a_broken_newest_backup_stops_the_start(admin_url: str, name: str, tmp_path: Path) -> None:
    url, _ = ensure_database(name, admin_url)
    settings = _settings(url, tmp_path)
    folder = tmp_path / "backups"
    folder.mkdir()
    (folder / "work_20991231-000000.dump").write_bytes(b"not a dump")
    with pytest.raises(container.ContainerError, match="Could not restore"):
        container.restore_on_first_start(settings, say=print)


# ---------------------------------------------------------------- version (I-14)


@pytest.mark.req("I-14")
def test_version_comes_from_pyproject() -> None:
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert f'version = "{app_version()}"' in text


@pytest.mark.req("I-14")
def test_settings_and_healthz_show_the_version(client: TestClient) -> None:
    assert client.get("/healthz").json()["version"] == app_version()
    page = client.get("/settings").text
    assert f'<dd data-testid="app-version">{app_version()}</dd>' in page


@pytest.mark.req("I-13", "S-08")
def test_settings_explain_a_missing_model_in_container_terms(
    settings: Settings, tmp_path: Path
) -> None:
    from app.main import create_app

    for update, expected in (
        ({"semantic_search": "auto", "model_dir": tmp_path}, "could not be downloaded when"),
        ({"semantic_search": "off"}, "Turned off in settings.env."),
    ):
        boxed = settings.model_copy(update={"install_kind": "container", **update})
        with TestClient(create_app(boxed, run_migrations=False)) as client:
            page = client.get("/settings").text
        assert expected in page
        assert "make model" not in page


# ---------------------------------------------------------------- moving ./run.sh instances


@pytest.mark.req("I-12", "I-10")
def test_move_to_containers_copies_a_backup_and_writes_settings(
    admin_url: str, tmp_path: Path
) -> None:
    from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
    from scripts.move_to_containers import MoveError, move

    spec = InstanceSpec(
        name=f"tm-{uuid.uuid4().hex[:6]}",
        port=5172,
        app_env="test",
        color="#0a7d55",
        contact_types="Employee,Vendor",
        display_name="Business Prod",
    )
    instances = tmp_path / "instances"
    info = bootstrap(spec, admin_url, instances)
    assert info.env_file is not None
    env = info.env_file.read_text().replace(
        "BACKUP_DIR=~/ContactsBackups/" + spec.name, f"BACKUP_DIR={tmp_path / 'old-backups'}"
    )
    info.env_file.write_text(env + "BACKUP_TOOL=local\nHOME_COMPANY=Acme Health\n")
    try:
        upgrade_to_head(make_settings(info.database_url))
        data = tmp_path / "Contact Manager"
        said: list[str] = []
        written = move({"work": spec.name}, data=data, instances_dir=instances, say=said.append)
        text = written.read_text()
        for line in (
            "COMPOSE_PROFILES=work",
            'WORK_NAME="Business Prod"',
            'WORK_COLOR="#0a7d55"',
            'WORK_TYPES="Employee,Vendor"',
            "WORK_PORT=5172",
            'WORK_HOME_COMPANY="Acme Health"',
            "PHONE_REGION=US",
        ):
            assert line in text.splitlines(), line
        copied = list((data / "Backups" / "work").glob("business-prod_*.dump"))
        assert len(copied) == 1  # named like the container instance will look for
        assert said == [f"{spec.name} → work: backed up and copied {copied[0].name}"]
        with pytest.raises(MoveError, match="already exists"):
            move({"work": spec.name}, data=data, instances_dir=instances)
        with pytest.raises(MoveError, match="at least one"):
            move({}, data=tmp_path / "other")
    finally:
        drop_database(spec, admin_url)
