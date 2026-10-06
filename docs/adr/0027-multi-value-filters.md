# ADR-0027: Pick several Company, Team, Tag or List values on the contacts screen

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-15 added (Should, Phase 2); S-04 and S-07 extended

## Context

The filter chips on the main contacts screen were native `<select>` elements, so only one Company,
Team, Tag or List could be chosen. Seeing a grouping such as "everyone at Acme or Beta Corp" or
"people on the Blue team or the Red team" meant running several searches.

## Options considered

**Control**

1. **Keep the selects, add a second control for extra values.** Clumsy and hard to read.
2. **A popover of checkboxes per chip.** Works by keyboard and without JavaScript (the Search
   button applies it), shows a count when several are chosen, and matches the existing chip look.
3. **A tag-input with typed tokens.** Needs more script and is weaker without JavaScript.

**Meaning of several values**

- **Any within a filter, and across filters.** Simple, but loses the ability to narrow.
- **Any within a filter, "and" across filters.** Matches how the filters already combine.
- **All required.** Wrong for Company and Team, since a person has one of each.

## Decision

- Option 2 for the control, with the Company, Team, Tag and List chips as checkbox popovers.
  Type stays a single select.
- Within one filter a contact matches **any** chosen value; different filters combine with "and".
  Tag and List also offer **"All of these"** (`tag_match=all`, `list_match=all`).
- Values are repeated query parameters (`?company=Acme&company=Beta+Corp`); old single-value URLs
  and saved searches keep working. At most 25 values per filter; blanks and repeats are dropped.
- The × on a chip clears that filter and its match mode. Saved searches keep every value and the
  match mode. The related-tags strip (T-05) shows only when exactly one tag is chosen.
- `/api/search` takes repeated `company`, `team`, `tag` and `list`, plus `tag_match` and
  `list_match`.
- The List filter moved from "More filters" to the main row, beside Tag.

## Consequences

- A grouping is one URL, so it can be bookmarked, saved (S-07) and shared.
- The browser test for the Team chip changed from `select_option` to ticking a checkbox.
- Company matching stays case-insensitive and whole-value; there is no partial match.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-15 | Added | — |
| S-04 | Company, team, tag and list take several values | Filters: contact type, company, team, manager, tag, list; combinable. |
