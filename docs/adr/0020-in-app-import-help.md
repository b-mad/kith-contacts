# ADR-0020: Explain the import column mapping in the app, generated from the importer's rules

- **Status:** Accepted (2026-10-04)
- **Date:** 2026-10-04
- **Deciders:** Bryan Madsen
- **Requirements affected:** D-06 added (Should, Phase 3); D-01 clarified (current Google
  Contacts export columns recognised)

## Context

The CSV import (D-01) shows one line per column with a field picker, but nothing says
which side is the file and which is the app, what each field does with a value (which
email becomes primary, how labels turn into tags, how managers are linked), or what
Google's 44-column export turns into. Users importing a Google export could not tell
what the mapping was from and to.

Checking a real Google Contacts export (2024 "Google CSV" format) also showed the
importer only knew Google's older column names ("Organization 1 - Name"), so company,
title, department and city were silently ignored, and rows for businesses (company, no
person's name) failed with "no display name".

## Options considered

1. **Help page in the app, built from the importer's own tables** (`FIELDS`,
   `FIELD_LABELS`, a new `FIELD_HELP`, and a list of Google's export columns run through
   `guess_mapping`) — the help always says what the code does; works offline (N-04).
   One more page to keep worded well.
2. **Markdown guide in `docs/`** — easy to write, but users of the app never see it,
   and it drifts from the code.
3. **Tooltips on each field picker** — close to the point of use, but no room for the
   Google walk-through, and title tooltips are invisible on touch screens.

## Decision

Option 1. An information icon on the Import page and next to "Column mapping" opens
`/import/help` (in a new tab from the preview, so the upload is not lost). Each mapping
line gets an arrow so it reads "column in your file → field". The page has a Google
section whose table is computed from the importer's rules. Google's current column
names are added to the recognised spellings, and a row with a company but no person's
name takes the company as its display name instead of failing.

## Consequences

- Adding a field or spelling to the importer updates the help automatically; a test
  makes sure every field has help text.
- The help is honest about what is not imported (birthdays, addresses, relations,
  photos, per-value phone/email labels) and suggests workarounds.
- Follow-up candidates, not decided here: use Google's per-value labels, split
  `:::` multi-value cells, map "starred" to favorite, flag duplicates by phone number.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| D-06 | Added | — |
| D-01 | Clarified (no text change): Google's current export column names are recognised; a row without a person's name uses the company as display name | — |
