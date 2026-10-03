"""Theme mode, color palette and density, saved per instance (A-01 to A-05, ADR-0015).

The choice is rendered by the server as ``<html data-theme data-palette data-density>``;
tokens.css does the rest, so pages arrive already themed and need no script.

The current choice is kept on ``app.state.appearance`` so rendering a page needs no extra
query: it is loaded on first use and replaced whenever it is saved or a backup is restored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import State

from app.models import AppSetting

Theme = Literal["system", "light", "dark"]
Palette = Literal["harbor", "sage", "clay"]  # A-02; Settings.default_palette uses the same values
Density = Literal["comfortable", "compact"]  # A-05

THEMES: Final[tuple[str, ...]] = get_args(Theme)
PALETTES: Final[tuple[str, ...]] = get_args(Palette)
DENSITIES: Final[tuple[str, ...]] = get_args(Density)

Choices = tuple[tuple[str, str, str], ...]  # (value, label, hint)

THEME_CHOICES: Final[Choices] = (
    ("system", "System", "Match this computer's light or dark setting"),
    ("light", "Light", "Always light"),
    ("dark", "Dark", "Always dark"),
)
PALETTE_CHOICES: Final[Choices] = (
    ("harbor", "Harbor", "Calm blue"),
    ("sage", "Sage", "Soft green, low glare"),
    ("clay", "Clay", "Warm terracotta"),
)
DENSITY_CHOICES: Final[Choices] = (
    ("comfortable", "Comfortable", "Roomy rows"),
    ("compact", "Compact", "More people on screen"),
)

_ALLOWED: Final[dict[str, tuple[str, ...]]] = {
    "theme": THEMES,
    "palette": PALETTES,
    "density": DENSITIES,
}


@dataclass(frozen=True)
class Appearance:
    theme: str = "system"
    palette: str = "harbor"
    density: str = "comfortable"


DEFAULT: Final = Appearance()


def load_appearance(session: Session, defaults: Appearance = DEFAULT) -> Appearance:
    """Read the saved choice; unknown or missing values fall back to ``defaults``."""
    rows = dict(
        session.execute(
            select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(_ALLOWED))
        )
        .tuples()
        .all()
    )
    theme = rows.get("theme")
    palette = rows.get("palette")
    density = rows.get("density")
    return Appearance(
        theme=theme if theme in THEMES else defaults.theme,
        palette=palette if palette in PALETTES else defaults.palette,
        density=density if density in DENSITIES else defaults.density,
    )


def save_appearance(
    session: Session,
    *,
    theme: str | None = None,
    palette: str | None = None,
    density: str | None = None,
    defaults: Appearance = DEFAULT,
) -> Appearance:
    """Upsert the given values (``None`` leaves a value unchanged) and return the result."""
    for key, value in (("theme", theme), ("palette", palette), ("density", density)):
        if value is None:
            continue
        if value not in _ALLOWED[key]:
            raise ValueError(f"unknown {key}: {value!r}")
        stmt = insert(AppSetting).values(key=key, value=value)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value, "updated_at": func.now()},
            )
        )
    session.flush()
    return load_appearance(session, defaults)


def instance_defaults(state: State) -> Appearance:
    """Defaults for this instance: DEFAULT_PALETTE from its env file (I-01), if set."""
    palette = getattr(getattr(state, "settings", None), "default_palette", DEFAULT.palette)
    return Appearance(palette=palette if palette in PALETTES else DEFAULT.palette)


def current_appearance(state: State) -> Appearance:
    """The instance's choice for rendering; loads it once, defaults if the database is down."""
    cached: Appearance | None = getattr(state, "appearance", None)
    if cached is not None:
        return cached
    defaults = instance_defaults(state)
    try:
        with state.session_factory() as session:
            cached = load_appearance(session, defaults)
    except SQLAlchemyError:
        return defaults
    state.appearance = cached
    return cached


def forget_appearance(state: State) -> None:
    """Drop the cached choice, e.g. after a backup restore replaced the database."""
    state.appearance = None
