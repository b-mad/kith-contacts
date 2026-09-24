"""Traceability tooling (ADR-0002)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.req_trace import find_tagged_tests, main, missing_musts, parse_requirements

SAMPLE = """
| ID | Requirement | Priority | Phase |
| --- | --- | --- | --- |
| C-01 | Create a contact. | Must | 1 |
| C-02 | Old idea. **Withdrawn (ADR-0009)** | Must | 1 |
| S-07 | Saved searches. | Could | 4 |
| I-01 | Env file config. | Must | 0 |
"""


def test_parse_requirements_reads_ids_priority_phase() -> None:
    reqs = parse_requirements(SAMPLE)
    assert [(r.id, r.priority, r.phase, r.withdrawn) for r in reqs] == [
        ("C-01", "Must", 1, False),
        ("C-02", "Must", 1, True),
        ("S-07", "Could", 4, False),
        ("I-01", "Must", 0, False),
    ]


def test_missing_musts_ignores_later_phases_and_withdrawn(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text('@pytest.mark.req("I-01", "C-01")\ndef test_a(): ...\n')

    tagged = find_tagged_tests(tests_dir)
    reqs = parse_requirements(SAMPLE)

    assert tagged == {"I-01": ["tests/test_x.py"], "C-01": ["tests/test_x.py"]}
    assert missing_musts(reqs, tagged, phase=1) == []
    assert missing_musts(reqs, {}, phase=0) == ["I-01"]


def test_all_phase_0_musts_are_tested(capsys: pytest.CaptureFixture[str]) -> None:
    """Guards the definition of done: every Must due by the current phase has a test."""
    assert main(["--phase", "0", "--strict"]) == 0
    assert "untested: 0" in capsys.readouterr().out
