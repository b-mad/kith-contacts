"""The app version (I-14): kept in one place, ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@cache
def app_version() -> str:
    try:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return "unknown"
