# ADR-0009: Choose Gmail or Outlook when emailing a group; company picker with a default

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** M-02 (changed), M-03 (changed), C-14 (added); open question "default mail client" resolved

## Context

Two change requests from the product owner at the start of Phase 2:

1. He uses both Gmail and Outlook. When copying or composing to more than one
   contact he wants to choose the client, because Outlook expects addresses
   separated by semicolons and Gmail by commas.
2. When adding an employee the Company field is always blank, but employees
   almost always work for the owner's current company. Company should default,
   and should be picked from existing values with an option to add a new one,
   so spellings stay consistent (which also makes company filters and search work).

## Options considered

- **Mail client:** (a) one global setting per instance; (b) a choice at the moment
  of copying/composing, remembered per browser. (b) matches how he works across
  personal and business mail.
- **Company default:** (a) a `HOME_COMPANY` instance setting; (b) infer the most
  common company among Employee contacts. Use (a) when set, otherwise (b), so it
  works with no configuration and can be pinned when needed.
- **Company input:** free text (current) vs a dropdown of existing companies with
  "+ Add new company…". Dropdown chosen; a new name that matches an existing one
  ignoring case reuses the existing spelling.

## Decision

- When more than one contact is selected, **Copy emails** asks: *Outlook*
  (semicolon-separated) or *Gmail* (comma-separated). **Compose** offers *Gmail*,
  *Outlook on the web* and *Default mail app* (`mailto:`), with To or Cc. The last
  choice is remembered in the browser. A single contact copies without asking.
- Compose opens Gmail (`https://mail.google.com/mail/?view=cm&fs=1&to=…`) or Outlook
  on the web (`https://outlook.office.com/mail/deeplink/compose?to=…`) in a new tab.
  This is user-initiated navigation, not a runtime call by the app, so N-04 holds.
- New requirement **C-14** (Must, Phase 2): the Company field is a dropdown of
  existing companies plus "+ Add new company…"; a new Employee defaults to the
  home company (`HOME_COMPANY`, else the most common Employee company).

## Consequences

- Copy/compose logic runs in the browser so clipboard writes and new tabs happen
  inside the click (required by Safari and popup blockers); it is covered by
  Playwright tests rather than unit tests.
- New optional instance setting `HOME_COMPANY`.

## Requirements changes

| ID | Change | Old text |
| --- | --- | --- |
| M-02 | Changed | Copy emails: semicolon-separated for Outlook (comma option) |
| M-03 | Changed | Open in mail: `mailto:` link with To / Cc choice |
| C-14 | Added | — |
