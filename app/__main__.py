"""Start one instance: ``python -m app`` (normally via ./run.sh <instance>)."""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from app.config import load_settings
from app.migrate import MigrationError, upgrade_to_head


def main() -> int:
    try:
        settings = load_settings()
    except (FileNotFoundError, ValidationError) as exc:
        print(f"Invalid instance configuration:\n{exc}", file=sys.stderr)
        return 2

    try:
        upgrade_to_head(settings)  # I-04: refuse to start on migration failure
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"Starting '{settings.instance_name}' ({settings.app_env}) "
        f"on http://{settings.host}:{settings.port}"
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
