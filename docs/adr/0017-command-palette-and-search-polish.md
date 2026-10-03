# ADR-0017: Add a command palette and finish the search page's keyboard and layout details

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-12 added (Phase 6); S-02, S-11, N-09 changed

## Context

The Phase 6 layout refresh (ADR-0015, step 6) built the search page's preview
pane, filter chips and highlighted matches. Reviewing it against the approved
plan and mockups left a few details unbuilt: Undo after Log or Snooze on the
Reconnect page, an overdue marker in search results, 40 px controls (44 px at
phone width), a remove × on each active filter chip, a `?` list of keyboard
shortcuts, and a 10,000-contact performance check for Reconnect. The plan's
"other improvements" listed a command palette (Ctrl/⌘ + K), common in modern
productivity tools, as the next step towards the 15-second recall goal. The
mockup also shows results as a card list rather than a table; the product
owner prefers the card list.

## Options considered

1. **Command palette over the existing search box only** — no new endpoint,
   but it can only find people and loses lists, tags, saved searches and
   actions.
2. **Command palette with its own small JSON endpoint** (`GET /palette`) that
   returns people, lists, tags and saved searches, plus page actions defined in
   the template — one entry point for everything; goes through the same
   presenting-mode session filter as every other read.
3. **Keep the results table** — column-header sorting and a header Select all;
   wide on phones.
4. **Card list** — matches the mockup; sorting moves entirely to the Sort
   control (which already offers every sort key) and Select all to a toolbar.

## Decision

Option 2 for the palette and option 4 for results. Undo after Log or Snooze
uses the existing delete-activity and snooze routes from a flash message; the
overdue marker uses the keep-in-touch due date (ADR-0016) and never relies on
color alone.

## Consequences

- One keyboard entry point (Ctrl/⌘ + K) reaches any person, list, tag, saved
  search or common action; `?` documents every shortcut.
- The palette endpoint is a GET route, so the presenting-mode canary test
  covers it automatically (ADR-0016).
- Results lose column headers; sorting is by the Sort control only, each key in
  one fixed direction as before.
- Larger controls make forms a little taller; tables of links keep their size.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-12 | Added (Should, Phase 6): command palette (Ctrl/⌘ + K) to jump to a person, list, tag or saved search, or run a common action; presenting mode applies. | — |
| S-02 | Changed: results show the matching context with the matched words highlighted. | Results rank by relevance and show the matching context (e.g. "team: Data Platform · manager: Maria Lopez"). |
| S-11 | Changed: adds Undo after Log or Snooze on Reconnect, and an overdue marker (not color alone) in search results. | **Reconnect** page and a "Due to reconnect" filter: overdue contacts first (most overdue at the top), then those due within 7 days; the count shows in the navigation (ADR-0016). |
| N-09 | Changed: adds `?` to list shortcuts, Ctrl/⌘ + K for the palette, and 40 px controls (44 px at phone width). | Keyboard-first: `/` focuses search, arrow keys move, space selects, `c` copies emails. Readable at 200% zoom; meets WCAG 2.2 Level AA, including contrast in every theme (A-04), visible focus and 24 × 24 px minimum targets (ADR-0015). |
