"""Start one instance: ``python -m app`` (normally via ./run.sh <instance>)."""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from app.config import Settings, load_settings
from app.migrate import MigrationError, upgrade_to_head
from app.version import app_version


def main() -> int:
    try:
        settings = load_settings()
    except (FileNotFoundError, ValidationError) as exc:
        print(f"Invalid instance configuration:\n{exc}", file=sys.stderr)
        return 2
    return run(settings)


def run(settings: Settings) -> int:
    """Migrate, then serve until stopped (also the container's ``serve``, ADR-0019)."""
    try:
        safety = upgrade_to_head(settings)  # I-04: refuse to start on migration failure
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if safety is not None:
        print(f"Backed up before upgrading: {safety.path}")  # I-11

    print(
        f"Starting '{settings.instance_name}' ({settings.app_env}, version {app_version()}) "
        f"on http://{'localhost' if settings.host == '0.0.0.0' else settings.host}:{settings.port}"  # noqa: S104
    )
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        reload_dirs=["app"] if settings.is_development else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
