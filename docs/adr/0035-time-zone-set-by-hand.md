# ADR-0035: Let a contact's time zone be set by hand when no address gives one

- **Status:** Proposed
- **Date:** 2026-10-23
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-26 added (Should, Phase 12); C-23 updated

## Context

A contact's local time and time zone come from their addresses (C-22, C-23). Some people are
known by time zone only: a colleague in "Central" with no address on file. Without an address
there is no local time, no good-time-to-reach hint, and nothing for the `time_zone` column in
exports (D-09). The product owner prefers the zone to come from the address when there is one
and to be able to set it only when there is not.

## Options considered

**Where the hand-set zone lives**

1. **A column on the contact.** One optional value per person; simple to show, edit, export
   and hide.
2. **A zone on an address.** Needs a made-up address to hold it, which then shows up as a
   place on the map, in directions and in "near" searches.
3. **A custom field.** Free text, so nothing could rely on it being a real zone.

**Which wins when both exist**

1. **Address always wins.** Predictable; but a state-level address (Kansas, Texas, Florida) is
   only a guess for a state that spans two zones, and a person who typed the right zone would
   be overruled by a guess.
2. **Hand-set always wins.** Lets a stale choice hide a better address.
3. **An address wins unless it is only a guess; then the hand-set zone wins.**

**Typing it**

- An IANA name from a list (America/Chicago), plus the everyday names Eastern, Central,
  Mountain and Pacific (and Arizona, Alaska, Hawaii). Abbreviations such as CST are not
  accepted: they are ambiguous (CST is also China and Cuba) and ignore daylight saving.

## Decision

Option 1 for storage and option 3 for precedence, with zones entered as IANA names or the
everyday US names.

- `contact.time_zone`, an optional IANA name (migration 0014), saved normalised
  (`central` → `America/Chicago`). Anything else is refused with a message on the field.
- The contact form has a Time zone field with a list (common US zones first) and a hint that an
  address takes its place.
- Local time (C-23) uses the first address whose zone is exact. If the only addresses are
  guesses for a multi-zone state or country, the hand-set zone is used instead; if there is none,
  the guess is shown as before. A zone used from the hand-set value says "set by hand" and is
  not marked approximate.
- Presenting mode hides the hand-set zone when Settings hides location, like the addresses
  it stands in for (P-03).
- The CSV `time_zone` column holds the zone shown on the card (address first, then hand-set).
  The JSON export carries the hand-set value as `time_zone`, and JSON import restores it. CSV
  import does not read it.
- Duplicate merge lists it as a field to choose; anonymised copies clear it.

## Consequences

- People known only by time zone get a local time and a "good time to reach" hint.
- A multi-zone state address no longer overrides a zone the person chose.
- A hand-set zone can go stale if the person moves; an exact address added later replaces it
  without any clean-up.
- vCard export and CSV import do not carry the hand-set zone yet.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-26 | Added | — |
| C-23 | "(from their first placed address)" extended with the hand-set zone | "(from their first placed address)" |
