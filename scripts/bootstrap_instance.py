"""Create an isolated instance: database, login role and env file (I-01, I-02).

Usage:
    uv run python -m scripts.bootstrap_instance --name dev --port 5180 --env development

The role owns only its own database, and CONNECT is revoked from PUBLIC, so
one instance cannot read another instance's data (ADR-0005).
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ADMIN_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
ENVIRONMENTS = ("development", "production", "test")


class BootstrapError(RuntimeError):
    pass


def database_name(name: str) -> str:
    return "contacts_" + name.replace("-", "_")


def role_name(name: str) -> str:
    return database_name(name) + "_app"


@dataclass(frozen=True)
class InstanceSpec:
    name: str
    port: int
    app_env: str
    color: str = "#1f6feb"
    contact_types: str = "Employee,Customer,Vendor"
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not NAME_PATTERN.fullmatch(self.name):
            raise BootstrapError(
                f"Invalid instance name {self.name!r}: use 2-31 lowercase letters, digits or '-'"
            )
        if self.app_env not in ENVIRONMENTS:
            raise BootstrapError(f"Invalid environment {self.app_env!r}")
        if not 1024 <= self.port <= 65535:
            raise BootstrapError(f"Invalid port {self.port}")

    @property
    def database(self) -> str:
        return database_name(self.name)

    @property
    def role(self) -> str:
        return role_name(self.name)

    @property
    def title(self) -> str:
        return self.display_name or self.name.replace("-", " ").title()


@dataclass(frozen=True)
class InstanceInfo:
    spec: InstanceSpec
    database_url: str
    env_file: Path | None


def _server_part(admin_url: str) -> str:
    parts = urlsplit(admin_url)
    host = parts.hostname or "localhost"
    port = parts.port or 5432
    return f"{host}:{port}"


def create_database(spec: InstanceSpec, admin_url: str) -> str:
    """Create role + database; return the instance's DATABASE_URL."""
    password = secrets.token_urlsafe(24)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (spec.database,)
        ).fetchone()
        if exists:
            raise BootstrapError(f"Database {spec.database} already exists")
        role_exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (spec.role,)
        ).fetchone()
        if role_exists:
            raise BootstrapError(f"Role {spec.role} already exists")

        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(spec.role), sql.Literal(password)
            )
        )
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(spec.database), sql.Identifier(spec.role)
            )
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(spec.database))
        )

    parts = urlsplit(admin_url)
    instance_admin_url = parts._replace(path="/" + spec.database).geturl()
    with psycopg.connect(instance_admin_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    return (
        f"postgresql://{spec.role}:{quote(password, safe='')}"
        f"@{_server_part(admin_url)}/{spec.database}"
    )


def ensure_database(name: str, admin_url: str, saved_url: str | None = None) -> tuple[str, bool]:
    """Create or repair an instance's role and database; return ``(DATABASE_URL, created)``.

    Idempotent, for container installs (I-10, ADR-0019): run on every start. The saved URL's
    password is kept (and re-applied, so a replaced volume still matches); without one a new
    password is generated. Like ``create_database``, the role owns only its own database and
    CONNECT is revoked from PUBLIC (I-02).
    """
    if not NAME_PATTERN.fullmatch(name):
        raise BootstrapError(f"Invalid instance name {name!r}")
    database, role = database_name(name), role_name(name)
    saved = urlsplit(saved_url).password if saved_url else None
    password = unquote(saved) if saved else secrets.token_urlsafe(24)
    created = False
    with psycopg.connect(admin_url, autocommit=True) as conn:
        role_exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        verb = "ALTER" if role_exists else "CREATE"
        conn.execute(
            sql.SQL(verb + " ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            created = True
    instance_admin_url = urlsplit(admin_url)._replace(path="/" + database).geturl()
    with psycopg.connect(instance_admin_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    url = f"postgresql://{role}:{quote(password, safe='')}@{_server_part(admin_url)}/{database}"
    return url, created


def drop_database(spec: InstanceSpec, admin_url: str) -> None:
    """Remove an instance's database and role. Refuses production instances."""
    if spec.app_env == "production":
        raise BootstrapError("Refusing to drop a production instance (I-05)")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(spec.database))
        )
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(spec.role)))


def render_env_file(spec: InstanceSpec, database_url: str) -> str:
    backup = f"~/ContactsBackups/{spec.name}"
    return (
        f"# Instance: {spec.name} — generated by scripts/bootstrap_instance.py\n"
        "# Contains credentials: never commit this file.\n"
        f"INSTANCE_NAME={spec.title}\n"
        f"APP_ENV={spec.app_env}\n"
        f"INSTANCE_COLOR={spec.color}\n"
        f"PORT={spec.port}\n"
        f"DATABASE_URL={database_url}\n"
        f"BACKUP_DIR={backup}\n"
        f"CONTACT_TYPES={spec.contact_types}\n"
        "PHONE_REGION=US\n"
    )


def write_env_file(path: Path, content: str, *, force: bool = False) -> None:
    if path.exists() and not force:
        raise BootstrapError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)


def bootstrap(
    spec: InstanceSpec,
    admin_url: str,
    env_dir: Path | None = ROOT / "instances",
    *,
    force: bool = False,
) -> InstanceInfo:
    env_file = env_dir / f"{spec.name}.env" if env_dir is not None else None
    if env_file is not None and env_file.exists() and not force:
        raise BootstrapError(f"{env_file} already exists (use --force to overwrite)")
    url = create_database(spec, admin_url)
    if env_file is not None:
        write_env_file(env_file, render_env_file(spec, url), force=force)
    return InstanceInfo(spec=spec, database_url=url, env_file=env_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="instance id, e.g. business-prod")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--env", required=True, choices=ENVIRONMENTS, dest="app_env")
    parser.add_argument("--color", default="#1f6feb")
    parser.add_argument("--types", default="Employee,Customer,Vendor")
    parser.add_argument("--title", default=None, help="display name (default from --name)")
    parser.add_argument(
        "--admin-url",
        default=os.environ.get("POSTGRES_ADMIN_URL", DEFAULT_ADMIN_URL),
        help="superuser connection URL (env POSTGRES_ADMIN_URL)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing env file")
    args = parser.parse_args(argv)

    try:
        spec = InstanceSpec(
            name=args.name,
            port=args.port,
            app_env=args.app_env,
            color=args.color,
            contact_types=args.types,
            display_name=args.title,
        )
        info = bootstrap(spec, args.admin_url, force=args.force)
    except (BootstrapError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Created database {spec.database} and role {spec.role}")
    print(f"Wrote {info.env_file}")
    print(f"Start it with: ./run.sh {spec.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
