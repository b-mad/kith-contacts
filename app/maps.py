"""Directions links and the maps-provider setting (M-06, ADR-0023).

Links only: nothing is sent anywhere until the user clicks one (N-04). With no starting
point, Google and Apple Maps start from the device's own location, so this app never asks
for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, Protocol
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import State

from app.addresses import lines_of
from app.models import AppSetting

Provider = Literal["google", "apple"]
PROVIDERS: Final[tuple[tuple[Provider, str, str], ...]] = (
    ("google", "Google Maps", "Directions and routes with several stops"),
    ("apple", "Apple Maps", "Directions between two places; routes still open in Google Maps"),
)
DEFAULT_PROVIDER: Final[Provider] = "google"
MAX_STOPS: Final = 11  # Google: origin + 9 waypoints + destination in a desktop browser
PHONE_STOPS: Final = 5  # Google on a phone: origin + 3 waypoints + destination
_KEY: Final = "maps.provider"


class _Address(Protocol):
    @property
    def street(self) -> str | None: ...
    @property
    def city(self) -> str | None: ...
    @property
    def region(self) -> str | None: ...
    @property
    def postal_code(self) -> str | None: ...
    @property
    def country(self) -> str | None: ...
    @property
    def country_code(self) -> str | None: ...
    @property
    def latitude(self) -> float | None: ...


def address_text(address: _Address) -> str:
    """One line a maps app can search for: "12 Elm St, Olathe, KS 66061, United States"."""
    return ", ".join(line for line in lines_of(address, "") if line)


def best_address(addresses: Sequence[_Address]) -> _Address | None:
    """The address to go to: the first one that could be placed, else the first one."""
    return next(
        (a for a in addresses if a.latitude is not None), addresses[0] if addresses else None
    )


def directions_url(stops: Sequence[str], provider: Provider = DEFAULT_PROVIDER) -> str | None:
    """1 stop: from here to it. 2: from the first to the second. 3-11: a route (Google)."""
    stops = [s for s in stops if s][:MAX_STOPS]
    if not stops:
        return None
    if provider == "apple" and len(stops) <= 2:
        params = {"daddr": stops[-1], "dirflg": "d"}
        if len(stops) == 2:
            params = {"saddr": stops[0], **params}
        return "https://maps.apple.com/?" + urlencode(params)
    query: dict[str, str] = {"api": "1", "destination": stops[-1], "travelmode": "driving"}
    if len(stops) >= 2:
        query = {"api": "1", "origin": stops[0], **{k: v for k, v in query.items() if k != "api"}}
    if len(stops) > 2:
        query["waypoints"] = "|".join(stops[1:-1])
    return "https://www.google.com/maps/dir/?" + urlencode(query)


def load_provider(session: Session) -> Provider:
    value = session.scalar(select(AppSetting.value).where(AppSetting.key == _KEY))
    return "apple" if value == "apple" else DEFAULT_PROVIDER


def save_provider(session: Session, provider: str) -> Provider:
    if provider not in {p for p, _, _ in PROVIDERS}:
        raise ValueError(f"unknown maps provider: {provider!r}")
    stmt = insert(AppSetting).values(key=_KEY, value=provider)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
    )
    session.flush()
    return load_provider(session)


def current_provider(state: State) -> Provider:
    """Cached per app, like the appearance (A-03); saving in Settings refreshes it."""
    cached: Provider | None = getattr(state, "maps_provider", None)
    if cached is None:
        try:
            with state.session_factory() as session:
                cached = load_provider(session)
        except SQLAlchemyError:  # e.g. during start-up: use the default
            return DEFAULT_PROVIDER
        state.maps_provider = cached
    return cached
