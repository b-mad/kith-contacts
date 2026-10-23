# ADR-0032: Find managers by tier on the contacts screen

- **Status:** Accepted (2026-10-23)
- **Date:** 2026-10-23
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-18 added (Should, Phase 3); S-04 extended

## Context

Managers are only reachable one at a time: the Manager filter (S-04) lists the direct reports of
one named person, and the org chart (S-06, S-16, S-17) is a separate screen. There is no way to
see "all the managers", or "the second layer of management", in the contacts list next to the
other filters. The data is already there: each contact has an optional manager (C-07), and the
org chart already treats a person with no active manager as the top of a reporting line.

## Options considered

**What a tier is**

1. **Depth from the top of the person's own reporting line.** The top is L0, their reports who
   manage others are L1, and so on. Matches the org chart and the request. Several separate
   lines each have an L0.
2. **Distance from one chosen root (for example the CEO).** Needs a setting, and leaves other
   lines unnumbered.
3. **A stored "level" column on each contact.** Fast to read, but it must be rewritten for a whole
   subtree whenever a manager changes, is archived or is merged, and can fall out of step.

**Who is a manager**

- **Someone with at least one active direct report.** No flag to keep in step, and it follows the
  org chart. Chosen.
- A manual "is a manager" checkbox. Another thing to maintain; can contradict the reporting lines.

**The control**

- **A checkbox popover like the Company/Team/Tag/List chips (S-15), with every box ticked at
  first.** An all-ticked chip shows everyone, so the screen looks as it did before; unticking
  narrows. A "Not a manager" box covers people who manage nobody, so "managers only" is one
  untick. Chosen.
- A single dropdown of one tier. Cannot show L1 and L2 together.

## Decision

Option 1 for tiers, computed when needed with a recursive database query, and the checkbox chip
for the control.

- The chip is **Manager tier**, with one box per tier that has a manager (L0, L1, …) and
  **Not a manager**. Every box is ticked at first. Ticking every box, or none, is no filter, and
  the boxes are then left out of the address and out of saved searches.
- Within the chip a person matches **any** ticked box; the chip combines with the other filters
  by "and" (as in ADR-0027).
- Values are repeated query parameters (`?tier=0&tier=1&tier=none`); saved searches keep them;
  `/api/search` takes repeated `manager_tier` (`0`, `1`, …, `none`) and each result carries
  `manager_tier` (empty for non-managers).
- A manager's tier is shown as an "L1 manager" pill on result cards and the full card.
- The lines are the org chart's: a person whose manager is archived, or private while
  presenting, heads a line of their own. Presenting mode's "names and companies only" shows no
  tier pill. Nothing new is stored, so there is no migration.

## Consequences

- Choosing "L0" lists the head of every reporting line, which is more than one person when the
  contacts hold several organizations.
- The recursive query runs for the filter, for the pills on each results page and to list the
  tiers in the chip; it is cheap at personal-contact sizes. If a very large instance needs it,
  caching the tiers per request is the follow-up.
- Changing someone's manager changes the tiers of their whole subtree at once, with nothing to
  repair.
- People who manage nobody have no tier. "Not a manager" is the way to list them.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-18 | Added | — |
| S-04 | Filters now include the manager tier (S-18) | Filters: contact type, company, team, manager, tag, list; combinable. Company, team, tag and list take several values (S-15). |
