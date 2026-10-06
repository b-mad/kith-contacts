# ADR-0028: Click a photo for a larger view with name, title and company

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-24 added (Should, Phase 3); C-09 unchanged

## Context

Photos are memory aids (C-09), but they show at 36 px in results, 64 px in the preview pane and
96 px on the card. At those sizes a face is hard to recognise, and nothing happened on click.

## Options considered

1. **Link the photo to the image file.** Leaves the app and shows no name or company.
2. **A modal dialog on the same page.** Native `<dialog>`: focus is trapped, Esc closes it, and no
   script library is needed.
3. **Enlarge in place (zoom the thumbnail).** Collides with the row's own click handling and
   can't carry a caption.

## Decision

Option 2. Each photo is wrapped in a button that opens one shared dialog (in `base.html`) showing
the stored image (up to 512 px, ADR-0011) with the contact's name, title and company beneath it.
The button carries those texts, taken from the same presentable contact the page already shows, so
presenting mode (P-02, P-03) applies and the dialog never reveals more than the page does. Close with
Esc, the Close button or a click outside. The click does not also select, preview or open the
row. A contact without a photo shows initials and has nothing to enlarge. Empty title or company
lines are left out.

## Consequences

- Works in results, the preview pane and the card with no new route or data.
- Photos are not re-encoded larger; a 512 px original is the most that can be shown.
- The photo button is a new tab stop in each result row.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-24 | Added | — |
