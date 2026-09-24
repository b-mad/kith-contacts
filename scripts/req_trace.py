"""Requirement → test traceability report (ADR-0002).

Reads requirement IDs, priorities and phases from docs/requirements.md and
finds tests tagged ``@pytest.mark.req("ID")``.

    uv run python -m scripts.req_trace --phase 0          # report
    uv run python -m scripts.req_trace --phase 0 --strict # fail if a Must in phase <= 0 is untested
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROW = re.compile(r"^\|\s*([A-Z]-\d{2})\s*\|(.+?)\|\s*(Must|Should|Could)\s*\|\s*(\d+)\s*\|")
# Only real markers: a decorator line or a module-level ``pytestmark = pytest.mark.req(...)``.
MARK = re.compile(
    r"""^\s*(?:@|pytestmark\s*=\s*)pytest\.mark\.req\(\s*((?:["'][A-Z]-\d{2}["']\s*,?\s*)+)\)""",
    re.MULTILINE,
)
ID = re.compile(r"[A-Z]-\d{2}")


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    priority: str
    phase: int
    withdrawn: bool


def parse_requirements(markdown: str) -> list[Requirement]:
    reqs = []
    for line in markdown.splitlines():
        m = ROW.match(line)
        if m:
            text = m.group(2).strip()
            reqs.append(
                Requirement(
                    id=m.group(1),
                    text=text,
                    priority=m.group(3),
                    phase=int(m.group(4)),
                    withdrawn="Withdrawn" in text,
                )
            )
    return reqs


def find_tagged_tests(tests_dir: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(tests_dir.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for m in MARK.finditer(source):
            for req_id in ID.findall(m.group(1)):
                found.setdefault(req_id, []).append(str(path.relative_to(tests_dir.parent)))
    return found


def missing_musts(reqs: list[Requirement], tagged: dict[str, list[str]], phase: int) -> list[str]:
    return [
        r.id
        for r in reqs
        if r.priority == "Must" and r.phase <= phase and not r.withdrawn and r.id not in tagged
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Requirement traceability report")
    parser.add_argument("--phase", type=int, default=0, help="current phase (completed up to)")
    parser.add_argument("--strict", action="store_true", help="exit 1 if a due Must is untested")
    args = parser.parse_args(argv)

    reqs = parse_requirements((ROOT / "docs" / "requirements.md").read_text(encoding="utf-8"))
    tagged = find_tagged_tests(ROOT / "tests")

    print(f"{'ID':<6} {'Pri':<7} {'Ph':<3} {'Tests':<6} Files")
    for r in reqs:
        if r.phase > args.phase:
            continue
        files = sorted(set(tagged.get(r.id, [])))
        print(f"{r.id:<6} {r.priority:<7} {r.phase:<3} {len(files):<6} {', '.join(files)}")

    missing = missing_musts(reqs, tagged, args.phase)
    due = [r for r in reqs if r.phase <= args.phase and r.priority == "Must"]
    print(f"\nMust requirements due by phase {args.phase}: {len(due)}; untested: {len(missing)}")
    if missing:
        print("Untested: " + ", ".join(missing))
    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
