"""Backup command line (D-04, I-06, I-07, N-06).

    make backup  I=business-prod                 # back up now (+ prune old ones)
    make backups I=business-prod                 # list backups
    make restore I=dev FILE=dev_20260924-120000.dump
    make copy-to-dev FROM=business-prod TO=dev ANONYMIZE=1

The instance comes from $INSTANCE_ENV_FILE (set by the Makefile).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.anonymize import anonymize
from app.backup import BackupError, backup, find_backup, list_backups, prune, restore
from app.config import Settings, load_settings
from app.db import create_db_engine, make_session_factory
from app.migrate import upgrade_to_head


def _size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _resolve(settings: Settings, file: str) -> Path:
    candidate = Path(file).expanduser()
    return candidate if candidate.is_file() else find_backup(settings, file).path


def restore_into(settings: Settings, source: Path) -> Path:
    """Restore, then bring the schema up to date (the dump may be older than the code)."""
    safety = restore(settings, source)
    upgrade_to_head(settings)
    return safety.path


def copy_to_dev(source: Settings, target: Settings, *, anonymize_data: bool) -> Path:
    """I-07: copy a (production) database into a non-production instance."""
    if target.is_production:
        raise BackupError(f"Refusing to overwrite production instance '{target.instance_name}'")
    dump = backup(source, label="copy")
    restore_into(target, dump.path)
    if anonymize_data:
        engine = create_db_engine(target)
        try:
            with make_session_factory(engine)() as session:
                anonymize(session)
                session.commit()
        finally:
            engine.dispose()
    return dump.path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up and restore an instance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="back up now, then delete backups past retention")
    sub.add_parser("list", help="list backups, newest first")
    sub.add_parser("prune", help="delete backups past retention (keeps the newest)")
    p_restore = sub.add_parser("restore", help="restore a backup (a safety backup is taken first)")
    p_restore.add_argument("file", help="backup file name or path")
    p_restore.add_argument("--yes", action="store_true", help="required for production instances")
    p_copy = sub.add_parser("copy-to-dev", help="copy another instance's data into this one")
    p_copy.add_argument("--from-env", required=True, help="env file of the source instance")
    p_copy.add_argument("--anonymize", action="store_true")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.command == "backup":
            made = backup(settings)
            removed = prune(settings)
            print(
                f"Backed up to {made.path} ({_size(made.size)}); "
                f"removed {len(removed)} old backup(s)."
            )
        elif args.command == "list":
            items = list_backups(settings)
            for item in items:
                print(f"{item.created:%Y-%m-%d %H:%M} UTC  {_size(item.size):>8}  {item.name}")
            if not items:
                print(f"No backups yet in {settings.resolved_backup_dir}")
        elif args.command == "prune":
            print(f"Removed {len(prune(settings))} old backup(s).")
        elif args.command == "restore":
            if settings.is_production and not args.yes:
                print(
                    f"'{settings.instance_name}' is a production instance: re-run with --yes "
                    "(make restore ... YES=1) to confirm.",
                    file=sys.stderr,
                )
                return 2
            safety = restore_into(settings, _resolve(settings, args.file))
            print(f"Restored. The previous data was saved to {safety}")
        elif args.command == "copy-to-dev":
            source = load_settings(args.from_env)
            dump = copy_to_dev(source, settings, anonymize_data=args.anonymize)
            note = " and anonymized" if args.anonymize else ""
            print(
                f"Copied '{source.instance_name}' into '{settings.instance_name}'{note} "
                f"(via {dump.name})."
            )
    except (BackupError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
