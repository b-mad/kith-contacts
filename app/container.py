"""Container entry point for the image built from ``Dockerfile`` (I-10, I-12, ADR-0019).

    python -m app.container secrets   one-shot, before PostgreSQL first starts: admin password
    python -m app.container setup     one-shot: each instance's database and role
    python -m app.container serve     run one instance (the image's default command)
    python -m app.container health    Docker health check
    python -m app.container backup | backups | restore FILE [--yes]   (scripts/backup.py)

Passwords live only in Docker volumes: ``/run/contacts/db`` (shared by ``secrets``,
PostgreSQL and ``setup``) and one ``/run/contacts/instance`` volume per instance, which
only ``setup`` and that instance mount. Everything people may change is in
``~/KithContacts/settings.env`` on the host and arrives as environment variables.
"""

from __future__ import annotations

import contextlib
import os
import secrets as token
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from urllib.parse import quote

import psycopg
from pydantic import ValidationError

from app.backup import BackupError, BackupFile, restore_newest_into_empty
from app.config import Settings, load_settings

DB_SECRETS = Path("/run/contacts/db")
INSTANCES = Path("/run/contacts/instances")
INSTANCE = Path("/run/contacts/instance")
BACKUPS = Path("/backups")
APP_UID = 10001  # the image's "contacts" user (Dockerfile); compose may run as another
ADMIN_PASSWORD_FILE = "postgres-password"  # noqa: S105 - a file name, not a password
URL_FILE = "database-url"
INSTANCE_NAMES = ("work", "personal")
BACKUP_COMMANDS = {"backup": "backup", "backups": "list", "restore": "restore"}
SETTING_KEYS = frozenset(name.upper() for name in Settings.model_fields)

Say = Callable[[str], None]


class ContainerError(RuntimeError):
    pass


def _say(message: str) -> None:
    print(message, flush=True)


def write_secret(path: Path, value: str) -> None:
    """Write a file only its owner can read (the app user; root in PostgreSQL's entrypoint)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    tmp.replace(path)


def read_secret(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


# ---------------------------------------------------------------- secrets


def ensure_admin_password(folder: Path = DB_SECRETS) -> bool:
    """Generate PostgreSQL's admin password once; True when it was created now."""
    path = folder / ADMIN_PASSWORD_FILE
    if read_secret(path):
        return False
    write_secret(path, token.token_urlsafe(32))
    return True


# ---------------------------------------------------------------- setup


def parse_instances(value: str) -> tuple[str, ...]:
    """``COMPOSE_PROFILES`` as chosen on first start, e.g. ``work,personal``."""
    names = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    unknown = [n for n in names if n not in INSTANCE_NAMES]
    if unknown:
        raise ContainerError(
            f"Unknown contact book {', '.join(unknown)!s}: use {' or '.join(INSTANCE_NAMES)}"
        )
    if not names:
        raise ContainerError(
            "No contact book chosen: set COMPOSE_PROFILES to work, personal or both"
        )
    return names


def wait_for_database(
    url: str, *, timeout: float = 120, interval: float = 2, say: Say = _say
) -> None:
    """Docker may start an instance before PostgreSQL is ready (e.g. after a restart)."""
    deadline = time.monotonic() + timeout
    told = False
    while True:
        try:
            with psycopg.connect(url, connect_timeout=3):
                return
        except psycopg.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise ContainerError(f"The database did not become reachable: {exc}") from exc
            if not told:
                say("Waiting for the database to start…")
                told = True
            time.sleep(interval)


def admin_url(password: str, host: str = "db", port: int = 5432) -> str:
    return f"postgresql://postgres:{quote(password, safe='')}@{host}:{port}/postgres"


def app_ids(environ: Mapping[str, str] = os.environ) -> tuple[int, int]:
    """The user the instances run as: ``APP_UID``/``APP_GID`` from compose, else the image's.

    The start scripts pass the computer's own user on macOS and Linux, because Docker Desktop
    shows a shared folder as owned by that user and lets nobody else write to it.
    """

    def number(key: str) -> int:
        value = environ.get(key, "").strip()
        return int(value) if value.isdigit() else APP_UID

    return number("APP_UID"), number("APP_GID")


def give_to_app(path: Path, ids: tuple[int, int] | None = None) -> None:
    """``setup`` runs as root so it can hand files and folders to the app user. A shared
    folder that ignores the change is fine as long as the app runs as its owner (above)."""
    if os.geteuid() != 0:
        return
    uid, gid = ids or app_ids()
    with contextlib.suppress(OSError):
        os.chown(path, uid, gid)


