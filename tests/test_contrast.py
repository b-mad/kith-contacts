"""Every palette meets WCAG 2.2 AA in light and dark mode (A-04, ADR-0015).

Pure CSS parsing: no browser and no database. Colors come only from
app/static/tokens.css, where each token is written as light-dark(<light>, <dark>).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
TOKENS_CSS = STATIC / "tokens.css"
APP_CSS = STATIC / "app.css"

TEXT = 4.5  # WCAG 1.4.3, normal text
UI = 3.0  # WCAG 1.4.11, field borders and focus indicators

BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
TOKEN = re.compile(
    r"--([\w-]+)\s*:\s*light-dark\(\s*(#[0-9a-fA-F]{6})\s*,\s*(#[0-9a-fA-F]{6})\s*\)"
)
PALETTE = re.compile(r'data-palette="([\w-]+)"')
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

Tokens = dict[str, tuple[str, str]]

# (foreground, background, minimum ratio). Backgrounds are the surfaces each foreground sits on.
PAIRS: list[tuple[str, str, float]] = [
    *[
        (fg, bg, TEXT)
        for fg in ("fg", "muted", "accent")
        for bg in ("bg", "surface", "surface-2", "accent-soft")
    ],
    ("on-accent", "accent-fill", TEXT),
    ("on-accent", "accent-fill-hover", TEXT),
    ("border-strong", "bg", UI),
    ("border-strong", "surface", UI),
    *[("focus", bg, UI) for bg in ("bg", "surface", "accent-soft")],
    *[
        (s, bg, TEXT)
        for s in ("danger", "success", "warning")
        for bg in ("bg", "surface", f"{s}-soft")
    ],
    *[
        ("fg", f"t-{c}", TEXT)
        for c in ("red", "orange", "yellow", "green", "teal", "blue", "purple", "gray")
    ],
]


def parse_tokens(css: str) -> dict[str, Tokens]:
    """Return {palette: {token: (light, dark)}}, with shared tokens merged into every palette."""
    palettes: dict[str, Tokens] = {}
    shared: Tokens = {}
    for selector, body in BLOCK.findall(COMMENT.sub("", css)):
        tokens = {name: (light, dark) for name, light, dark in TOKEN.findall(body)}
        if not tokens:
            continue
        names = PALETTE.findall(selector)
        if names:
            for name in names:
                palettes.setdefault(name, {}).update(tokens)
        else:
            shared.update(tokens)
    return {name: {**shared, **tokens} for name, tokens in palettes.items()}


def luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


PALETTES = parse_tokens(TOKENS_CSS.read_text())


def test_contrast_formula_matches_wcag_reference_values() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.req("A-04")
def test_harbor_is_the_default_palette() -> None:
    css = COMMENT.sub("", TOKENS_CSS.read_text())
    assert re.search(r":root\s*,\s*\[data-palette=\"harbor\"\]\s*\{", css)
    assert "harbor" in PALETTES


@pytest.mark.req("A-02")
def test_three_palettes_each_define_every_token() -> None:
    assert sorted(PALETTES) == ["clay", "harbor", "sage"]
    names = {frozenset(tokens) for tokens in PALETTES.values()}
    assert len(names) == 1, "every palette must define the same tokens"


@pytest.mark.req("A-04")
@pytest.mark.parametrize("palette", sorted(PALETTES))
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_pair_meets_wcag_aa(palette: str, mode: str) -> None:
    tokens = PALETTES[palette]
    side = 0 if mode == "light" else 1
    failures = []
    for fg, bg, minimum in PAIRS:
        assert fg in tokens, f"{palette} is missing --{fg}"
        assert bg in tokens, f"{palette} is missing --{bg}"
        ratio = contrast(tokens[fg][side], tokens[bg][side])
        if ratio < minimum:
            failures.append(f"--{fg} on --{bg}: {ratio:.2f}:1 (needs {minimum}:1)")
    assert not failures, f"{palette} {mode}: " + "; ".join(failures)


@pytest.mark.req("A-04")
def test_app_css_uses_tokens_only() -> None:
    """New colors go into tokens.css, where this test can check them."""
    css = COMMENT.sub("", APP_CSS.read_text())
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == []
    assert "prefers-color-scheme" not in css


def test_parse_tokens_merges_shared_tokens_into_each_palette() -> None:
    css = """
    :root { --danger: light-dark(#111111, #eeeeee); }
    :root, :root[data-palette="a"] { --fg: light-dark(#000000, #ffffff); }
    :root[data-palette="b"] { --fg: light-dark(#222222, #dddddd); }
    """
    assert parse_tokens(css) == {
        "a": {"danger": ("#111111", "#eeeeee"), "fg": ("#000000", "#ffffff")},
        "b": {"danger": ("#111111", "#eeeeee"), "fg": ("#222222", "#dddddd")},
    }
