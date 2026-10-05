"""Search by meaning setup (S-08, ADR-0013).

make model                    # download the model (pinned, checksum-verified)
make model FROM=<folder>      # install it from a folder instead
make reindex I=<instance>     # embed every contact now (the app also does this itself)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app.config import load_settings
from app.db import create_db_engine, make_session_factory
from app.embedder import (
    MODEL_FILES,
    MODEL_NAME,
    MODEL_REPO,
    MODEL_REVISION,
    ModelUnavailable,
    default_model_dir,
    load_embedder,
)
from app.semantic import index_all, index_counts

BASE_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/"
CHUNK = 1024 * 1024


class SetupError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, say: Callable[[str], None]) -> None:
    if not url.startswith("https://"):  # pragma: no cover - constant
        raise SetupError("refusing a non-https download")
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as out:  # noqa: S310
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while block := response.read(CHUNK):
            out.write(block)
            done += len(block)
            if total and done % (10 * CHUNK) < CHUNK:
                say(f"  {done * 100 // total}%")


def install_model(
    dest: Path,
    *,
    source_dir: Path | None = None,
    fetch: Callable[[str, Path, Callable[[str], None]], None] = _download,
    say: Callable[[str], None] = print,
) -> Path:
    """Put the model files in ``dest`` after checking every SHA-256; returns ``dest``."""
    dest = dest.expanduser()
    if all((dest / n).is_file() and sha256(dest / n) == h for n, h in MODEL_FILES.items()):
        say(f"Model already installed in {dest}")
        return dest
    with tempfile.TemporaryDirectory(prefix="contacts-model-") as tmp:
        staging = Path(tmp)
        for name, expected in MODEL_FILES.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if source_dir is not None:
                src = source_dir.expanduser() / name
                if not src.is_file():
                    raise SetupError(f"{src} not found")
                shutil.copyfile(src, target)
            else:
                say(f"Downloading {name} …")
                fetch(BASE_URL + name, target, say)
            actual = sha256(target)
            if actual != expected:
                raise SetupError(
                    f"{name} does not match the expected checksum "
                    f"(expected {expected}, got {actual}); nothing was installed"
                )
        dest.mkdir(parents=True, exist_ok=True)
        for name in MODEL_FILES:
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / name), dest / name)
    manifest = {
        "model": MODEL_NAME,
        "repo": MODEL_REPO,
        "revision": MODEL_REVISION,
        "files": MODEL_FILES,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    say(f"Model installed in {dest}. Restart running instances to use search by meaning.")
    return dest


def reindex(say: Callable[[str], None] = print) -> int:
    settings = load_settings()
    embedder = load_embedder(settings.resolved_model_dir)
    engine = create_db_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            total = index_all(session, embedder, progress=lambda n: say(f"  {n} contacts embedded"))
            counts = index_counts(session, embedder.model_id)
    finally:
        engine.dispose()
    say(f"{settings.instance_name}: {counts.indexed} of {counts.contacts} contacts indexed.")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    model = sub.add_parser("model", help="install the search-by-meaning model")
    model.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="default: ~/.cache/kith-contacts/models/all-MiniLM-L6-v2",
    )
    model.add_argument("--from", dest="source", type=Path, default=None, help="copy from a folder")
    sub.add_parser("reindex", help="embed all contacts of INSTANCE_ENV_FILE's instance")
    args = parser.parse_args(argv)
    try:
        if args.command == "model":
            install_model(args.dest or default_model_dir(), source_dir=args.source)
        else:
            reindex()
    except (SetupError, ModelUnavailable, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
