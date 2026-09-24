"""Backups and restores with pg_dump / pg_restore (D-04, I-06, I-07, N-06, ADR-0011).

``BACKUP_TOOL=auto`` uses a local pg_dump when its major version is at least
the server's; otherwise it runs the tools inside the PostgreSQL container with
``docker compose exec`` so nothing needs installing on the Mac.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

import psycopg

from app.config import Settings

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.db.yml"
TIMESTAMP = "%Y%m%d-%H%M%S"
DAILY = timedelta(hours=24)
Tool = Literal["local", "docker"]

# Restores skip extension entries: the instance's role may not drop or create
# extensions it doesn't own (pg_trgm is installed by the bootstrap as admin).
_RESTORE_LIST_FILTER = " EXTENSION "


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupFile:
    path: Path
    created: datetime
    size: int

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Connection:
    user: str
    password: str
    host: str
    port: int
    database: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Connection:
        url = settings.database_url
        host = url.hosts()[0]
        return cls(
            user=unquote(host.get("username") or ""),
            password=unquote(host.get("password") or ""),
            host=host.get("host") or "localhost",
            port=host.get("port") or 5432,
            database=(url.path or "").lstrip("/"),
        )

    @property
    def libpq_url(self) -> str:
        """URL without the password (passed via PGPASSWORD so it stays out of `ps`)."""
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


# ---------------------------------------------------------------- tool selection


def _major(version_text: str) -> int | None:
    match = re.search(r"(\d+)(?:\.\d+)?", version_text)
    return int(match.group(1)) if match else None


def local_tool_major(program: str = "pg_dump") -> int | None:
    path = shutil.which(program)
    if path is None:
        return None
    out = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return _major(out.stdout)


def server_major(conn: Connection) -> int:
    with psycopg.connect(
        host=conn.host,
        port=conn.port,
        user=conn.user,
        password=conn.password,
        dbname=conn.database,
        connect_timeout=5,
    ) as db:
        row = db.execute("SHOW server_version_num").fetchone()
    if row is None:  # pragma: no cover - SHOW always returns a row
        raise BackupError("Could not read the server version")
    return int(row[0]) // 10000


def resolve_tool(settings: Settings, conn: Connection | None = None) -> Tool:
    if settings.backup_tool != "auto":
        return settings.backup_tool
    conn = conn or Connection.from_settings(settings)
    local = local_tool_major()
    if local is not None and local >= server_major(conn):
        return "local"
    if shutil.which("docker"):
        return "docker"
    raise BackupError(
        "No usable pg_dump: install PostgreSQL client tools matching the server "
        "(macOS: brew install libpq && brew link --force libpq) or start Docker Desktop."
    )


def _docker_prefix(conn: Connection) -> list[str]:
    return [
        "docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T",
        "-e", f"PGPASSWORD={conn.password}",
        "-e", f"PGUSER={conn.user}",
        "-e", f"PGDATABASE={conn.database}",
        "postgres",
    ]  # fmt: skip


def dump_command(conn: Connection, tool: Tool, target: Path) -> tuple[list[str], bool]:
    """(argv, writes_to_stdout)."""
    args = ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]
    if tool == "local":
        return [*args, f"--file={target}", f"--dbname={conn.libpq_url}"], False
    # Inside the container the server listens on localhost:5432 regardless of host mapping.
    return [*_docker_prefix(conn), *args, "--host=localhost", "--port=5432"], True


def restore_command(
    conn: Connection, tool: Tool, source: Path, list_file: Path | None
) -> list[str]:
    opts = ["--clean", "--if-exists", "--no-owner", "--no-acl", "--single-transaction"]
    if tool == "local":
        if list_file is None:
            raise BackupError("A local restore needs a filtered restore list")
        return [
            "pg_restore",
            *opts,
            f"--use-list={list_file}",
            f"--dbname={conn.libpq_url}",
            str(source),
        ]
    script = (
        'set -e; f=$(mktemp); cat > "$f"; '
        f'pg_restore -l "$f" | grep -v "{_RESTORE_LIST_FILTER}" > "$f.list"; '
        f'pg_restore {" ".join(opts)} --use-list="$f.list" --host=localhost --port=5432 '
        '--dbname="$PGDATABASE" "$f"; rm -f "$f" "$f.list"'
    )
    return [*_docker_prefix(conn), "sh", "-c", script]


def _run(
    argv: Sequence[str], conn: Connection, *, stdin: Path | None = None, stdout: Path | None = None
) -> None:
    env = {**os.environ, "PGPASSWORD": conn.password}
    stdin_f = stdin.open("rb") if stdin else None
    stdout_f = stdout.open("wb") if stdout else None
    try:
        result = subprocess.run(  # noqa: S603 - argv built from settings, never a shell string
            list(argv),
            stdin=stdin_f,
            stdout=stdout_f if stdout_f else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
            timeout=600,
        )
    finally:
        for f in (stdin_f, stdout_f):
            if f:
                f.close()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "no error output"
        raise BackupError(f"{argv[0]} failed ({result.returncode}): {detail}")


# ---------------------------------------------------------------- files


def backup_dir(settings: Settings) -> Path:
    return settings.resolved_backup_dir


def _parse_created(path: Path, prefix: str) -> datetime | None:
    stamp = path.stem.removeprefix(prefix + "_").split("_")[0]
    try:
        return datetime.strptime(stamp, TIMESTAMP).replace(tzinfo=UTC)
    except ValueError:
        return None


def list_backups(settings: Settings) -> list[BackupFile]:
    """This instance's backups, newest first."""
    folder = backup_dir(settings)
    prefix = settings.instance_slug
    files = []
    for path in folder.glob(f"{prefix}_*.dump") if folder.is_dir() else []:
        created = _parse_created(path, prefix)
        if created is not None:
            files.append(BackupFile(path, created, path.stat().st_size))
    return sorted(files, key=lambda f: f.created, reverse=True)


