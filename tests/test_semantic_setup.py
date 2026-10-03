"""`make model` and `make reindex` (S-08, ADR-0013)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.embedder import MODEL_REPO, MODEL_REVISION, read_manifest
from app.main import create_app
from app.migrate import upgrade_to_head
from scripts import semantic as cli
from scripts.bootstrap_instance import InstanceSpec, bootstrap, drop_database
from tests.conftest import make_settings
from tests.fake_embedder import HashingEmbedder

pytestmark = pytest.mark.req("S-08")

FILES = {"onnx/model.onnx": b"fake onnx bytes", "tokenizer.json": b'{"fake": true}'}


@pytest.fixture
def fake_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    monkeypatch.setattr(
        cli, "MODEL_FILES", {n: hashlib.sha256(b).hexdigest() for n, b in FILES.items()}
    )
    return FILES


def _fetcher(files: dict[str, bytes], urls: list[str]) -> Callable[..., None]:
    def fetch(url: str, target: Path, say: Callable[[str], None]) -> None:
        urls.append(url)
        target.write_bytes(files[url.split(MODEL_REVISION + "/", 1)[1]])

    return fetch


def test_install_downloads_pinned_files_and_verifies_them(
    tmp_path: Path, fake_files: dict[str, bytes]
) -> None:
    urls: list[str] = []
    said: list[str] = []
    dest = cli.install_model(tmp_path / "m", fetch=_fetcher(fake_files, urls), say=said.append)
    assert all(u.startswith(f"https://huggingface.co/{MODEL_REPO}/resolve/") for u in urls)
    assert all(MODEL_REVISION in u for u in urls)
    assert (dest / "onnx/model.onnx").read_bytes() == b"fake onnx bytes"
    assert read_manifest(dest)["revision"] == MODEL_REVISION
    assert "Restart running instances" in said[-1]

    # Already there and intact: nothing is downloaded again.
    again: list[str] = []
    cli.install_model(dest, fetch=_fetcher(fake_files, again), say=said.append)
    assert again == []
    assert said[-1].startswith("Model already installed")


def test_install_refuses_a_file_with_the_wrong_checksum(
    tmp_path: Path, fake_files: dict[str, bytes]
) -> None:
    tampered = {**fake_files, "tokenizer.json": b"tampered"}
    with pytest.raises(cli.SetupError, match="expected checksum"):
        cli.install_model(tmp_path / "m", fetch=_fetcher(tampered, []), say=lambda _: None)
    assert not (tmp_path / "m").exists()  # nothing half-installed


def test_install_from_a_folder(tmp_path: Path, fake_files: dict[str, bytes]) -> None:
    source = tmp_path / "src"
    for name, data in fake_files.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes(data)
    dest = cli.install_model(tmp_path / "m", source_dir=source, say=lambda _: None)
    assert (dest / "tokenizer.json").read_bytes() == fake_files["tokenizer.json"]
    with pytest.raises(cli.SetupError, match="not found"):
        cli.install_model(tmp_path / "other", source_dir=tmp_path / "empty", say=lambda _: None)


def test_cli_entry_points(
    tmp_path: Path,
    fake_files: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "src"
    for name, data in fake_files.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes(data)
    assert cli.main(["model", "--dest", str(tmp_path / "m"), "--from", str(source)]) == 0
    assert cli.main(["model", "--dest", str(tmp_path / "x"), "--from", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err
    monkeypatch.setenv("INSTANCE_ENV_FILE", str(tmp_path / "missing.env"))
    assert cli.main(["reindex"]) == 1


@pytest.fixture
def instance(admin_url: str, tmp_path: Path) -> Iterator[Settings]:
    spec = InstanceSpec(name=f"tr-{uuid.uuid4().hex[:6]}", port=5193, app_env="test")
    info = bootstrap(spec, admin_url, None)
    settings = make_settings(info.database_url, instance_name="Reindex", backup_dir=str(tmp_path))
    upgrade_to_head(settings)
    yield settings
    drop_database(spec, admin_url)


def test_reindex_embeds_every_contact(instance: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(instance, background_indexing=False)) as client:
        types = {t["name"]: t["id"] for t in client.get("/api/contact-types").json()}
        for i in range(40):  # more than one batch
            client.post("/api/contacts", json={"display_name": f"Person {i}",
                                               "contact_type_id": types["Employee"]})  # fmt: skip
    monkeypatch.setattr(cli, "load_settings", lambda: instance)
    monkeypatch.setattr(cli, "load_embedder", lambda _dir: HashingEmbedder())
    said: list[str] = []
    assert cli.reindex(say=said.append) == 40
    assert said[-1] == "Reindex: 40 of 40 contacts indexed."
    assert cli.reindex(say=said.append) == 0  # nothing left to do
