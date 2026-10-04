"""Build the zip people download to install Contact Manager (I-13, ADR-0019).

    make bundle            # dist/Contact-Manager-<version>.zip

Layout inside the zip::

    Contact Manager <version>/
        Start here.html                    the install guide (docs/install-guide.md)
        Start Contact Manager.command      macOS
        Stop Contact Manager.command
        Start Contact Manager.bat          Windows
        Stop Contact Manager.bat
        program/                           what the image is built from, plus the scripts

Only files git knows about and does not ignore are included, so instance env files,
backups and local tools can never end up in the zip. Permissions are normalised (scripts
executable, everything else read-only for others) and Windows scripts get CRLF line endings.
"""

from __future__ import annotations

import argparse
import html
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

import markdown

from app.version import app_version

ROOT = Path(__file__).resolve().parent.parent
PROGRAM_PATHS = (
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "app",
    "migrations",
    "scripts",
    "deploy/mac",
    "deploy/windows",
)
LAUNCHERS = ROOT / "deploy" / "launchers"
GUIDE = ROOT / "docs" / "install-guide.md"
EXECUTABLE = (".command", ".sh")
WINDOWS = (".bat", ".ps1")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; --ink: #1f2328; --muted: #59636e; --line: #d1d9e0;
  --bg: #ffffff; --tint: #f6f8fa; --accent: #0969da; }}
@media (prefers-color-scheme: dark) {{ :root {{ --ink: #e6edf3; --muted: #9198a1;
  --line: #3d444d; --bg: #0d1117; --tint: #151b23; --accent: #4493f8; }} }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 17px/1.6 -apple-system, "Segoe UI", system-ui, sans-serif; }}
main {{ max-width: 46rem; margin: 0 auto; padding: 2rem 1rem 4rem; }}
h1 {{ font-size: 2rem; line-height: 1.2; }}
h2 {{ margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line); }}
h3 {{ margin-top: 1.75rem; }}
a {{ color: var(--accent); }}
code {{ background: var(--tint); border: 1px solid var(--line); border-radius: 4px;
  overflow-wrap: anywhere;
  padding: 0 .3em; font-size: .9em; }}
pre {{ background: var(--tint); border: 1px solid var(--line); border-radius: 6px;
  padding: .75rem 1rem; overflow-x: auto; }}
pre code {{ border: 0; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid var(--line); padding: .5rem .6rem; text-align: left;
  vertical-align: top; }}
th {{ background: var(--tint); }}
blockquote {{ margin: 1rem 0; padding: .5rem 1rem; border-left: 4px solid var(--accent);
  background: var(--tint); }}
li + li {{ margin-top: .3rem; }}
.version {{ color: var(--muted); }}
</style>
</head>
<body>
<main>
<p class="version">Contact Manager {version}</p>
{body}
</main>
</body>
</html>
"""


def guide_html(text: str, version: str) -> str:
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    title = next(
        (line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "Start here"
    )
    return PAGE.format(title=html.escape(title), version=html.escape(version), body=body)


def tracked(paths: Iterable[str]) -> list[Path]:
    argv = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths]
    out = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        argv,
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [ROOT / name for name in out.decode().split("\0") if name]


def _info(name: str, executable: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, so the permissions below are honoured on macOS
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    return info


def _content(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in WINDOWS:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def build(dest: Path, version: str | None = None) -> Path:
    version = version or app_version()
    top = f"Contact Manager {version}"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"Contact-Manager-{version}.zip"
    files = tracked(PROGRAM_PATHS)
    if not any(f.name == "compose.yaml" for f in files):
        raise SystemExit("compose.yaml not found: run this from the repository")
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr(
            _info(f"{top}/Start here.html", False),
            guide_html(GUIDE.read_text(encoding="utf-8"), version),
        )
        for launcher in sorted(LAUNCHERS.iterdir()):
            zf.writestr(
                _info(f"{top}/{launcher.name}", launcher.suffix in EXECUTABLE),
                _content(launcher),
            )
        for path in sorted(files):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            zf.writestr(_info(f"{top}/program/{rel}", path.suffix in EXECUTABLE), _content(path))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the install zip")
    parser.add_argument("--dest", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    target = build(args.dest)
    print(f"Wrote {target} ({target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
