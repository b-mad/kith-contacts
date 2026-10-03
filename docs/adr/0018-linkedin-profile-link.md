# ADR-0018: Store a LinkedIn profile per contact as a validated link with a card action

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-18 added (Should, Phase 8)

## Context

Many contacts have a LinkedIn profile. Today it can only be kept as an extra field
(C-11), which renders as plain text, is not validated, can be hidden by presenting
mode's "private extra fields", and cannot be imported in bulk. LinkedIn lets members
download their connections as a CSV (`Connections.csv`: First Name, Last Name, URL,
Email Address, Company, Position, Connected On, after a short "Notes" preamble), so
profile links for many contacts can arrive in one import.

## Options considered

1. **Dedicated LinkedIn field** — one validated column, a LinkedIn action next to
   Email, Call, Slack and Teams, bulk import from LinkedIn's export. Covers the common
   case with the least typing. A second social network would need its own field.
2. **General "links" list per contact** (label + URL, like emails and phones) —
   flexible (GitHub, company bio, personal site); more typing for the common case, a
   new table and form rows; LinkedIn would still need special handling for a button.
3. **Auto-link URLs in extra fields** — no schema change; no validation, no button,
   no bulk import, and hidden while presenting when the field is private.

## Decision

Option 1. A nullable `contact.linkedin_url` stores the canonical
`https://www.linkedin.com/in/<name>`. Input may be the full profile URL (any
`linkedin.com` host, with or without `https://`, query or trailing slash) or just the
profile name; anything else is rejected with a clear message. The card and the search
preview show a **LinkedIn** action that opens the profile in a new tab
(`rel="noopener noreferrer"`); with none saved, a disabled action says so. While
presenting it is a work detail (shown, except in the names-only view). CSV import
recognises LinkedIn's export (skipping its preamble) and common headers ("LinkedIn",
"LinkedIn URL", "Profile URL", "URL"); a value that is not a LinkedIn profile is
dropped rather than failing the row. vCard uses `X-SOCIALPROFILE;TYPE=linkedin` and
reads LinkedIn `URL` lines; JSON and CSV exports carry the field. The search document
is unchanged (no migration rebuild).

## Consequences

- One click from any card or preview to the person's LinkedIn profile.
- Bulk-filling profiles from LinkedIn's own export.
- A general links list (option 2) can still be added later; LinkedIn would keep its
  dedicated field and button.
- The app never fetches anything from LinkedIn (N-04): the link opens in the browser.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-18 | Added (Should, Phase 8): optional LinkedIn profile per contact, validated and stored as `https://www.linkedin.com/in/<name>`; a LinkedIn action on the card and preview opens it in a new tab; CSV (including LinkedIn's Connections export), vCard and JSON carry it. | — |
