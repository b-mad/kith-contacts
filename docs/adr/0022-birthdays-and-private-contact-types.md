# ADR-0022: Birthdays as a partial date, birthday reminders on Reconnect, and private contact types

- **Status:** Accepted (2026-10-04)
- **Date:** 2026-10-04
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-20 and C-21 added (Should, Phase 11); P-08 added (Should,
  Phase 11); P-02 clarified (birthdays are personal); D-01, D-02, D-03, I-09 clarified
  (birthdays travel)

## Context

Birthdays could only be kept as an extra field (C-11): free text, not imported, and no
reminder. A Google Contacts export had 29 birthdays — 21 as `1980-03-14` and 8 as
`--03-14` (no year). Outlook exports `3/14/1980`, and `0/0/00` for none; vCard uses `BDAY`
(Apple writes year 1604 when the year is unknown).

Large imports (a whole family address book, a club roster) go into one contact type. Marking
each contact private (P-03) one by one is impractical.

## Options considered

Birthday storage:

1. **One text column in ISO 8601 form** — `YYYY-MM-DD`, or `--MM-DD` without a year (the form
   vCard 4 and Google already use). Fits the existing scalar-field machinery (form, merge
   choices, exports, presenting redaction); "upcoming" is a match on the last five
   characters. Chosen.
2. **Three integer columns** (month, day, optional year) — easy arithmetic, but every
   layer would need three fields for one value.
3. **A `date` column with a placeholder year** — cannot tell "no year" from a real year.

Private types:

1. **A flag on `contact_type`**, applied while presenting exactly like a private contact
   (the session-level filter and the Python checks both look at it). Chosen.
2. **Copy the flag onto every contact of the type** — simple, but a contact moved out of the
   type would stay private, and new contacts would not pick it up.

## Decision

- `contact.birthday` holds `YYYY-MM-DD` or `--MM-DD` (CHECK constraint). Typed and imported
  values are parsed: ISO, `19800314`, `--0314`, month names ("March 14", "14 Mar 1980"), and
  slashed dates, read month-first when the instance's `PHONE_REGION` writes dates that way
  (US) and day-first otherwise. Outlook's `0/0/00` means none; Apple's year 1604 means no year.
  An unreadable birthday on import is left out rather than failing the row.
- The card shows the birthday and age. **Reconnect** lists birthdays in the next 14 days
  (today first); 29 February is celebrated on 28 February in other years.
- Birthdays belong to presenting's "Personal details" category (hidden by default), so they
  vanish from cards, the API and Reconnect while presenting.
- `contact_type.is_private`: while presenting, every contact of a private type is withheld
  like a private contact (P-02, P-04), and the type itself is hidden from type lists and
  filters. Set on Settings › Contact types or Settings › Privacy.

## Consequences

- An import can be made private in one step: pick (or create) a private type under "Type for
  rows without one".
- Existing "Birthday" extra fields are left as they are; they can be copied into the new field
  by hand or by a later clean-up.
- The private-type ids are loaded with the privacy settings and refreshed when a type's flag
  changes.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-20 | Added | — |
| C-21 | Added | — |
| P-08 | Added | — |
| P-02 | Clarified (no text change): birthdays are personal | — |
| D-01, D-02, D-03, I-09 | Clarified (no text change): birthdays included | — |
