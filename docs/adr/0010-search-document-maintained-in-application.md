# ADR-0010: Search document maintained by the application, not database triggers

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-01 to S-05 (implementation; no requirement text changed)

## Context

The requirements' data model said the `search_vector` would be "trigger-maintained".
The document for one contact depends on five tables (contact, its manager, tags,
lists, emails), so triggers would be needed on all of them, including cascades
such as "manager renamed → refresh their reports" and "list renamed → refresh members".

## Decision

- `app/search.py` owns the document definition and `refresh_search(session, ids)`.
  Every service function that changes an input calls it (contacts, tags, lists).
  Tests assert the index follows each kind of change.
- Refresh is a single-table `UPDATE … WHERE id = ANY(:ids)` with correlated
  sub-selects; a full rebuild has no `WHERE`. An earlier self-join version was
  planned as a nested loop once table statistics went stale and took ~40 s for
  10,000 rows; this form is linear regardless of statistics.
- Ranking: `ts_rank` (length-normalized) plus a +1 boost when a query word
  matches the person's own name; AND of all words first, then OR if nothing
  matches, then trigram similarity on names (≥ 0.3) for typos.
- Migration 0002 embeds a frozen copy of the document SQL to backfill existing
  contacts. A future change to the document needs a new migration.

## Consequences

- Writes that bypass the service layer (raw SQL, imports) must call
  `refresh_search` or `refresh_all`; `CLAUDE.md` states this rule.
- Search logic is ordinary Python + SQL, easy to test and change.
