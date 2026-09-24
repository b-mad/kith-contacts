# ADR-0007: Slack and Teams on every card; local-folder backups

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-04 (changed), M-04, I-06 (changed), N-06 (changed)

## Context

Open questions from requirements v1.0: which chat tool to link by default,
and where backups should be stored. The owner's company uses both Slack and
Microsoft Teams. Backups should go to a local folder for now.

## Decision

- Every contact card shows both a Slack action (DM link when `slack_url` is set, otherwise the handle) and a Teams action. The Teams chat link is generated from the primary email as `https://teams.microsoft.com/l/chat/0/0?users=<email>` when no explicit link is stored.
- Backups are written by `pg_dump` to a local folder set per instance by `BACKUP_DIR` (default `~/ContactsBackups/<instance>`), with 14-day retention. External or synced storage is a later change to `BACKUP_DIR` only.

## Consequences

- No per-instance setting is needed to choose a chat tool.
- A local folder does not protect against disk loss; revisit (new ADR) before relying on the business instance long-term.

## Requirements changes

| ID | Change |
| --- | --- |
| C-04 | Changed: both Slack and Teams actions shown on every card. |
| I-06, N-06 | Changed: backups go to a local folder (`BACKUP_DIR`). |
