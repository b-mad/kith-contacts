"""Move instances run with ./run.sh into the container install (ADR-0019).

    make move-to-containers WORK=business-prod PERSONAL=personal-prod

For each instance named: takes a fresh backup, copies it into the container install's backup
folder (``~/KithContacts/Backups/work`` or ``…/personal``) and writes
``~/KithContacts/settings.env`` with the same name, color, contact types, port, home
company and phone region. On its first start each container instance finds its new database
empty and restores that backup (I-12). Nothing in the old instances is changed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from app.backup import BackupError, backup
from app.config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent
DATA = Path.home() / "KithContacts"
SLOTS = ("work", "personal")


class MoveError(RuntimeError):
    pass


def _quoted(value: str) -> str:
    if any(c in value for c in '"$\\`\n'):
        raise MoveError(f"{value!r} contains characters settings.env cannot hold")
    return f'"{value}"'


def render_settings(instances: dict[str, Settings]) -> str:
    """settings.env in the same shape the start scripts write (deploy/mac/start.sh)."""
    lines = [
        '# Kith Contacts settings. Change a value, then double-click "Start Kith Contacts" again.',
        "# No passwords are kept here. Moved from ./run.sh instances by "
        "scripts/move_to_containers.py.",
        "",
        "# Contact books to run: work, personal, or work,personal",
        f"COMPOSE_PROFILES={','.join(instances)}",
    ]
    for slot, s in instances.items():
        key = slot.upper()
        lines += [
            "",
            f"{key}_NAME={_quoted(s.instance_name)}",
            f"{key}_COLOR={_quoted(s.instance_color)}",
            f"{key}_TYPES={_quoted(','.join(s.contact_types))}",
            f"{key}_PORT={s.port}",
        ]
        if s.home_company:
            lines.append(f"{key}_HOME_COMPANY={_quoted(s.home_company)}")
    first = next(iter(instances.values()))
    lines += [
        "",
        "# Country for phone numbers typed without a +code (two letters, e.g. US, GB, CA)",
        f"PHONE_REGION={first.phone_region}",
        "",
    ]
    return "\n".join(lines)


def move(
    names: dict[str, str],
    *,
    data: Path = DATA,
    instances_dir: Path = ROOT / "instances",
    force: bool = False,
    say: Callable[[str], None] = print,
) -> Path:
    if not names:
        raise MoveError("Name at least one instance: WORK=<instance> and/or PERSONAL=<instance>")
    settings_file = data / "settings.env"
    if settings_file.exists() and not force:
        raise MoveError(
            f"{settings_file} already exists: the container install has been set up here. "
            "Re-run with FORCE=1 to replace it."
        )
    loaded = {slot: load_settings(instances_dir / f"{name}.env") for slot, name in names.items()}
    ports = [s.port for s in loaded.values()]
    if len(set(ports)) != len(ports):
        raise MoveError(f"The instances share a port ({ports}); give them different ports")
    for slot, settings in loaded.items():
        made = backup(settings)
        folder = data / "Backups" / slot
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(made.path, folder / made.name)
        say(f"{names[slot]} → {slot}: backed up and copied {made.name}")
    data.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(render_settings(loaded), encoding="utf-8")
    return settings_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", help="instance to run as the work contact book")
    parser.add_argument("--personal", help="instance to run as the personal contact book")
    parser.add_argument("--force", action="store_true", help="replace an existing settings.env")
    args = parser.parse_args(argv)
    names = {slot: getattr(args, slot) for slot in SLOTS if getattr(args, slot)}
    try:
        written = move(names, force=args.force)
    except (MoveError, BackupError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {written}")
    print("Next:")
    for name in names.values():
        print(f"  - stop ./run.sh {name} (changes made after this backup are not moved)")
    print("  - double-click Start Kith Contacts, or run deploy/mac/start.sh from here")
    print("  - check your contacts, then retire the old env files and any launchd backup job")
    return 0


if __name__ == "__main__":
    sys.exit(main())
