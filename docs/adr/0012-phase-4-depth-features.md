# ADR-0012: Custom fields, activity log, duplicate merge, saved searches and contact transfer (Phase 4)

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-11, C-12, C-13, S-07, T-05, L-05 (list tags), I-09 (implementation); S-01 search document extended

## Context

Phase 4 adds power-user depth. Several choices are hard to reverse (new tables,
what a merge deletes, what goes into the search document), and one of them —
merging duplicates — removes a row, which CLAUDE.md only allows with a backup.

## Options considered

1. **Custom fields as a JSONB column on `contact`** — simple, but awkward to
   validate, order, suggest field names from, or search by field.
2. **Custom fields as a `custom_field` table (chosen)** — one row per
   key/value; easy ordering, name suggestions and per-contact uniqueness.
3. **Merge by archiving the duplicate** — nothing is deleted, but the archived
   husk keeps its emails and reappears in archived searches and exports.
4. **Merge by deleting the duplicate after a full `pg_dump` (rejected)** — a
   multi-second dump per merge; needs Docker or `pg_dump` for a UI click.
5. **Merge by deleting the duplicate and keeping a JSON snapshot (chosen)** —
   fast, auditable, and the snapshot restores the person by hand if needed;
   the daily backup still covers the whole database.

## Decision

1. **Custom fields (C-11).** Table `custom_field(id, contact_id, name ≤ 50,
   value ≤ 500, sort_order)`, unique per contact on `lower(name)`. Edited as
   rows in the contact form (like phones); names suggest from names already in
   use. Values are searchable (weight C, as "name value").
2. **Activity log (C-13).** Table `activity(id, contact_id, kind, occurred_on,
   summary ≤ 2000, created_at)`, `kind` ∈ meeting, call, email, message, note.
   Shown newest first on the card with an add form (date defaults to today) and
   delete. The card shows "Last contact" from the newest non-note activity.
   Summaries are searchable (weight D) so "met at HIMSS" finds the person.
3. **Duplicates (C-12).** `/duplicates` lists candidate pairs of active
   contacts: a shared email (ignoring case), or name similarity ≥ 0.6
   (`pg_trgm`) with the same company or one company blank. "Not a duplicate"
   stores the pair in `duplicate_dismissal` so it is not suggested again.
   **Merge** shows both side by side; the user picks which contact to keep and,
   for each field where both have different values, which value wins. Emails,
   phones, tags, lists (the kept contact's role note wins), custom fields (the
   kept contact's value wins on a name clash), activities, direct reports and a
   missing photo move to the kept contact. Different notes / works-on texts are
   combined. The other contact is deleted; its full JSON snapshot is stored in
   `contact_merge(id, kept_id, merged_name, snapshot, merged_at)` and a "Merged
   with …" note is added to the kept contact's activity log.
4. **Saved searches (S-07).** Table `saved_search(id, name unique ignoring
   case, query, created_at)`. `query` is the search page's query string reduced
   to known parameters (q, type, company, team, manager, tag, list, favorites,
   archived; not sort). Saved searches appear as chips above the search box and
   are renamed and deleted on `/saved-searches`. Saving under an existing name
   updates that search.
5. **Related tags (T-05).** On a tag's results (`/?tag=X`), up to 8 tags that
   co-occur on active contacts, ranked by shared contacts then name.
6. **List tags (L-05).** Table `list_tag(list_id, tag_id)` sharing the contact
   tag vocabulary; tags are added/removed on the list page and filter the lists
   index (`/lists?tag=X`). Renaming/merging/deleting a tag also applies to
   lists. List tags do not enter contacts' search documents.
7. **Contact transfer between instances (I-09).** Instances stay isolated
   (I-02), so transfer is by file: the card offers **Export JSON** (one contact
   in the `contacts-app/1` format, including custom fields, activities, list
   memberships and the photo as base64) alongside the existing vCard. The import
   page accepts `.json` files (single-contact or full export) through the same
   preview → confirm flow, restoring those extras; unknown types fall back to
   the chosen default type; managers link by name when unique. To *move* a
   contact, import it in the target instance and archive the original.

## Consequences

- Migration 0004 adds six tables and rebuilds every search document.
- The JSON export gains `custom_fields` and `activities` per contact; readers
  of `contacts-app/1` must ignore unknown keys (the format stays `/1`).
- A merge cannot be undone with one click; the snapshot makes a manual restore
  possible and the daily backup covers the rest. CLAUDE.md is updated to allow
  merge-with-snapshot as the backup for this one operation.
- Deferred: logging one activity for several selected contacts at once, list
  tags in contact search, and the "work vs personal" type flag (needs its own
  ADR).

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-01 | Clarified: search also covers custom field values and activity summaries. | — |
| — | Data model (§6) gains `custom_field`, `activity`, `saved_search`, `list_tag`, `duplicate_dismissal`, `contact_merge`. | — |
