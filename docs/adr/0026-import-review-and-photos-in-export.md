# ADR-0026: Review an import page by page, choose the rows, compare duplicates, and export photos

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** D-07 added (Should, Phase 3); D-03 and I-09 clarified (the full JSON export carries photos)

## Context

Four gaps showed up when moving contacts between instances:

1. **Photos were lost.** The JSON export of a whole instance (D-03) left photos out; only the
   one-contact "Copy to another instance" file (I-09) carried them, so importing a full export
   elsewhere restored every field except the pictures.
2. **The import preview stopped at 25 rows.** Possible duplicates past the 25th could not be seen,
   so they could not be judged.
3. **All or nothing.** One checkbox, "Import possible duplicates too", decided for every duplicate
   at once; there was no way to take some rows and leave others.
4. **"Duplicate?" said nothing about the difference.** A row that repeats a stored contact exactly
   and one that carries a new phone number and a new job title looked the same.

The owner also asked how import relates to merge (C-12, ADR-0012). Today they are separate:
import creates contacts (or skips a duplicate); merge works on two contacts already stored.

## Options considered

**Where the selection lives while paging**

1. **In the form** — the preview already carries the whole file in a hidden field and re-posts it
   on "Update preview". Selected row numbers travel as one hidden field; each page submits its own
   ticks over it. No server state, works without JavaScript, nothing to expire or clean up. Every
   page change re-posts the file.
2. **Server-side stash** of the upload with a token — smaller posts, but needs storage, expiry and
   clean-up, and breaks if the server restarts mid-review.
3. **Client-side only** (all rows in the page, JavaScript pages them) — a 5,000-row file means a huge
   DOM, and the page is unusable without JavaScript.

**What import does with a duplicate**

A. **Compare and let the person choose; a ticked duplicate is added as a new contact.** Import
   never changes a stored contact. Merging stays where it is (Possible duplicates).
B. **Merge on import** — choose per row to merge into the matched contact. More powerful, but it
   needs rules for which value wins per field and writes to existing contacts from a file preview,
   which ADR-0012's snapshot-and-undo design does not yet cover for imports.

## Decision

- **Photos:** the whole-instance JSON export includes each contact's photo (already resized to at
  most 512 px, C-09). A JSON import may therefore be larger: the limit is 64 MB for JSON and stays
  5 MB for CSV and vCard. vCard export does not carry photos.
- **Review:** the preview shows 25 rows per page with First / Previous / Next / Last, a filter
  (all, ready, possible duplicates, errors) and a checkbox per valid row, with Select this page,
  Select all, Select none and Ready rows only. Option 1 for the selection. Ready rows start ticked,
  duplicates do not. Only ticked rows are imported (the old checkbox still works for a post that
  sends no selection). Importing with nothing ticked is refused.
- **Comparison:** each duplicate is compared field by field with the contact it matched (same
  email, or same name and company), or with the earlier row of the same file. Both sides are
  normalised first (phone numbers by meaning, case and spacing ignored, an address is the same place
  when street, city and postal code match). A **full match** has no difference. Otherwise a detail
  view lists every field as same, different, only in the file, or only in the stored contact.
  Only the fields the file can hold are compared (a CSV without a Tags column says nothing about
  tags). Photos are compared by presence only, since re-encoding changes the bytes.
- **Merge:** option A. A new module `app/importdiff.py` holds the comparison.

## Consequences

- Importing a full export into another instance restores photos; backups are unaffected.
- A person can review a 5,000-row file, tick exactly the rows they want and see why each duplicate
  was flagged.
- Each page change re-posts the file (up to 64 MB with photos). Acceptable for a local app; if it
  becomes a problem, option 2 can replace the hidden field without changing the screens.
- Importing a duplicate still creates a second contact; the person merges afterwards. Merge during
  import (option B) is not built and would need its own ADR.
- Follow-up candidates: photos in vCard export and import; paging on the Possible duplicates page,
  which still shows its 100 strongest pairs.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| D-07 | Added | — |
| D-03 | Clarified: the JSON export includes photos | Export all data (contacts, tags, lists) to CSV and JSON. |
| I-09 | Clarified: a whole-instance JSON export carries photos too | Move or copy a contact between instances via export/import (vCard or JSON). JSON keeps extra fields, activity, lists, photo, the keep-in-touch cadence and snooze, and private flags. |
