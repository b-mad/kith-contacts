"""The release workflow builds the install zip from a version tag and attaches it (I-13, N-13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _load() -> dict[Any, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> str:
    return "\n".join(
        str(step.get("run", "")) + " " + str(step.get("uses", ""))
        for step in _load()["jobs"]["release"]["steps"]
    )


@pytest.mark.req("I-13", "N-13")
def test_release_runs_only_on_version_tags() -> None:
    data = _load()
    triggers = data.get("on", data.get(True))  # YAML reads a bare `on` as True
    assert triggers == {"push": {"tags": ["v*"]}}


@pytest.mark.req("I-13", "N-13")
def test_release_may_only_write_contents() -> None:
    assert _load()["permissions"] == {"contents": "write"}


@pytest.mark.req("I-13", "N-13")
def test_release_builds_with_make_bundle_and_attaches_the_zip_and_checksum() -> None:
    steps = _steps()
    assert "make bundle" in steps
    assert "gh release create" in steps
    assert "--verify-tag" in steps
    assert "dist/Kith-Contacts-${VERSION}.zip" in steps
    assert ".zip.sha256" in steps


@pytest.mark.req("I-13", "N-13")
def test_release_checks_the_tag_against_the_version_and_main() -> None:
    steps = _steps()
    assert "app_version" in steps
    assert "v${version}" in steps
    assert "merge-base --is-ancestor" in steps
