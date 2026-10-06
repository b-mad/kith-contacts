"""Nothing that must stay private is in the files a public repository would publish (N-13).

Looks at every file git would commit (tracked or not yet added, minus what is ignored), so a
real address or key is caught before it reaches history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
#: Domains that are safe to publish: reserved for documentation (RFC 2606) or deliberate.
SAFE_DOMAIN = re.compile(
    r"(\.example|(^|\.)example\.(com|org|net)|(^|\.)users\.noreply\.github\.com|^db\.local|^127\.0\.0\.1|^localhost)$",
    re.I,
)
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bghp_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\bsk-[A-Za-z0-9]{32,}"
)
#: A path into somebody's home folder.
HOME_PATH = re.compile(
    r"(?:/Users/|/home/|C:\\Users\\)(?!<|\$|\{|%|\.\.\.|you\b|name\b|user\b)[A-Za-z]"
)
SKIP_SUFFIXES = (".png", ".woff2", ".gz", ".ico", ".jpg", ".jpeg", ".zip", ".pyc")
SKIP_PARTS = {"vendor"}  # third-party code keeps its authors' own addresses


def _publishable_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    files = []
    for name in out.decode().split("\0"):
        path = ROOT / name
        if (
            name
            and path.is_file()
            and not name.endswith(SKIP_SUFFIXES)
            and not SKIP_PARTS & set(path.relative_to(ROOT).parts)
            and name not in {"uv.lock", "tests/test_release_hygiene.py"}
        ):
            files.append(path)
    return files


def _lines() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _publishable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found.extend(
            (path.relative_to(ROOT).as_posix(), n, line)
            for n, line in enumerate(text.splitlines(), 1)
        )
    return found


@pytest.mark.req("N-13")
def test_only_documentation_addresses_are_published() -> None:
    bad = [
        f"{rel}:{n}: {m.group(0)}"
        for rel, n, line in _lines()
        for m in EMAIL.finditer(line)
        if not SAFE_DOMAIN.search(m.group(1))
    ]
    assert not bad, "use a `.example` address instead of a real one:\n" + "\n".join(bad)


@pytest.mark.req("N-13")
def test_no_keys_or_tokens_are_published() -> None:
    bad = [f"{rel}:{n}" for rel, n, line in _lines() if SECRET.search(line)]
    assert not bad, "key or token found:\n" + "\n".join(bad)


@pytest.mark.req("N-13")
def test_no_personal_home_paths_are_published() -> None:
    bad = [f"{rel}:{n}: {line.strip()[:80]}" for rel, n, line in _lines() if HOME_PATH.search(line)]
    assert not bad, "home folder path found:\n" + "\n".join(bad)


@pytest.mark.req("N-13")
def test_only_the_example_env_file_is_published() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _publishable_files()}
    env_files = {n for n in names if n.endswith(".env") or "/.env" in n or n == ".env"}
    assert env_files <= {"instances/example.env"}, env_files
    assert not [n for n in names if n.endswith((".dump", ".sql.gz", ".vcf", ".csv"))]


@pytest.mark.req("N-13")
def test_the_checker_catches_what_it_should() -> None:
    assert not SAFE_DOMAIN.search("acme.com")
    assert SAFE_DOMAIN.search("acme.example")
    assert SAFE_DOMAIN.search("example.com")
    assert SECRET.search("-----BEGIN RSA PRIVATE " + "KEY-----")  # split: not a real key
    assert SECRET.search("ghp_" + "a" * 36)
    assert HOME_PATH.search("/Users/someone/project")
    assert not HOME_PATH.search("/home/<you>/project")