def find_backup(settings: Settings, name: str) -> BackupFile:
    """Look up a backup by file name — only inside this instance's folder."""
    for item in list_backups(settings):
        if item.name == name:
            return item
    raise BackupError(f"No backup named {name!r} for this instance")


# ---------------------------------------------------------------- operations


def backup(settings: Settings, *, now: datetime | None = None, label: str = "") -> BackupFile:
    """Take a backup now (D-04)."""
    conn = Connection.from_settings(settings)
    tool = resolve_tool(settings, conn)
    folder = backup_dir(settings)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = (now or datetime.now(UTC)).strftime(TIMESTAMP)
    suffix = f"_{label}" if label else ""
    target = folder / f"{settings.instance_slug}_{stamp}{suffix}.dump"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{settings.instance_slug}_{stamp}{suffix}-{n}.dump"

    argv, to_stdout = dump_command(conn, tool, target)
    try:
        _run(argv, conn, stdout=target if to_stdout else None)
        if not target.exists() or target.stat().st_size == 0:
            raise BackupError("pg_dump produced an empty file")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    target.chmod(0o600)
    log.info("backup written: %s", target)
    created = _parse_created(target, settings.instance_slug) or datetime.now(UTC)
    return BackupFile(target, created, target.stat().st_size)


def prune(settings: Settings, *, now: datetime | None = None) -> list[Path]:
    """Delete backups older than the retention period; always keep the newest (N-06)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.backup_retention_days)
    removed = []
    for item in list_backups(settings)[1:]:
        if item.created < cutoff:
            item.path.unlink(missing_ok=True)
            removed.append(item.path)
    return removed


def ensure_recent_backup(settings: Settings, *, now: datetime | None = None) -> BackupFile | None:
    """Daily backup (I-06): take one if the newest is older than 24 h, then prune."""
    now = now or datetime.now(UTC)
    backups = list_backups(settings)
    if backups and now - backups[0].created < DAILY:
        return None
    made = backup(settings, now=now)
    prune(settings, now=now)
    return made


def restore(settings: Settings, source: Path) -> BackupFile:
    """Replace the database with ``source``. Takes a safety backup first; returns it."""
    if not source.is_file():
        raise BackupError(f"Backup file not found: {source}")
    conn = Connection.from_settings(settings)
    tool = resolve_tool(settings, conn)
    safety = backup(settings, label="before-restore")
    if tool == "local":
        with tempfile.TemporaryDirectory() as tmp:
            listing = subprocess.run(  # noqa: S603
                ["pg_restore", "--list", str(source)],  # noqa: S607 - resolved on PATH like pg_dump
                capture_output=True,
                text=True,
                check=False,
            )
            if listing.returncode != 0:
                raise BackupError(f"Not a valid backup file: {listing.stderr.strip()}")
            list_file = Path(tmp) / "restore.list"
            list_file.write_text(
                "\n".join(
                    line for line in listing.stdout.splitlines() if _RESTORE_LIST_FILTER not in line
                ),
                encoding="utf-8",
            )
            _run(restore_command(conn, tool, source, list_file), conn)
    else:
        _run(restore_command(conn, tool, source, None), conn, stdin=source)
    log.info("restored %s from %s", conn.database, source)
    return safety
