# ADR-0034: Let people choose what an export holds, protect it, and keep a log of exports

- **Status:** Proposed
- **Date:** 2026-10-23
- **Deciders:** Bryan Madsen
- **Requirements affected:** D-09 and D-10 added (Should, Phase 3); D-03 unchanged; P-03 and P-05 applied

## Context

An export puts personal data about other people (employees, customers, vendors) into a file that
no longer has this app's protection. Privacy law and good practice ask for data minimisation
(collect and share only what is needed), safeguards for data in transit and at rest, and a record
of disclosures. Until now an export always held every field, including free-text notes, birthdays,
personal email addresses, mobile numbers and home addresses, and also private contacts, tags and
lists; nothing warned the person, and nothing recorded that it happened.

The recurring reason to export location is scheduling across time zones. That needs a time zone,
not an address.

## Options considered

**What an export holds by default**

1. **Everything, as now.** Simple; the person has to know to delete columns.
2. **A minimal default with opt-in extras.** Work contact details, reporting line, tags and lists
   and a time zone; free text, birthdays, personal contact details, state, country and street
   address are ticked on purpose.
3. **Ask every time with nothing ticked.** Safest, but tedious for the common export.

**Location**

- **Four levels** (none, time zone only, time zone with office/state/country, full address) with
  time zone only as the default. A state alone often spans several time zones, so it cannot
  replace the zone; the zone is worked out from the address already stored (C-22) and exported as
  its own `time_zone` column.
- Exporting the state and country instead of the zone. Rejected: still personal location data,
  and less useful for scheduling.

**Protecting the file**

1. **A password-protected AES-256 zip** (`pyzipper`). Opens in 7-Zip, Keka and similar tools.
   The classic ZipCrypto scheme is weak and is not used. The built-in unzip on macOS and Windows
   may not open AES zips, which the page says.
2. **PGP or age encryption.** Stronger tooling but out of reach for most recipients.
3. **No protection; rely on the disk.** Leaves the file unprotected once it is sent anywhere.

**Private records**

- Left out of every format unless "include private" is ticked, reusing the presenting-mode filter
  (P-02) so there is one definition of private. JSON stays the complete format for everything the
  person is allowed to export.

**Record of exports**

- An `export_log` table: time, format, contact count, the choices made, whether it was
  encrypted or included private records. No names, no contact data, no password.

## Decision

Option 2 for defaults, four location levels with time zone only as the default, AES-256 zip as
the optional protection, private records excluded unless included on purpose, and an export log.

- The Settings export panel is one form: format, column groups (CSV only), location, include
  private, password, and a confirmation box. A warning is always shown. Notes, birthdays, personal
  contact details, full addresses, private records, vCard and JSON need the confirmation ticked;
  a missing confirmation or a password under 10 characters returns to Settings with the reason.
- Column groups: work contact details, reporting line, tags and lists, notes and "works on",
  birthdays, personal contact details. Core columns stay. "Personal" email/phone means the labels
  P-03 treats as personal (`personal`, `home`, `mobile`).
- The old links (`/export/contacts.csv|json|vcf`) still work and use the protective defaults.
  A one-contact vCard or JSON from the card is a deliberate action on a visible contact and is
  logged but not filtered.
- Exports remain unavailable while presenting (P-05); the new route is under the same prefix.
- The password is used to make the zip and then dropped; it is not logged or stored.
- New dependencies: `pyzipper` (MIT) and `pycryptodomex` (BSD-2-Clause, public domain parts),
  both listed in THIRD_PARTY_NOTICES.

## Consequences

- The default CSV is smaller than before. Someone who relied on notes, birthdays or addresses
  in the default file has to tick them. Ticking everything gives the earlier columns plus
  `time_zone`.
- `time_zone` is a new column before the manager levels; a CSV read by header name is
  unaffected, one read by position past `birthday` is not. Importing ignores it.
- Private contacts are excluded from JSON exports by default, so a backup-style copy of
  everything needs "include private" (the database backup in Settings is unchanged).
- The log shows how often data left the app, not what it said. It lives in the instance
  database and is restored with it.
- This reduces risk; it does not make an exported file safe. A recipient can still copy it.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| D-09 | Added | — |
| D-10 | Added | — |
