"""The public release carries its licence and credits every third-party asset (N-13, ADR-0025)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES"

#: Where a bundled asset lives, and the name its entry in THIRD_PARTY_NOTICES must carry.
#: The first rule that matches wins; an asset no rule matches fails the test, so adding a new
#: font, library or data set means adding its notice and a rule here in the same change.
ASSET_RULES: tuple[tuple[str, str], ...] = (
    (r"app/static/vendor/leaflet/.*markercluster", "Leaflet.markercluster"),
    (r"app/static/vendor/leaflet/MarkerCluster", "Leaflet.markercluster"),
    (r"app/static/vendor/leaflet/", "Leaflet"),
    (r"app/static/vendor/topojson-client", "topojson-client"),
    (r"app/static/vendor/geo/(states|counties)-", "us-atlas"),
    (r"app/static/vendor/geo/countries-", "world-atlas"),
    (r"app/static/fonts/", "Atkinson Hyperlegible Next"),
    (r"app/data/world_cities", "GeoNames"),
)
ASSET_DIRS = ("app/static/vendor", "app/static/fonts", "app/data")
#: Licence texts and the vendored-assets table are not assets themselves.
NOT_ASSETS = re.compile(r"(^|/)(LICENSE[^/]*|OFL\.txt|README\.md|__pycache__/.*|.*\.pyc)$")


def _bundled_assets() -> list[str]:
    found: list[str] = []
    for folder in ASSET_DIRS:
        for path in sorted((ROOT / folder).rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and not NOT_ASSETS.search(rel):
                found.append(rel)
    return found


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_packages() -> set[str]:
    """Every package the app needs at run time, from uv.lock (dev tools excluded)."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {_normalise(p["name"]): p for p in lock["package"]}
    root = packages["kith-contacts"]
    seen: set[str] = set()
    todo = [_normalise(d["name"]) for d in root["dependencies"]]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(_normalise(d["name"]) for d in packages[name].get("dependencies", []))
    return seen


@pytest.mark.req("N-13")
def test_licence_is_apache_2_with_a_notice() -> None:
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in licence
    assert "Version 2.0, January 2004" in licence
    assert "END OF TERMS AND CONDITIONS" in licence
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Kith Contacts" in notice
    assert "Bryan Madsen" in notice
    assert "GeoNames" in notice
    assert "Creative Commons Attribution 4.0" in notice


@pytest.mark.req("N-13")
@pytest.mark.parametrize(
    ("name", "must_mention"),
    [
        ("SECURITY.md", "Report a vulnerability"),
        ("CONTRIBUTING.md", "make check"),
        ("CODE_OF_CONDUCT.md", "Contributor Covenant"),
    ],
)
def test_project_files_exist(name: str, must_mention: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert must_mention in text


@pytest.mark.req("N-13")
def test_contributing_states_the_licence_and_the_definition_of_done() -> None:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Apache License 2.0" in text
    assert "make trace" in text
    assert '@pytest.mark.req("<ID>")' in text


@pytest.mark.req("N-13")
def test_readme_is_written_for_a_stranger() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Apache License 2.0" in text
    assert "no telemetry" in text.lower()
    assert "Not for regulated health information" in text
    assert "## Trademark" in text
    assert "Phase 5" not in text  # the old status paragraph


@pytest.mark.req("N-13")
def test_every_bundled_asset_has_a_notice() -> None:
    notices = NOTICES.read_text(encoding="utf-8")
    assets = _bundled_assets()
    assert assets, "no bundled assets found: the folders moved?"
    unmatched = [a for a in assets if not any(re.search(rx, a) for rx, _ in ASSET_RULES)]
    assert not unmatched, (
        f"no notice rule for {unmatched}: add an entry to THIRD_PARTY_NOTICES "
        "and a rule to ASSET_RULES"
    )
    for asset in assets:
        keyword = next(kw for rx, kw in ASSET_RULES if re.search(rx, asset))
        assert keyword in notices, f"{asset}: THIRD_PARTY_NOTICES does not mention {keyword}"


@pytest.mark.req("N-13")
def test_notices_point_at_licence_files_that_exist() -> None:
    notices = NOTICES.read_text(encoding="utf-8")
    cited = set(re.findall(r"`(app/static/[^`]*(?:LICENSE[^`]*|OFL\.txt))`", notices))
    assert cited, "THIRD_PARTY_NOTICES cites no licence files"
    for rel in cited:
        assert (ROOT / rel).is_file(), rel
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for folder in ASSET_DIRS
        for p in (ROOT / folder).rglob("*")
        if p.is_file() and re.search(r"(^|/)(LICENSE[^/]*|OFL\.txt)$", p.as_posix())
    }
    assert on_disk <= cited, f"licence files not cited in THIRD_PARTY_NOTICES: {on_disk - cited}"


@pytest.mark.req("N-13")
def test_notices_list_every_runtime_package() -> None:
    notices = NOTICES.read_text(encoding="utf-8")
    listed = {_normalise(m) for m in re.findall(r"^\| ([A-Za-z0-9_.-]+) \| [0-9]", notices, re.M)}
    missing = _runtime_packages() - listed
    assert not missing, f"packages missing from THIRD_PARTY_NOTICES: {sorted(missing)}"


@pytest.mark.req("N-13")
def test_notices_credit_geonames_and_the_search_model() -> None:
    notices = NOTICES.read_text(encoding="utf-8")
    assert "https://www.geonames.org" in notices
    assert "Creative Commons" in notices
    assert "all-MiniLM-L6-v2" in notices
    assert "Apache" in notices


@pytest.mark.req("N-13")
def test_settings_page_has_an_about_section() -> None:
    template = (ROOT / "app/templates/settings/index.html").read_text(encoding="utf-8")
    assert 'data-testid="about"' in template
    assert "Apache License 2.0" in template
    assert "THIRD_PARTY_NOTICES" in template


@pytest.mark.req("N-13")
def test_pyproject_declares_the_licence() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "kith-contacts"
    assert project["license"] == "Apache-2.0"
