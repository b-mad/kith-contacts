# ADR-0011: Backups, import/export formats and photo storage (Phase 3)

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** D-01 – D-04, I-06, I-07, N-06, C-09 (implementation); L-05 list tags moved to Phase 4

## Context

Phase 3 makes the app safe for daily use: backups, import/export, and the
remaining memory aids. The app runs natively on macOS while PostgreSQL runs in
Docker, so `pg_dump` may not be installed on the host, and the app is not
guaranteed to be running at night.

## Decision

1. **Backup tool.** Backups use `pg_dump -Fc --no-owner --no-acl`; restores use
   `pg_restore --clean --if-exists --no-owner --no-acl --single-transaction`.
   `BACKUP_TOOL=auto` (default) uses a local `pg_dump` whose major version is at
   least the server's, otherwise runs the same command inside the PostgreSQL
   container (`docker compose exec`). `local` / `docker` force one.
2. **Daily backups (I-06, N-06).** While a production instance is running it
   checks at start-up and every hour; if the newest backup is older than 24 h it
   takes one, then deletes backups older than 14 days (`BACKUP_RETENTION_DAYS`).
   `make backup I=<instance>` and a macOS `launchd` example cover nights when the
   app is closed. Files: `BACKUP_DIR/<instance>_<UTC timestamp>.dump`.
3. **Restore safety.** A restore first takes a safety backup of the current
   database, then restores; production restores must be confirmed by typing the
   instance name. `make copy-to-dev FROM=<prod> TO=dev [ANONYMIZE=1]` refuses a
   production target (I-05, I-07).
4. **Exports (D-03, D-02).** CSV: one row per contact, multi-values joined with
   `; `. JSON: versioned document (`format: contacts-app/1`) with contacts,
   emails, phones, tags, lists and roles, and types — the lossless format.
   vCard 3.0 for exchange with Outlook/Google/Apple Contacts.
5. **Imports (D-01, D-02).** Upload → preview with auto-mapped columns (headers
   from Outlook and Google exports recognised) → confirm. Duplicates (same email,
   or same name + company) are flagged and skipped unless the user opts in.
   Managers are matched by name after all rows are created.
6. **Photos (C-09)** are stored in the database (`contact_photo`, resized to
   at most 512 px, re-encoded to strip EXIF), so backups contain them.
7. **L-05** (tags on lists) is a *Could*; list status already exists. List tags
   move to Phase 4 to keep Phase 3 focused on data safety.

## Consequences

- Backups work without installing PostgreSQL tools on the Mac, as long as
  Docker is running. CI installs `postgresql-client-17`.
- New dependency: Pillow (image resizing).
- Photos make the database larger; 512 px JPEGs are ~50 KB each.
