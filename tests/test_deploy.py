"""Install files for Windows and Mac (I-10, I-13, ADR-0019): compose wiring, launchers and the
zip people download. The stack itself is exercised by `make container-test`."""

from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.version import app_version
from scripts import bundle

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
MAC_START = (ROOT / "deploy/mac/start.sh").read_text(encoding="utf-8")
WIN_START = (ROOT / "deploy/windows/start.ps1").read_text(encoding="utf-8")
SCRIPTS = [
    ROOT / "deploy/mac/start.sh",
    ROOT / "deploy/mac/stop.sh",
    ROOT / "deploy/windows/start.ps1",
    ROOT / "deploy/windows/stop.ps1",
]


def _service(name: str) -> str:
    match = re.search(rf"^  {name}:\n((?:    .*\n|\n)+)", COMPOSE, re.MULTILINE)
    assert match, name
    return match.group(1)


@pytest.mark.req("I-10", "N-04")
def test_database_has_no_published_port_and_sits_on_an_internal_network() -> None:
    db = _service("db")
    assert "ports:" not in db
    assert "networks: [backend]" in db
    assert re.search(r"^  backend:\n    internal: true", COMPOSE, re.MULTILINE)


@pytest.mark.req("I-10", "N-01")
@pytest.mark.parametrize("name", ["work", "personal"])
def test_instances_listen_on_this_computer_only(name: str) -> None:
    ports = re.findall(r'- "([^"]+)"', _service(name).split("ports:")[1].split("volumes:")[0])
    assert ports
    assert all(p.startswith("127.0.0.1:") for p in ports)


@pytest.mark.req("I-10")
def test_instances_are_hardened_and_restart_with_docker() -> None:
    block = COMPOSE.split("x-instance: &instance")[1].split("x-instance-env")[0]
    for line in (
        "restart: unless-stopped",
        "read_only: true",
        "cap_drop: [ALL]",
        'security_opt: ["no-new-privileges:true"]',
        "condition: service_completed_successfully",
    ):
        assert line in block


@pytest.mark.req("I-10", "I-02")
def test_each_instance_mounts_only_its_own_secrets_and_backups() -> None:
    for name, other in (("work", "personal"), ("personal", "work")):
        service = _service(name)
        assert f"{name}-instance:/run/contacts/instance:ro" in service
        assert f"{other}-instance" not in service
        assert f"}}/{name}\n        target: /backups" in service


@pytest.mark.req("I-12")
def test_container_instances_restore_on_an_empty_database() -> None:
    assert 'RESTORE_ON_EMPTY: "1"' in COMPOSE


@pytest.mark.req("I-13")
def test_launchers_write_every_setting_compose_reads() -> None:
    used = set(re.findall(r"\$\{([A-Z_]+)(?::[-?][^}]*)?\}", COMPOSE))
    provided = {"APP_VERSION", "CONTACTS_BACKUPS"}  # exported by the start scripts
    optional = {
        "BACKUP_RETENTION_DAYS",
        "SEMANTIC_SEARCH",
        "WORK_HOME_COMPANY",
        "WORK_PALETTE",
        "PERSONAL_HOME_COMPANY",
        "PERSONAL_PALETTE",
        # container-test overrides; the defaults are the real install
        "PYTHON_IMAGE",
        "POSTGRES_IMAGE",
        "PG_MAJOR",
        "WITH_MODEL",
        "BUILD_NETWORK",
    }
    for script in (MAC_START, WIN_START):
        written = set(re.findall(r"^([A-Z_]+)=", script, re.MULTILINE))
        assert used - provided - optional <= written
        assert "COMPOSE_PROFILES" in written


@pytest.mark.req("I-13")
def test_both_launchers_ask_the_same_questions_and_use_the_same_ports() -> None:
    for text in ("Which contact books do you want?", "1  Work", "2  Personal", "3  Both"):
        assert text in MAC_START
        assert text in WIN_START
    for port in ("WORK_PORT=5170", "PERSONAL_PORT=5171"):
        assert port in MAC_START
        assert port in WIN_START
    for script in (MAC_START, WIN_START):
        assert "--project-name" in script
        assert "--wait" in script


@pytest.mark.req("I-13")
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_plain_ascii(path: Path) -> None:
    """Windows PowerShell 5.1 reads BOM-less files as ANSI; keep every script ASCII."""
    path.read_bytes().decode("ascii")


@pytest.mark.req("I-13")
def test_mac_scripts_run_in_the_bash_that_ships_with_macos() -> None:
    for path in SCRIPTS:
        if path.suffix == ".sh":
            result = subprocess.run(  # noqa: S603
                ["bash", "-n", str(path)],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            text = path.read_text()
            # bash 3.2: no associative arrays, ${x,,}, mapfile or |&
            for newer in ("declare -A", ",,}", "^^}", "mapfile", "|&"):
                assert newer not in text, (path.name, newer)


@pytest.mark.req("I-13")
def test_names_typed_at_first_start_cannot_break_the_settings_file() -> None:
    script = ROOT / "deploy/mac/start.sh"
    cleaned = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "bash",
            "-c",
            f'source <(sed -n "/^clean()/,/^}}/p" "{script}"); clean \'  Acme "Q$x`1`\\\\ \' Work',
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert cleaned == "Acme Qx1"


# ---------------------------------------------------------------- the zip (I-13)


@pytest.fixture(scope="module")
def zip_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return bundle.build(tmp_path_factory.mktemp("dist"))


@pytest.mark.req("I-13")
def test_bundle_has_launchers_guide_and_program(zip_path: Path) -> None:
    top = f"Contact Manager {app_version()}"
    assert zip_path.name == f"Contact-Manager-{app_version()}.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for name in (
            "Start here.html",
            "Start Contact Manager.command",
            "Stop Contact Manager.command",
            "Start Contact Manager.bat",
            "Stop Contact Manager.bat",
            "program/Dockerfile",
            "program/compose.yaml",
            "program/uv.lock",
            "program/app/container.py",
            "program/deploy/windows/start.ps1",
        ):
            assert f"{top}/{name}" in names, name
        guide = zf.read(f"{top}/Start here.html").decode()
        assert "<h2" in guide
        assert "Docker Desktop" in guide
        assert "<script" not in guide


@pytest.mark.req("I-13", "N-05")
def test_bundle_never_carries_secrets_or_local_files(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            assert "/instances/" not in name
            assert not name.endswith((".env", ".dump", ".pyc"))
            assert "__pycache__" not in name
            assert "/tests/" not in name


@pytest.mark.req("I-13")
def test_bundle_permissions_and_line_endings(zip_path: Path) -> None:
    top = f"Contact Manager {app_version()}"
    with zipfile.ZipFile(zip_path) as zf:
        mode = {i.filename: (i.external_attr >> 16) & 0o777 for i in zf.infolist()}
        assert mode[f"{top}/Start Contact Manager.command"] == 0o755
        assert mode[f"{top}/program/deploy/mac/start.sh"] == 0o755
        assert mode[f"{top}/program/compose.yaml"] == 0o644
        bat = zf.read(f"{top}/Start Contact Manager.bat")
        ps1 = zf.read(f"{top}/program/deploy/windows/start.ps1")
        assert b"\r\n" in bat
        assert b"\n" not in bat.replace(b"\r\n", b"")
        assert b"\n" not in ps1.replace(b"\r\n", b"")
        assert b"\r\n" not in zf.read(f"{top}/program/deploy/mac/start.sh")