def setup_instances(
    names: Sequence[str],
    admin: str,
    folder: Path = INSTANCES,
    backups: Path | None = BACKUPS,
    *,
    say: Say = _say,
) -> dict[str, bool]:
    """Create or repair each instance's database and role; save its URL for that instance,
    and make sure its backup folder exists and the app may write to it (N-06)."""
    from scripts.bootstrap_instance import BootstrapError, ensure_database

    created: dict[str, bool] = {}
    for name in names:
        url_file = folder / name / URL_FILE
        try:
            url, created[name] = ensure_database(name, admin, read_secret(url_file))
        except BootstrapError as exc:
            raise ContainerError(str(exc)) from exc
        write_secret(url_file, url)
        give_to_app(url_file)
        if backups is not None:
            target = backups / name
            target.mkdir(parents=True, exist_ok=True)
            give_to_app(target)
        say(f"{name}: database {'created' if created[name] else 'ready'}")
    return created


# ---------------------------------------------------------------- serve


def prepare_environment(environ: MutableMapping[str, str], folder: Path = INSTANCE) -> None:
    """Compose passes unset settings as empty strings: drop them so defaults apply; read the
    instance's database URL from its volume unless one was given."""
    for key in [k for k, v in environ.items() if k in SETTING_KEYS and not v.strip()]:
        del environ[key]
    if "DATABASE_URL" not in environ:
        url = read_secret(folder / URL_FILE)
        if url is None:
            raise ContainerError(
                f"No database settings in {folder}: the setup step has not run for this instance"
            )
        environ["DATABASE_URL"] = url


def check_backup_folder(settings: Settings) -> None:
    """N-06: an instance that cannot write its backups must not look healthy. Refuse to start
    with a message the Start script shows, instead of failing quietly every night."""
    folder = settings.resolved_backup_dir
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write-check-"):
            pass
    except OSError as exc:
        raise ContainerError(
            f"Cannot write backups to {folder} (the KithContacts/Backups folder on this "
            f"computer): {exc.strerror or exc}. Kith Contacts does not start without "
            "working backups."
        ) from exc


def restore_on_first_start(settings: Settings, *, say: Say = _say) -> BackupFile | None:
    """I-12: a brand-new database is filled from the newest backup in its folder."""
    try:
        restored = restore_newest_into_empty(settings)
    except BackupError as exc:
        raise ContainerError(f"Could not restore the newest backup: {exc}") from exc
    if restored is not None:
        say(f"New database: restored the newest backup, {restored.name}")
    return restored


def serve(environ: MutableMapping[str, str] = os.environ) -> int:
    from app.__main__ import run

    prepare_environment(environ)
    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Invalid settings in settings.env:\n{exc}", file=sys.stderr)
        return 2
    check_backup_folder(settings)
    wait_for_database(str(settings.database_url))
    if environ.get("RESTORE_ON_EMPTY", "").lower() in {"1", "true", "yes"}:
        restore_on_first_start(settings)
    return run(settings)


def health(port: str | None = None) -> int:
    url = f"http://127.0.0.1:{port or os.environ.get('PORT', '5170')}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            return 0 if response.status == 200 else 1
    except (urllib.error.URLError, OSError):
        return 1


# ---------------------------------------------------------------- command line


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv) or ["serve"]
    command = args[0]
    try:
        if command == "secrets":
            made = ensure_admin_password()
            _say("Database password created" if made else "Database password ready")
            return 0
        if command == "setup":
            password = read_secret(DB_SECRETS / ADMIN_PASSWORD_FILE)
            if password is None:
                raise ContainerError("The database password is missing: run the secrets step")
            admin = admin_url(password)
            wait_for_database(admin)
            setup_instances(parse_instances(os.environ.get("CONTACTS_INSTANCES", "")), admin)
            return 0
        if command == "serve":
            return serve()
        if command == "health":
            return health()
        if command in BACKUP_COMMANDS:
            # e.g. docker compose -p kith-contacts exec work python -m app.container backup
            from scripts.backup import main as backup_main

            prepare_environment(os.environ)
            return backup_main([BACKUP_COMMANDS[command], *args[1:]])
    except (ContainerError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        "usage: python -m app.container secrets|setup|serve|health|backup|backups|restore FILE"
        f" (got {command!r})"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
