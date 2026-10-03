"""Instance settings (requirement I-01).

Every instance-specific value comes from an env file (``instances/<name>.env``)
or environment variables — never from code. The app refuses to start when a
required setting is missing or invalid.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "production", "test"]

DEFAULT_CONTACT_TYPES: tuple[str, ...] = ("Employee", "Customer", "Vendor")
ENV_FILE_VARIABLE = "INSTANCE_ENV_FILE"


class Settings(BaseSettings):
    """Configuration for one app instance."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    instance_name: str = Field(min_length=1, max_length=40)
    app_env: AppEnv
    database_url: PostgresDsn
    port: int = Field(ge=1024, le=65535)
    host: str = "127.0.0.1"
    instance_color: str = Field(default="#1f6feb", pattern=r"^#[0-9a-fA-F]{6}$")
    backup_dir: Path | None = None
    contact_types: Annotated[tuple[str, ...], NoDecode] = DEFAULT_CONTACT_TYPES
    phone_region: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    home_company: str | None = Field(default=None, max_length=200)  # C-14
    # Backups (I-06, N-06, ADR-0011)
    backup_tool: Literal["auto", "local", "docker"] = "auto"
    backup_retention_days: int = Field(default=14, ge=1, le=3650)
    auto_backup: bool | None = None  # default: on in production, off elsewhere
    # Search by meaning (S-08, ADR-0013): on when the model is installed, unless "off".
    semantic_search: Literal["auto", "off"] = "auto"
    model_dir: Path | None = None  # default ~/.cache/contacts-app/models/all-MiniLM-L6-v2

    @field_validator("contact_types", mode="before")
    @classmethod
    def _split_contact_types(cls, value: object) -> object:
        if isinstance(value, str):
            value = tuple(part.strip() for part in value.split(","))
        if isinstance(value, list | tuple):
            items = tuple(str(v).strip() for v in value if str(v).strip())
            if not items:
                raise ValueError("CONTACT_TYPES must list at least one type")
            if len({i.casefold() for i in items}) != len(items):
                raise ValueError("CONTACT_TYPES contains duplicates")
            return items
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def auto_backup_enabled(self) -> bool:
        return self.is_production if self.auto_backup is None else self.auto_backup

    @property
    def instance_slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.instance_name.lower()).strip("-") or "instance"

    @property
    def sqlalchemy_url(self) -> str:
        """Database URL with the psycopg 3 driver selected for SQLAlchemy."""
        url = str(self.database_url)
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url  # pragma: no cover - PostgresDsn guarantees one of the prefixes

    @property
    def resolved_backup_dir(self) -> Path:
        """Folder for this instance's backups (ADR-0007)."""
        if self.backup_dir is not None:
            return self.backup_dir.expanduser()
        return Path.home() / "ContactsBackups" / self.instance_slug

    @property
    def resolved_model_dir(self) -> Path:
        from app.embedder import default_model_dir

        return self.model_dir.expanduser() if self.model_dir else default_model_dir()


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from ``env_file``, ``$INSTANCE_ENV_FILE`` or the environment.

    Raises ``FileNotFoundError`` if an env file is named but missing, and
    ``pydantic.ValidationError`` if required settings are missing or invalid.
    """
    path = env_file or os.environ.get(ENV_FILE_VARIABLE)
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Instance env file not found: {path}")
    return Settings(_env_file=path)
