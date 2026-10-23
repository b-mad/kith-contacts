# ADR-0033: End the CSV export with the managers above each person, one column per level

- **Status:** Proposed
- **Date:** 2026-10-23
- **Deciders:** Bryan Madsen
- **Requirements affected:** D-08 added (Should, Phase 3); D-03 unchanged

## Context

The CSV export has a `manager` column with each person's direct manager only. To see who is above
someone, or to group a spreadsheet by division or by second-level leader, the reader has to look
managers up row by row. Manager tiers (ADR-0032) already give every manager a level: L0 at the
top of a reporting line, +1 for each line below.

## Options considered

**Which managers a row lists**

1. **The chain above the person, from the top down** (L0, then L1, … up to the direct manager).
   A person at L3 has L0, L1 and L2 filled in. Reads left to right as the way down the
   organization and lines up with the tier numbers.
2. **The chain including the person.** Puts managers' own names in their own level column, which
   mixes "who manages me" with "who I am".
3. **Direct manager, then their manager, and so on, nearest first.** Columns would mean different
   levels in different rows, which is no use for sorting or filtering.

**Where the columns go and how many**

- **After the existing columns, as many as the longest chain needs.** Existing columns and the
  order of what is already exported do not move; no empty columns when nobody has a manager.
- Always a fixed number of columns. Wastes space or cuts off a deep organization.

## Decision

Option 1: after the existing columns, add `L0`, `L1`, … one per level up to the longest chain in
the export. Each cell holds the display name of the manager at that level; cells below a person's
own depth are empty.

- The numbers are the manager tiers of S-18, and the same lines apply: the climb stops at a
  manager who is archived (so a person whose manager is archived heads a line of their own).
- The existing `manager` column is unchanged. Archived people are exported as before, with the
  managers above them.
- Names are written as they are; two managers with the same display name cannot be told apart in
  the file. Cells are protected against spreadsheet formulas like every other cell.
- Importing the file again ignores `L0`, `L1`, … (they are not importable fields); the `manager`
  column still restores each person's manager (D-01).
- Only the CSV changes. The JSON export keeps its single `manager` and stays the lossless format.

## Consequences

- A spreadsheet can be sorted or pivoted by `L0` (the top of the line), `L1`, and so on.
- The header changes with the data, so a tool that reads the CSV by fixed column position should
  read by header name instead. The existing columns keep their positions.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| D-08 | Added | — |
