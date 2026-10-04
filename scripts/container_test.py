"""End-to-end check of the container install (I-10 to I-12, I-14, ADR-0019).

    make container-test          # uses Docker; takes a few minutes the first time

Builds the image and starts the whole stack under its own project name, on spare ports and
with a throw-away settings folder, then checks: both contact books answer /healthz with the
version; the database publishes no port; the app runs read-only as a non-root user; backups
land in the host folder; an instance backs up before migrating (I-11); after the database
volumes are deleted ("a new computer"), the newest backup comes back on the next start
(I-12). Everything it created is removed at the end, including on failure.

Environment overrides for machines that cannot reach Docker Hub or Debian (the defaults
match the real install): PYTHON_IMAGE, POSTGRES_IMAGE, PG_MAJOR, WITH_MODEL, BUILD_NETWORK.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.version import app_version

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "contact-manager-test"
PORTS = {"work": 5190, "personal": 5191}
SETTINGS = """# written by scripts/container_test.py
COMPOSE_PROFILES=work,personal
WORK_NAME="Test Work"
WORK_PORT={work}
PERSONAL_NAME="Test Personal"
PERSONAL_PORT={personal}
PHONE_REGION=US
"""


class Failed(AssertionError):
    pass


def say(message: str) -> None:
    print(f"· {message}", flush=True)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)
    say(f"ok: {message}")


class Stack:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.settings = home / "settings.env"
        self.backups = home / "Backups"
        self.env = {
            **os.environ,
            "APP_VERSION": app_version(),
            "CONTACTS_BACKUPS": str(self.backups),
        }
        if os.getuid() != 0 and "APP_UID" not in self.env:  # as deploy/mac/start.sh does
            self.env |= {"APP_UID": str(os.getuid()), "APP_GID": str(os.getgid())}

    def compose(self, *args: str, check_ok: bool = True) -> subprocess.CompletedProcess[str]:
        argv = [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "--env-file",
            str(self.settings),
            "-f",
            str(ROOT / "compose.yaml"),
            *args,
        ]
        result = subprocess.run(  # noqa: S603 - fixed argv
            argv, env=self.env, capture_output=True, text=True, check=False
        )
        if check_ok and result.returncode != 0:
            raise Failed(f"docker compose {' '.join(args)} failed:\n{result.stdout}{result.stderr}")
        return result

    def up(self) -> None:
        self.compose("up", "-d", "--build", "--wait", "--wait-timeout", "300")

    def exec_python(self, service: str, code: str) -> str:
        return self.compose("exec", "-T", service, "python", "-c", code).stdout


def get_json(url: str, *, data: dict[str, Any] | None = None) -> Any:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(  # noqa: S310 - local URL
        url, data=body, headers={"Content-Type": "application/json"} if body else {}
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.loads(response.read())


def wait_healthy(port: int, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            body: dict[str, Any] = get_json(f"http://127.0.0.1:{port}/healthz")
            return body
        except (urllib.error.URLError, OSError):
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def inspect(container_id: str) -> dict[str, Any]:
    out = subprocess.run(  # noqa: S603
        ["docker", "inspect", container_id],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data: dict[str, Any] = json.loads(out)[0]
    return data


DOWNGRADE_ONE = (
    "import os; from app.container import prepare_environment; "
    "prepare_environment(os.environ); "
    "from alembic import command; from app.config import load_settings; "
    "from app.migrate import alembic_config; "
    "command.downgrade(alembic_config(load_settings().sqlalchemy_url), '-1')"
)


def run(stack: Stack) -> None:
    say(f"building and starting {PROJECT} (version {app_version()})")
    for name in PORTS:  # as the Start scripts do: Docker must never create these
        (stack.backups / name).mkdir(parents=True)
    stack.up()

    for name, port in PORTS.items():
        health = wait_healthy(port)
        check(
            health["status"] == "ok" and health["version"] == app_version(),
            f"{name} answers /healthz with version {app_version()}",
        )

    db_id = stack.compose("ps", "-q", "db").stdout.strip()
    check(not inspect(db_id)["HostConfig"]["PortBindings"], "the database publishes no port")
    work = inspect(stack.compose("ps", "-q", "work").stdout.strip())
    check(work["HostConfig"]["ReadonlyRootfs"], "the app's filesystem is read-only")
    user = work["Config"]["User"]
    expected = f"{stack.env.get('APP_UID', '10001')}:{stack.env.get('APP_GID', '10001')}"
    check(user == expected, f"the app runs as an unprivileged user ({user})")
    bindings = work["HostConfig"]["PortBindings"][f"{PORTS['work']}/tcp"]
    check(
        all(b["HostIp"] == "127.0.0.1" for b in bindings), "the app listens on this computer only"
    )

    work_url = f"http://127.0.0.1:{PORTS['work']}"
    types = get_json(f"{work_url}/api/contact-types")
    created = get_json(
        f"{work_url}/api/contacts",
        data={"display_name": "Container Test Person", "contact_type_id": types[0]["id"]},
    )
    check(created["id"] > 0, "a contact can be saved")

    stack.compose("exec", "-T", "work", "python", "-m", "app.container", "backup")
    dumps = sorted((stack.backups / "work").glob("test-work_*.dump"))
    check(bool(dumps), f"backups are written to the host folder ({len(dumps)} file(s))")

    # I-11: an instance one migration behind backs up before migrating on its next start.
    stack.exec_python("work", DOWNGRADE_ONE)
    stack.compose("restart", "work")
    wait_healthy(PORTS["work"])
    check(
        any((stack.backups / "work").glob("*_before-upgrade.dump")),
        "a before-upgrade backup is taken when migrations are pending",
    )

    # I-12: "a new computer": database volumes gone, backup folder and settings kept.
    stack.compose("down", "--volumes")
    stack.up()
    wait_healthy(PORTS["work"])
    people = get_json(f"{work_url}/api/contacts?q=Container")
    names = [p["display_name"] for p in people]
    check("Container Test Person" in names, "a new database starts from the newest backup")


MOUNT_CHECK = r"""
echo "user: $(id)"
echo "BACKUP_DIR=${BACKUP_DIR:-unset}"
echo "folder: $(ls -lnd "${BACKUP_DIR:-/backups}" 2>&1)"
echo "mount: $(grep -E ' /backups( |/)' /proc/self/mountinfo 2>&1)"
echo "capabilities: $(grep -E '^Cap(Eff|Bnd)' /proc/self/status | tr '\n' ' ')"
if touch "${BACKUP_DIR:-/backups}/.mount-check" 2>/tmp/err; then echo "write: OK"; \
  rm -f "${BACKUP_DIR:-/backups}/.mount-check"; else echo "write: FAIL $(cat /tmp/err)"; fi
