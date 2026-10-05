"""One name everywhere (N-12, ADR-0024): the product is Kith Contacts and no earlier name is
left in the code, scripts, launchers or documents, except where it is deliberate history."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from app.contacts import ContactError
from app.exchange import FORMAT, rows_from_json

ROOT = Path(__file__).resolve().parent.parent

#: Names the product used before ADR-0024 (the lower-case one is a test folder prefix).
OLD_NAMES = re.compile(
    r"Contact Manager|ContactManager|Contact-Manager|contact-manager|contacts-app"
    r"|contact manager test"
)

#: Folders that are not the product's own text: history (accepted ADRs, applied
#: migrations), generated files, vendored code, local data.
SKIP_DIRS = {
    ".git",
    ".venv",
    "dist",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "vendor",
    "instances",
}
SKIP_PREFIXES = ("docs/adr/", "migrations/versions/")
#: A line (or a block between old-name:start and old-name:end) may keep an old name on purpose.
MARK_LINE = "old-name-ok"
MARK_START, MARK_END = "old-name:start", "old-name:end"
#: Requirement rows that name the old identifiers because they describe the change.
HISTORY_ROWS = {"docs/requirements.md": ("| N-12 |", "| 13 — Name |", "| 1.16 |")}


def _files() -> list[Path]:
    found: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if not path.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        if rel.as_posix().startswith(SKIP_PREFIXES) or rel.name in {"test_naming.py", ".coverage"}:
            continue
        found.append(path)
    return found


def _leftovers(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[str] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if MARK_START in line:
            inside = True
        kept = line.startswith(HISTORY_ROWS.get(rel, ()))
        if not inside and not kept and MARK_LINE not in line and OLD_NAMES.search(line):
            hits.append(f"{rel}:{number}: {line.strip()[:100]}")
        if MARK_END in line:
            inside = False
    return hits


@pytest.mark.req("N-12")
def test_no_earlier_name_is_left_in_the_product() -> None:
    hits = [hit for path in _files() for hit in _leftovers(path)]
    assert not hits, "earlier names left:\n" + "\n".join(hits)


@pytest.mark.req("N-12")
def test_launchers_carry_the_new_name() -> None:
    names = {p.name for p in (ROOT / "deploy/launchers").iterdir()}
    assert names == {
        "Start Kith Contacts.command",
        "Stop Kith Contacts.command",
        "Start Kith Contacts.bat",
        "Stop Kith Contacts.bat",
    }


@pytest.mark.req("N-12")
def test_compose_project_data_folder_and_image_use_the_new_name() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^name: kith-contacts$", compose, re.MULTILINE)
    assert "image: kith-contacts:${APP_VERSION:-dev}" in compose
    mac_start = (ROOT / "deploy/mac/start.sh").read_text(encoding="utf-8")
    mac_stop = (ROOT / "deploy/mac/stop.sh").read_text(encoding="utf-8")
    win_start = (ROOT / "deploy/windows/start.ps1").read_text(encoding="utf-8")
    win_stop = (ROOT / "deploy/windows/stop.ps1").read_text(encoding="utf-8")
    assert 'PROJECT="kith-contacts"' in mac_start
    assert "--project-name kith-contacts" in mac_stop
    assert "$Project = 'kith-contacts'" in win_start
    assert "--project-name kith-contacts" in win_stop
    assert 'DATA="$HOME/KithContacts"' in mac_start
    assert "KithContacts" in win_start


@pytest.mark.req("N-12")
def test_python_package_is_named_kith_contacts() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "kith-contacts"


@pytest.mark.req("N-12", "I-09")
def test_json_export_format_is_renamed_and_the_old_one_still_imports() -> None:
    assert FORMAT == "kith-contacts/1"
    contact = {"display_name": "Maria Copy"}
    for name in (FORMAT, "contacts-app/1"):  # old-name-ok
        rows = rows_from_json(json.dumps({"format": name, "contacts": [contact]}))
        assert [row["display_name"] for row in rows] == ["Maria Copy"]
    with pytest.raises(ContactError):
        rows_from_json(json.dumps({"format": "someone-else/1", "contacts": [contact]}))
