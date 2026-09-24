"""Instance configuration (I-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent

VALID_ENV = """\
INSTANCE_NAME=Business
APP_ENV=production
INSTANCE_COLOR=#1f6feb
PORT=5170
DATABASE_URL=postgresql://biz_app:s3cret@localhost:5432/contacts_business_prod
BACKUP_DIR=/srv/backups/business
CONTACT_TYPES=Employee, Customer ,Vendor
"""


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "INSTANCE_ENV_FILE",
        "INSTANCE_NAME",
        "APP_ENV",
        "INSTANCE_COLOR",
        "PORT",
        "DATABASE_URL",
        "BACKUP_DIR",
        "CONTACT_TYPES",
    ):
        monkeypatch.delenv(var, raising=False)


def write_env(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "instance.env"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.req("I-01")
def test_settings_load_from_instance_env_file(tmp_path: Path) -> None:
    settings = load_settings(write_env(tmp_path, VALID_ENV))

    assert settings.instance_name == "Business"
    assert settings.is_production
    assert not settings.is_development
    assert settings.port == 5170
    assert settings.contact_types == ("Employee", "Customer", "Vendor")
    assert settings.resolved_backup_dir == Path("/srv/backups/business")
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://biz_app:")


@pytest.mark.req("I-01")
def test_env_file_can_be_named_by_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTANCE_ENV_FILE", str(write_env(tmp_path, VALID_ENV)))
    assert load_settings().instance_name == "Business"


@pytest.mark.req("I-01")
def test_missing_required_setting_refuses_to_load(tmp_path: Path) -> None:
    content = "\n".join(line for line in VALID_ENV.splitlines() if "DATABASE_URL" not in line)
    with pytest.raises(ValidationError, match="database_url"):
        load_settings(write_env(tmp_path, content))


@pytest.mark.req("I-01")
def test_missing_env_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.env")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_env", "staging"),
        ("instance_color", "blue"),
        ("port", 80),
        ("database_url", "mysql://x@y/z"),
        ("contact_types", " , "),
        ("contact_types", "Friend,friend"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    values: dict[str, object] = {
        "instance_name": "X",
        "app_env": "development",
        "database_url": "postgresql://u:p@localhost/db",
        "port": 5180,
    }
    values[field] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_defaults_for_optional_settings() -> None:
    settings = Settings.model_validate(
        {
            "instance_name": "Personal Prod",
            "app_env": "development",
            "database_url": "postgres://u:p@localhost/db",
            "port": 5171,
        }
    )
    assert settings.host == "127.0.0.1"  # N-01: localhost only by default
    assert settings.contact_types == ("Employee", "Customer", "Vendor")
    assert settings.instance_slug == "personal-prod"
    assert settings.resolved_backup_dir == Path.home() / "ContactsBackups" / "personal-prod"
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@localhost/db"


def test_example_env_file_is_valid() -> None:
    settings = load_settings(ROOT / "instances" / "example.env")
    assert settings.instance_color == "#bf3989"
    assert settings.is_development
