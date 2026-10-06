# ADR-0031: Suggest existing values in the contact form and reuse their spelling

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-25 added (Should, Phase 3); C-14 unchanged

## Context

Team, Department, Location and the type (label) of each email, phone and address are free text.
The same value is easily typed several ways ("Data Platform", "data platform", "Data  Platform"),
which splits filters (S-04, S-15), the org chart and presenting-mode label rules (P-03) into
near-duplicates. Company already avoids this (C-14): a dropdown of existing companies, and a new
name that matches an existing one ignoring case reuses its spelling. The form also already offers
existing tag and custom-field names as suggestions.

## Options considered

1. **A strict dropdown (`<select>`) with "+ Add new…" like Company.** Prevents typos, but needs a
   click-through for every new value, hides what is typed, and is clumsy for type labels where
   a new one is common.
2. **Free text with a suggestion list (`<datalist>`) and the server reusing an existing spelling
   when the case matches.** Choose from the list or type anything; no script needed; the same
   pattern the form uses for custom-field names.
3. **Suggestions only, no server rule.** Fixes only people who pick from the list.

## Decision

Option 2.

- The edit and add forms offer the values already in use as suggestions for Team, Department,
  Location, and the type of each email, phone and address. Typing narrows the list; any text is
  still accepted.
- On save, a value that matches an existing one ignoring case and extra spaces is stored with the
  existing spelling (the most used one if there are several), the way Company does (C-14). A value
  that matches nothing is kept as typed. Fixing the case of a value no one else uses still works,
  because the contact's own current value is not counted. This applies wherever contacts are
  saved: the form, imports and the API.
- The three type fields share one list and one spelling rule ("work", "home", "mobile" and so on
  are the same words for email, phone and address), most used first.
- Presenting mode applies (P-02, P-03): suggestions are built from the same filtered session, so
  private contacts and personal-label rows add nothing, and Location suggestions are left out when
  Location is hidden. "Names and companies only" offers no Team, Department or Location
  suggestions.

## Consequences

- Fewer near-duplicate teams, departments, locations and labels from typing.
- Existing near-duplicates are not merged; only new saves follow the rule. A bulk rename is a
  separate feature if wanted.
- A deliberately different capitalisation of an existing value cannot be saved; it is corrected to
  the existing one. This matches Company.
- Browser suggestion lists differ in look between browsers and are not styled by the app.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-25 | Added | — |