python - <<'PY'
import os, tempfile
folder = os.environ.get("BACKUP_DIR", "/backups")
for label, call in (
    ("python mkdir(exist_ok)", lambda: os.makedirs(folder, exist_ok=True)),
    ("python temp file", lambda: tempfile.NamedTemporaryFile(dir=folder).close()),
):
    try:
        call()
        print(f"{label}: OK")
    except OSError as exc:
        print(f"{label}: FAIL {exc!r}")
PY
"""


def mount_report(stack: Stack, service: str) -> str:
    """What a fresh copy of ``service`` sees in its backup folder: same user, mounts and
    restrictions, started through Compose (the probe's ``docker run`` cannot reproduce every
    Compose setting)."""
    result = stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--entrypoint",
        "sh",
        service,
        "-c",
        MOUNT_CHECK,
        check_ok=False,
    )
    host = subprocess.run(  # noqa: S603
        ["ls", "-lna", str(stack.backups), str(stack.backups / service)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return f"{result.stdout}{result.stderr}--- on this computer ---\n{host.stdout}{host.stderr}"


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    # a space in the path, like "~/Contact Manager"
    with tempfile.TemporaryDirectory(prefix="contact manager test-") as tmp:
        home = Path(tmp)
        stack = Stack(home)
        stack.settings.write_text(SETTINGS.format(**PORTS), encoding="utf-8")
        try:
            run(stack)
        except (Failed, urllib.error.URLError, OSError, KeyError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            for service in ("setup", "work", "personal"):
                logs = stack.compose("logs", "--tail", "40", service, check_ok=False)
                print(f"--- {service} logs ---\n{logs.stdout}{logs.stderr}", file=sys.stderr)
            print(
                f"--- backup folder, as work sees it ---\n{mount_report(stack, 'work')}",
                file=sys.stderr,
            )
            return 1
        finally:
            stack.compose("down", "--volumes", "--remove-orphans", check_ok=False)
            # files written by the containers' user may not be ours to delete
            subprocess.run(  # noqa: S603
                ["chmod", "-R", "u+rwX", str(home)],  # noqa: S607
                check=False,
                capture_output=True,
            )
    say("container install works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
