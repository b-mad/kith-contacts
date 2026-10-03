"""Theme mode and color palette, saved per instance (A-01 to A-03, ADR-0015).

The choice is rendered by the server as ``<html data-theme data-palette>``; tokens.css
does the rest, so pages arrive already themed and need no script.

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
Palette = Literal["harbor"]  # Sage and Clay arrive with their tokens (A-02)

THEMES: Final[tuple[str, ...]] = get_args(Theme)
PALETTES: Final[tuple[str, ...]] = get_args(Palette)

THEME_CHOICES: Final[tuple[tuple[str, str, str], ...]] = (
    ("system", "System", "Match this computer's light or dark setting"),
    ("light", "Light", "Always light"),
    ("dark", "Dark", "Always dark"),
)
PALETTE_CHOICES: Final[tuple[tuple[str, str, str], ...]] = (("harbor", "Harbor", "Calm blue"),)

_KEYS: Final = ("theme", "palette")


@dataclass(frozen=True)
class Appearance:
    theme: str = "system"
    palette: str = "harbor"


DEFAULT: Final = Appearance()


def load_appearance(session: Session) -> Appearance:
    """Read the saved choice; unknown or missing values fall back to the defaults."""
    rows = dict(
        session.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(_KEYS)))
        .tuples()
        .all()
    )
    theme = rows.get("theme")
    palette = rows.get("palette")
    return Appearance(
        theme=theme if theme in THEMES else DEFAULT.theme,
        palette=palette if palette in PALETTES else DEFAULT.palette,
    )


def save_appearance(
    session: Session, *, theme: str | None = None, palette: str | None = None
) -> Appearance:
    """Upsert the given values (``None`` leaves a value unchanged) and return the result."""
    for key, value, allowed in (("theme", theme, THEMES), ("palette", palette, PALETTES)):
        if value is None:
            continue
        if value not in allowed:
            raise ValueError(f"unknown {key}: {value!r}")
        stmt = insert(AppSetting).values(key=key, value=value)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value, "updated_at": func.now()},
            )
        )
    session.flush()
    return load_appearance(session)


def current_appearance(state: State) -> Appearance:
    """The instance's choice for rendering; loads it once, defaults if the database is down."""
    cached: Appearance | None = getattr(state, "appearance", None)
    if cached is not None:
        return cached
    try:
        with state.session_factory() as session:
            cached = load_appearance(session)
    except SQLAlchemyError:
        return DEFAULT
    state.appearance = cached
    return cached


def forget_appearance(state: State) -> None:
    """Drop the cached choice, e.g. after a backup restore replaced the database."""
    state.appearance = None
