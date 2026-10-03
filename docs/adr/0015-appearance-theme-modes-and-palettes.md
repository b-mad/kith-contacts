# ADR-0015: Add theme modes and three color palettes, chosen per instance and applied by the server

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** A-01–A-06 added (Phase 6); N-09 changed

## Context

The app follows the operating system's light/dark setting only; there is no way
to choose. Colors are hard-coded in three `:root` blocks and three
`prefers-color-scheme` queries in `app/static/app.css`, so a user choice cannot
override the OS. An audit against WCAG 2.2 AA (which N-09 already requires for
contrast) found:

- Dark-mode primary button: white on `#4493f8` = 3.1:1 (text needs 4.5:1).
- Form-field borders: `#d1d9e0` on white = 1.4:1; `#3d444d` on `#0d1117` = 1.9:1
  (WCAG 1.4.11 needs 3:1).
- No `color-scheme` declared, so native controls stay light in dark mode.
- Tag colors (T-04) collapse to one gray in dark mode.
- Light-only literals (`.pill.warn`, `.star`, white text on the instance bar).

The strict Content-Security-Policy (ADR-0008) forbids inline scripts, so the
usual "read localStorage in a `<head>` script" approach to avoid a flash of the
wrong theme is not available. Mockups and the reviewed plan:
"Contact Manager UI Refresh" canvas and implementation plan (2026-10-03).

## Options considered

1. **Where the choice lives**
   - Browser storage — needs JavaScript before first paint (blocked by CSP),
     flashes the wrong theme, lost when the browser changes.
   - Cookie — no flash, but browsers share cookies across ports on `localhost`,
     so every instance would get the same theme unless names are per instance.
   - **Instance database (chosen)** — a row in a new `app_setting` table; no
     flash, survives browser changes, included in backups, and lets
     business-prod and personal-prod look different.
2. **How System is resolved**
   - JavaScript `matchMedia` — needs script before paint.
   - **CSS (chosen)** — `color-scheme: light dark` plus `light-dark()` token
     values; the browser follows the OS live with no script.
3. **Typeface**
   - System UI stack — zero weight, inconsistent across platforms.
   - **Atkinson Hyperlegible Next (chosen)** — SIL Open Font License, designed
     for low-vision legibility; vendored under `app/static/fonts/` (N-04).

## Decision

1. **Theme mode** System (default) | Light | Dark, and **palette** Harbor
   (default) | Sage | Clay, plus **density** Comfortable (default) | Compact,
   are stored per instance in `app_setting` and edited on Settings ›
   Appearance (`POST /settings/appearance`, CSRF, validated by Pydantic).
   A header control switches the mode; it is a real form that works without
   JavaScript and is enhanced by `app.js` to apply instantly.
2. `base.html` renders `<html data-theme=… data-palette=… data-density=…>`.
3. All colors come from `app/static/tokens.css`: one block per palette, every
   token written once with `light-dark(light, dark)`; `color-scheme` is
   `light dark` for System and `light` or `dark` otherwise. Status colors and
   the eight tag colors are shared across palettes with separate light and
   dark values. `app.css` uses tokens only (no hex literals outside
   `tokens.css`).
4. Token values are those published with the mockups (`theme.css`); every
   palette in both modes passes WCAG 2.2 AA — 27 pairs per palette and mode,
   162 in total (text 4.5:1; field borders and focus rings 3:1).
5. **Instance header (I-03):** production shows a 4 px instance-color stripe
   and a colored instance-name chip; non-production keeps the full striped band
   and environment badge. `instance_css` also emits `--instance-on`, white or
   near-black, whichever contrasts more with the instance color.
6. Optional `DEFAULT_PALETTE` in the instance env file sets the palette for a
   new instance (I-01).
7. `prefers-reduced-motion` disables transitions; `prefers-contrast: more`
   strengthens borders and muted text.
8. The layout refresh shown in the mockups (list + preview pane, filter chips)
   is a separate, optional final step of Phase 6 and is not required by A-01–A-06.

## Consequences

- No flash of the wrong theme, no new inline script, CSP unchanged.
- `light-dark()` needs Chrome/Edge 123, Firefox 120 or Safari 17.5 — within
  N-02's "current browsers". Older browsers fall back to the light theme.
- A new `tests/test_contrast.py` parses `tokens.css` and fails the build if any
  pair drops below AA (A-04); Playwright checks System vs explicit modes with an
  emulated OS scheme; axe-core scans the main pages in all six themes.
- Adding a color now means adding a token in every palette and mode.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| A-01 | Added (Must, Phase 6): theme mode System / Light / Dark, default System. | — |
| A-02 | Added (Must, Phase 6): palettes Harbor (default), Sage, Clay, each light and dark. | — |
| A-03 | Added (Must, Phase 6): saved per instance, applied by the server, no flash, no JavaScript required. | — |
| A-04 | Added (Must, Phase 6): every palette and mode meets WCAG 2.2 AA, checked by an automated test. | — |
| A-05 | Added (Could, Phase 6): density Comfortable / Compact. | — |
| A-06 | Added (Should, Phase 6): honor reduce-motion and increase-contrast. | — |
| N-09 | Changed: "meets WCAG 2.2 AA contrast" → "meets WCAG 2.2 Level AA (contrast, focus visibility, 24 px targets)". | Keyboard-first: `/` focuses search, arrow keys move, space selects, `c` copies emails. Readable at 200% zoom; meets WCAG 2.2 AA contrast. |
