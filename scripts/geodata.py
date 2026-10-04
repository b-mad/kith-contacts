"""Rebuild ``app/data/world_cities.tsv.gz`` — the offline place data for addresses outside
the US (C-22, ADR-0023). US addresses use the ``zipcodes`` package instead.

Source: GeoNames "cities15000" (cities of 15,000+ people), CC BY 4.0, as packaged by
``geonamescache``. That package is large, so it is not a dependency; run with it on demand:

    uv run --with geonamescache==3.0.2 python -m scripts.geodata

Output, one city per line, tab separated and sorted (the file is deterministic):
name, Latin alternate names (;), ISO country, latitude, longitude, population, IANA time zone.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import unicodedata
from pathlib import Path

BIG_CITY = 250_000  # people
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "world_cities.tsv.gz"


def _latin(name: str) -> bool:
    """Names written in Latin letters ("Munich", "München"), not other scripts."""
    return 2 <= len(name) <= 40 and all(
        ch in " .'-" or unicodedata.name(ch, "").startswith("LATIN") for ch in name
    )


def build() -> bytes:
    import geonamescache  # type: ignore[import-not-found]  # optional, see the docstring

    path = Path(geonamescache.__file__).parent / "data" / "cities15000.json"
    cities = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for city in cities.values():
        if city["countrycode"] == "US":  # the zipcodes package covers the US in detail
            continue
        # Cities big enough to have names in other languages (Cologne, München) keep every
        # Latin-script name; smaller ones keep their shortest few.
        names = sorted(
            {a for a in city["alternatenames"] if _latin(a) and a != city["name"]},
            key=lambda a: (len(a), a),
        )
        alternates = sorted(names if city["population"] >= BIG_CITY else names[:4])
        rows.append(
            "\t".join(
                [
                    city["name"],
                    ";".join(alternates),
                    city["countrycode"],
                    f"{city['latitude']:.4f}",
                    f"{city['longitude']:.4f}",
                    str(city["population"]),
                    city["timezone"],
                ]
            )
        )
    text = "\n".join(sorted(rows)) + "\n"
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)


def main() -> None:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data) // 1024} KB, sha256 {hashlib.sha256(data).hexdigest()})")


if __name__ == "__main__":
    main()
