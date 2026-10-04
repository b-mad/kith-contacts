# ADR-0021: Store postal addresses as structured rows with ISO country and state codes

- **Status:** Accepted (2026-10-04)
- **Date:** 2026-10-04
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-19 added (Should, Phase 10); D-01 clarified (Google's
  per-value labels, fax numbers, `:::` multi-value cells, address columns); D-02, D-03 and
  I-09 clarified (addresses travel in vCard, CSV and JSON)

## Context

A contact can only hold a free-text `location` ("Atlanta office"). Google Contacts,
Outlook and vCard all carry postal addresses — a real Google export had a street, city,
state and ZIP for 240 of 825 contacts — and they were dropped on import.

A later feature will show contacts on a map and give each contact's time-zone offset from
the user. Both need addresses that a program can read, not just display: the country and
the state as standard codes, and the city separate from the street. The same export showed
why that needs work at entry time: "United States" and "United States of America", "KS"
and "Kan", a city typed into the state field ("Raymore, MO"), and 113 addresses with a
state but no country.

The same export also showed that the importer ignored Google's own label on each email and
phone ("* Home", "Mobile", "Work Fax"), imported fax numbers as phones, and kept two values
that Google packs into one cell (`a ::: b`) as one broken entry.

## Options considered

1. **One structured address table** (`contact_address`: label, street, city, region,
   postal code, country, country code), many per contact, labelled like emails and
   phones. Country and region are normalised on save with `pycountry` (ISO 3166-1 and
   3166-2 data, offline). Fits the map and time-zone work; one more table and form rows.
2. **A single free-text address on the contact** — least work; a map would have to parse
   text, and home/work cannot be told apart for presenting mode.
3. **Geocode on save** (latitude, longitude, time zone) — what the map ultimately needs,
   but it needs an outside service or a large offline dataset (N-04). Deferred.

## Decision

Option 1. Addresses are stored as `contact_address` rows. On save the country is matched
to an ISO 3166-1 code (and shown under its standard name); the region is stored as the
state or province code when it matches the country's subdivisions (including common
abbreviations such as "Kan." and "Calif."). An address with a state but no country, whose
state belongs to the instance's `PHONE_REGION`, gets that country. Anything unrecognised
is kept as typed, with no code.

Imports read Google's per-value labels (a leading `*` marks the primary email), skip
numbers labelled as fax, and split `:::` cells into separate values. Address columns from
Google (Address 1 and 2), Outlook (Business and Home) and hand-made files map to the first
and second address; Outlook's Home/Business columns imply the label.

## Consequences

- The map and time-zone feature can group by `country_code` and `region` without parsing
  text; it will add latitude, longitude and an IANA time zone to `contact_address` (a new
  migration) and needs an offline geocoding source — an open question.
- Presenting mode treats addresses like emails and phones: one with a personal label
  (home, personal…) is withheld when "Personal emails and phones" is hidden, and all are
  withheld when "Location" is hidden.
- City, state, postal code and country join the search document (weight D), so "Olathe"
  or "KS" finds people.
- New dependency: `pycountry` (data only, no network).
- Duplicate merge, anonymised copies, vCard (ADR), CSV and JSON export and import handle
  addresses.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-19 | Added | — |
| D-01 | Clarified (no text change): per-value labels, faxes skipped, `:::` split, address columns | — |
| D-02, D-03, I-09 | Clarified (no text change): addresses included | — |
