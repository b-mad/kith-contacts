# ADR-0023: An offline contact map, local time per contact, and directions links

- **Status:** Accepted (2026-10-04)
- **Date:** 2026-10-04
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-22, C-23, S-13, S-14, M-06 added (Phase 12); N-04 clarified
  (map links the user clicks); data model gains place columns on `contact_address`

## Context

ADR-0021 stored addresses with ISO country and state codes as groundwork for a map and time
zones. The product owner asked for: a map of contacts at state level or finer, filtered by a
selection, a list, a tag or any search; the contact's local time and time zone on cards and in
search results; and Google Maps driving directions between two contacts, or from the device's
own location to one contact.

A real Google export: 240 contacts with addresses across 23 states; 218 addresses have a ZIP,
232 a city and state, 17 no state. 115 addresses are in states that span two time zones
(Kansas, Nebraska, Texas, Florida…), so a state alone gives the wrong zone for some of them.

N-04 rules out runtime calls to third parties. Ordinary web maps fetch tiles from a provider
on every pan, and geocoding services receive every address.

## Options considered

Map display:

1. **Choropleth of states only** — simple, offline; no detail below state level.
2. **States shaded by count, zooming to clustered points at ZIP/city level, drawn over bundled
   outlines with no street tiles** — offline, state level or finer. Chosen.
3. **A tiled street map** (OpenStreetMap, Google) — street detail, but breaks N-04 and tells
   the provider which areas are viewed.

Place data:

1. **State level only** — no data to ship; time zones wrong in split states.
2. **ZIP and city level from bundled data** — `zipcodes` (MIT; ZIP → coordinates, IANA time
   zone; data from GeoNames CC BY 4.0, USPS and unitedstateszipcodes.org) for the US, and a
   compact extract of GeoNames' cities of 15,000+ people (CC BY 4.0) for elsewhere. Chosen.
3. **A geocoding web service** — most precise, but every address leaves the computer (N-04).

Directions:

1. **Links the user clicks** (Google Maps URLs, or Apple Maps) — nothing leaves the app until
   the user chooses to go; the provider then uses the device's location when no start is
   given, so the app never asks for or sees it. Chosen.
2. **The browser's geolocation API** — the app would handle the user's location; no benefit
   over letting the maps provider do it.

## Decision

- Each address gets `latitude`, `longitude`, `time_zone` (IANA) and `place_precision`
  (`zip`, `city`, `state`, `country` or `none`) when it is saved, from offline data: US ZIP,
  then US city + state, then state (its ZIP-weighted centre and most common zone), then
  non-US city + country, then country. Existing addresses are filled in at start-up.
- Local time is shown wherever a contact appears in full (card, preview, search results),
  rendered by the server in the contact's zone and kept current in the browser, which also
  says how far ahead or behind it is from the viewer's own zone. A "good time to reach" mark
  says, in words and an icon, whether it is working hours (weekdays 9–17), the edges of the
  day (8–9, 17–21) or night/weekend there. A state-only zone in a split state says "approx."
- The map is a view of a search (`/map?…` with the same filters as `/`), of a list, a tag or a
  selection (`ids=`). It uses Leaflet (BSD-2) and Leaflet.markercluster (MIT) vendored into
  `app/static/vendor/`, with US state and county outlines from us-atlas (US Census, public
  domain; counties are fetched on first zoom past state level and drawn on a canvas) and
  country outlines from world-atlas (Natural Earth, public domain), and no tile layer. States
  are shaded by count; zooming in shows clustered points. Home, work or all addresses; a count
  of contacts that could not be placed. Presenting mode applies through `to_out`.
- "Near" filter: within N miles of a place (a city, a ZIP or a contact), computed in SQL with
  the haversine formula — no extension needed.
- Directions: on the card ("from here"), and for a selection — one contact from here, two from
  the first to the second, three to eleven as one Google Maps route (phones open at most five
  stops). The provider is a per-instance setting, Google (default) or Apple Maps; Apple Maps
  has no multi-stop routes, so routes always open in Google Maps.

## Consequences

- No street-level detail: the map shows where people are, not how to get there — directions
  hand off to Google or Apple Maps.
- GeoNames data is CC BY 4.0: the map and the help page credit it.
- New runtime dependencies: `zipcodes` (≈1 MB, prebuilt wheels for macOS, Windows, Linux) and
  `tzdata` (time zones on systems without them, e.g. Windows); a ~1 MB world-cities extract in
  `app/data/`, rebuilt by `scripts/geodata.py`.
- N-04 still holds: the browser never loads anything from outside; a directions link sends the
  addresses in it to Google or Apple only when the user clicks it, like the existing Teams and
  LinkedIn links.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-22, C-23, S-13, S-14, M-06 | Added | — |
| N-04 | Clarified: map links the user clicks are not runtime calls | — |
