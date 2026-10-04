# Contact Manager

A locally hosted, browser-based contact manager for finding people by
context — team, manager, project, tags — even when you forget their name.

- Requirements: [docs/requirements.md](docs/requirements.md)
- Decisions: [docs/adr/](docs/adr/README.md)
- Agent / contributor rules: [CLAUDE.md](CLAUDE.md)

**Status:** Phase 5 started: **search by meaning** — ask “the person who helped with the FDA submission” and get matches from notes, projects and activity, using a model that runs on your computer (`make model` once) — and by **when you last interacted**: a Contacted filter, a Last contact column, and phrases like “who did I meet last week”. Phase 4 (depth) complete: custom fields, activity log, duplicate finder and merge, saved searches, related tags, tags on lists, and copying a contact between instances. Phase 3 brought backups, import/export, org chart, photos and admin pages. Operations guide: [docs/operations.md](docs/operations.md).

## Install on Windows or Mac (no technical knowledge needed)

Download the zip made by `make bundle`, unzip it and follow **Start here** — or read the same
guide here: [docs/install-guide.md](docs/install-guide.md). It needs only Docker Desktop;
everything else runs in containers (ADR-0019).

## Prerequisites (development)

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- Docker Desktop (for PostgreSQL), or a local PostgreSQL 16+ with `pg_trgm`
- PostgreSQL client tools 17+ (`pg_dump`, `pg_restore`) for the backup and container tests —
  macOS: `brew install libpq && brew link --force libpq`

## Quick start

```bash
make install        # dependencies + git hooks
make db-up          # PostgreSQL 17 on localhost:5432 (Docker)

# create the dev instance: database, role and instances/dev.env
make instance NAME=dev PORT=5180 ENV=development

make seed I=dev     # optional: ~50 sample contacts (refused in production)
make model          # optional: search by meaning (one-time ~90 MB download, runs locally)
./run.sh dev        # http://localhost:5180
```

Add more instances the same way — each gets its own database, login, port
and color:

```bash
make instance NAME=business-prod PORT=5170 ENV=production COLOR='#1f6feb' TYPES='Employee,Customer,Vendor'
make instance NAME=personal-prod PORT=5171 ENV=production COLOR='#8250df' TYPES='Family,Friend,Service provider'
./run.sh business-prod
```

## Development

```bash
make check    # format check, lint, type check, tests with coverage (what CI runs)
make test     # tests only (needs PostgreSQL running)
make trace    # requirement → test traceability
make fmt      # auto-format
make backup I=dev   # back up an instance (see docs/operations.md)
```

Tests create and drop their own database. Point them at another server with
`TEST_DATABASE_ADMIN_URL=postgresql://user:pass@host:5432/postgres`.
