"""Instance bootstrap and isolation (I-01, I-02, I-05)."""

from __future__ import annotations

import stat
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from app.config import load_settings
from app.migrate import upgrade_to_head
from scripts.bootstrap_instance import (
    BootstrapError,
    InstanceInfo,
    InstanceSpec,
    bootstrap,
    drop_database,
    main,
)


def _spec(prefix: str, **kwargs: object) -> InstanceSpec:
    values: dict[str, object] = {
        "name": f"t{prefix}-{uuid.uuid4().hex[:6]}",
        "port": 5190,
        "app_env": "test",
    }
    values.update(kwargs)
    return InstanceSpec(**values)  # type: ignore[arg-type]


@pytest.fixture
def two_instances(admin_url: str, tmp_path: Path) -> Iterator[tuple[InstanceInfo, InstanceInfo]]:
    a = bootstrap(_spec("a"), admin_url, tmp_path)
    b = bootstrap(_spec("b", port=5191), admin_url, tmp_path)
    yield a, b
    drop_database(a.spec, admin_url)
    drop_database(b.spec, admin_url)


@pytest.mark.req("I-02")
def test_instance_role_can_use_its_own_database(
    two_instances: tuple[InstanceInfo, InstanceInfo],
) -> None:
    a, _ = two_instances
    with psycopg.connect(a.database_url) as conn:
        conn.execute("CREATE TABLE probe (id int)")
        conn.execute("INSERT INTO probe VALUES (1)")
        assert conn.execute("SELECT count(*) FROM probe").fetchone() == (1,)


@pytest.mark.req("I-02")
def test_instance_role_cannot_connect_to_another_instance(
    two_instances: tuple[InstanceInfo, InstanceInfo],
) -> None:
    a, b = two_instances
    url_a_into_b = a.database_url.rsplit("/", 1)[0] + "/" + b.spec.database
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(url_a_into_b)


@pytest.mark.req("I-01", "I-04")
def test_generated_env_file_starts_a_migrated_instance(
    two_instances: tuple[InstanceInfo, InstanceInfo],
) -> None:
    a, _ = two_instances
    assert a.env_file is not None
    assert stat.S_IMODE(a.env_file.stat().st_mode) == 0o600  # credentials: owner only

    settings = load_settings(a.env_file)
    assert settings.port == 5190
    assert str(settings.database_url).endswith("/" + a.spec.database)

    upgrade_to_head(settings)  # the instance's own role can run migrations (owns its DB)


@pytest.mark.req("I-01")
def test_existing_env_file_is_not_overwritten(admin_url: str, tmp_path: Path) -> None:
    spec = _spec("c")
    (tmp_path / f"{spec.name}.env").write_text("keep me", encoding="utf-8")
    with pytest.raises(BootstrapError, match="already exists"):
        bootstrap(spec, admin_url, tmp_path)
    assert (tmp_path / f"{spec.name}.env").read_text(encoding="utf-8") == "keep me"


def test_existing_database_is_reported(admin_url: str, tmp_path: Path) -> None:
    spec = _spec("d")
    bootstrap(spec, admin_url, None)
    try:
        with pytest.raises(BootstrapError, match="already exists"):
            bootstrap(spec, admin_url, tmp_path)
    finally:
        drop_database(spec, admin_url)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "Business"},
        {"name": "x"},
        {"name": "bad_name"},
        {"app_env": "staging"},
        {"port": 80},
    ],
)
def test_invalid_specs_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(BootstrapError):
        _spec("e", **kwargs)


@pytest.mark.req("I-05")
def test_production_instance_cannot_be_dropped(admin_url: str) -> None:
    with pytest.raises(BootstrapError, match="production"):
        drop_database(_spec("f", app_env="production"), admin_url)


def test_cli_creates_instance(
    admin_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.bootstrap_instance as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    name = f"tcli-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(
        module,
        "bootstrap",
        lambda spec, url, force=False: bootstrap(spec, url, tmp_path, force=force),
    )
    try:
        code = main(
            ["--name", name, "--port", "5192", "--env", "development", "--admin-url", admin_url]
        )
        assert code == 0
        assert f"./run.sh {name}" in capsys.readouterr().out
        assert (tmp_path / f"{name}.env").is_file()
        assert (
            main(
                ["--name", name, "--port", "5192", "--env", "development", "--admin-url", admin_url]
            )
            == 1
        )
    finally:
        drop_database(InstanceSpec(name=name, port=5192, app_env="development"), admin_url)
