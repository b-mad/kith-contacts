# ADR-0030: Show the org chart as a Focus view and an Outline view

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-06 changed; S-16 and S-17 added (Should, Phase 3)

## Context

The org chart (S-06) draws the whole reporting tree as one nested list. With many people and
several levels it becomes a long page: every person looks alike, there is no photo, no way to find
someone, and the only way up is a breadcrumb that appears after drilling in. The largest group in
the sample data has 12 people on one level, so a classic box chart would be over 2,000 px wide.
Other products avoid this by showing one person with their surroundings (SAP focused mode, Microsoft
Org Explorer, Pigment) or by collapsing branches by default and showing counts (Creately, tree-list
charts). Photos are memory aids (C-09), and an org view is where they help most.

## Options considered

1. **Box-and-line chart (pan and zoom).** Familiar, but too wide at one level, hard to use with a
   keyboard or screen reader, and needs a drawing library (N-04).
2. **Miller columns.** One column per level; breaks down on narrow screens and for deep chains.
3. **Focus view plus an improved Outline.** One person at a time with their chain, peers and direct
   reports; an outline with real expand/collapse for scanning the whole organization. Plain HTML,
   links and `<details>`-style controls; works without a library.

## Decision

Option 3.

- **Focus view (default).** Shows the management chain as a breadcrumb with photos, the focused
  person (photo, name, title · team), their peers (same manager) as chips, and their direct reports
  as cards with photo, name, title and team. Each report card shows "N direct · M in total" and
  opens that person's Focus view. With no focus it lists the top-level leaders.
  A side pane on wide screens shows Reports to, Team, Reports and Email for the focused person.
- **Outline view.** The whole tree with a chevron per row, avatar, name, title and the
  "Direct · in total" counts; levels 1 / 2 / 3 / All, Collapse all and Expand all; a search box that
  highlights matches and opens their ancestors. Team is not shown on Outline rows. A focus icon on a
  row opens that person's Focus view.
- **Both views.** People with no manager and no reports stay out of the chart, with the existing
  footnote. Counts read "N direct · M in total" ("in team" would collide with the *team* field).
- **Photos.** Shown when a photo exists, otherwise initials, through one shared avatar macro that
  loads images lazily (`loading="lazy"`). Presenting mode applies: a hidden photo category shows
  initials, and "names and companies only" also blanks title and team. No thumbnail route is added
  now: a 512 px photo is about 51 KB against about 4.6 KB at 112 px, so 300 photos are about 15 MB
  against 1.4 MB, which lazy loading and the existing `ETag` keep acceptable. A thumbnail variant
  gets its own ADR if a page regularly loads more than about 100 photos or a first view exceeds
  about 5 MB.
- **URL.** `/org?root=<id>&view=focus|outline&levels=1|2|3|all&q=<text>`. Unknown values fall back
  to the defaults, and `/org?root=<id>` keeps working.

## Consequences

- A long or deep organization is browsed one level at a time, with the way up always visible.
- The Outline replaces the always-open nested list; the old `_node.html` partial is removed.
- Two views to test and keep in step; both are built from one tree-building function.
- Follow-up: a thumbnail route (own ADR) if the triggers above are met.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-06 | Changed | Org view: pick a manager and browse reports, up and down the chain. |
| S-16 | Added | — |
| S-17 | Added | — |
