# Kith Contacts

Find people by what you remember about them, even when you forget their name.

Kith Contacts is a contact manager that runs on your own computer and opens in your browser.
Search by team, manager, project, tag, company or something from your notes ("the person who
helped with the FDA submission"), group people into lists, and go from a list to a drafted
email in two clicks. Your contacts stay on your machine.

<!-- Add a screenshot here: ![Kith Contacts](docs/images/screenshot.png) -->

## What it does

- **Search by context.** Team, manager, project, tag, company, notes, and when you last spoke
  ("who did I meet last week").
- **Search by meaning.** A small model that runs on your computer matches your description to
  notes, projects and activity. It is optional and nothing leaves your machine.
- **Lists and email.** Keep project lists and open a draft in your own mail client with every
  recipient filled in.
- **Context on the card.** Reporting chain and org chart, custom fields, an activity log,
  photos, birthdays and reminders to reconnect.
- **Places.** A map of your contacts, local time and a "near me" filter, all from data bundled
  with the app.
- **Keeping it tidy.** Duplicate finder and merge, saved searches, import and export, backups
  and restore.
- **Separate instances.** Run business, personal and test contacts side by side, each with its
  own database, port and colour.

## Privacy

- Your data is stored in a PostgreSQL database on your own computer.
- There is no telemetry, no account and no call to any outside service while the app runs.
  Maps, fonts and place data are bundled; the search model is downloaded once at install.
- The app is built for one person at a time. It has no cloud sync and no sharing.

**Not for regulated health information.** Kith Contacts is a personal contact tool. It has not
been validated for HIPAA or any other regulated use, so do not use it as a system of record for
protected health information.

## Install on Windows or Mac (no technical knowledge needed)

Download the zip from the project's releases page, unzip it and follow **Start here**, or read
the same guide here: [docs/install-guide.md](docs/install-guide.md). It needs only Docker
Desktop; everything else runs in containers.

To make the zip yourself, run `make bundle` (see below).

## Run from source

You need:

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- Docker Desktop (for PostgreSQL), or a local PostgreSQL 16+ with `pg_trgm`
- PostgreSQL client tools 17+ (`pg_dump`, `pg_restore`) for the backup and container tests;
  on macOS: `brew install libpq && brew link --force libpq`

```bash
make install        # dependencies + git hooks
make db-up          # PostgreSQL 17 on localhost:5432 (Docker)

# create the dev instance: database, role and instances/dev.env
make instance NAME=dev PORT=5180 ENV=development

make seed I=dev     # optional: ~50 made-up sample contacts (refused in production)
make model          # optional: search by meaning (one-time ~90 MB download, runs locally)
./run.sh dev        # http://localhost:5180
```

Add more instances the same way:

```bash
make instance NAME=business-prod PORT=5170 ENV=production COLOR='#1f6feb' TYPES='Employee,Customer,Vendor'
make instance NAME=personal-prod PORT=5171 ENV=production COLOR='#8250df' TYPES='Family,Friend,Service provider'
./run.sh business-prod
```

## Development

```bash
make check    # format check, lint, type check, tests with coverage (what CI runs)
make test     # tests only (needs PostgreSQL running)
make trace    # requirement -> test traceability
make fmt      # auto-format
make bundle   # build the install zip
make backup I=dev   # back up an instance (see docs/operations.md)
```

Tests create and drop their own database. Point them at another server with
`TEST_DATABASE_ADMIN_URL=postgresql://user:pass@host:5432/postgres`.

## Documentation

- Requirements, the source of truth for what the app does: [docs/requirements.md](docs/requirements.md)
- Decisions: [docs/adr/](docs/adr/README.md)
- Operations (backups, restore, upgrades): [docs/operations.md](docs/operations.md)
- How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md); rules for AI coding agents: [CLAUDE.md](CLAUDE.md)
- Reporting a vulnerability: [SECURITY.md](SECURITY.md)

## Licence

Kith Contacts is licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Bryan Madsen.
Bundled fonts, libraries and data sets keep their own licences, listed in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES); the place data includes GeoNames data (CC BY 4.0).

## Trademark

"Kith Contacts" is the name of this project. The Apache License does not give you the right to
use the name for a product of your own. If you fork the project, please give your fork a
different name, and say that it is based on Kith Contacts.
