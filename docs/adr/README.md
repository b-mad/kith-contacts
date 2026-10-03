# Architecture Decision Records

An ADR records one significant decision: the context, the choice, and its
consequences. ADRs are how this project remembers *why* — for architecture
and for changes to [the requirements](../requirements.md).

## When to write an ADR

Write one when a change:

- adds, removes, withdraws, re-scopes or re-prioritizes a requirement in `docs/requirements.md`;
- picks or replaces a technology, library, data store or external integration;
- changes the data model in a way that is hard to reverse (dropping data, changing keys);
- changes security, privacy, backup or instance-isolation behavior;
- sets or changes a development practice everyone must follow.

No ADR is needed for bug fixes, refactors, or wording clarifications that do
not change meaning — those are logged in the requirements change log only.

## How

1. Copy `template.md` to `NNNN-short-title.md` using the next free number.
2. Fill it in with **Status: Proposed**. Link the requirement IDs it affects.
3. In the same change, update `docs/requirements.md` (bump the version, add a change-log row naming the ADR).
4. When the product owner approves, set **Status: Accepted** and add the date.
5. Never edit an accepted ADR's decision. To change it, write a new ADR that
   **supersedes** it and set the old one's status to `Superseded by ADR-NNNN`.

## Index

| ADR | Title | Status | Requirements |
| --- | --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | — |
| [0002](0002-requirements-as-versioned-source-of-truth.md) | Requirements as a versioned source of truth | Accepted | all |
| [0003](0003-postgresql-data-store.md) | PostgreSQL as the data store | Accepted | N-01, N-03, S-01–S-03, S-08 |
| [0004](0004-python-fastapi-htmx-stack.md) | Python, FastAPI and HTMX stack | Accepted | N-10 |
| [0005](0005-isolated-instances-per-database.md) | Isolated instances: one database and env file per instance | Accepted | I-01–I-09, N-05 |
| [0006](0006-testing-and-definition-of-done.md) | Testing strategy and definition of done | Accepted | N-10 |
| [0007](0007-slack-teams-and-local-backups.md) | Slack and Teams on every card; local-folder backups | Accepted | C-04, M-04, I-06, N-06 |
| [0008](0008-server-rendered-forms-csrf-and-phone-numbers.md) | Server-rendered forms, CSRF protection and phone number format | Accepted | C-01–C-08, M-04, N-04, N-05 |
| [0009](0009-mail-client-choice-and-company-picker.md) | Choose Gmail or Outlook when emailing a group; company picker with a default | Accepted | M-02, M-03, C-14 |
| [0010](0010-search-document-maintained-in-application.md) | Search document maintained by the application, not database triggers | Accepted | S-01–S-05 |
| [0011](0011-backups-import-export-and-photos.md) | Backups, import/export formats and photo storage | Accepted | D-01–D-04, I-06, I-07, N-06, C-09, L-05 |
| [0012](0012-phase-4-depth-features.md) | Custom fields, activity log, duplicate merge, saved searches and contact transfer | Accepted | C-11–C-13, S-07, T-05, L-05, I-09, S-01 |
| [0013](0013-search-by-meaning.md) | Search by meaning with a local model and in-process vectors | Accepted | S-08, N-04 |
| [0014](0014-recent-interactions-and-time-phrases.md) | Find people by when you last interacted (filter, sort and time phrases) | Accepted | S-09, S-10 |
| [0015](0015-appearance-theme-modes-and-palettes.md) | Theme modes and three color palettes, per instance, applied by the server | Accepted | A-01–A-06, N-09 |
| [0016](0016-keep-in-touch-reminders-and-presenting-mode.md) | Keep-in-touch reminders and a presenting mode that withholds private details | Accepted | C-15–C-17, S-11, P-01–P-07 |
| [0017](0017-command-palette-and-search-polish.md) | Command palette; search-page keyboard and layout details | Accepted | S-12, S-02, S-11, N-09 |
