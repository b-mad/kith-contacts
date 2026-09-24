# Contact Manager

A locally hosted, browser-based contact manager for finding people by
context — team, manager, project, tags — even when you forget their name.

- Requirements: [docs/requirements.md](docs/requirements.md)
- Decisions: [docs/adr/](docs/adr/README.md)
- Agent / contributor rules: [CLAUDE.md](CLAUDE.md)

**Status:** Phase 0 (foundation) complete.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- Docker Desktop (for PostgreSQL), or a local PostgreSQL 16+ with `pg_trgm`

## Quick start

```bash
make install        # dependencies + git hooks
make db-up          # PostgreSQL 17 on localhost:5432 (Docker)

# create the dev instance: database, role and instances/dev.env
make instance NAME=dev PORT=5180 ENV=development

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
```

Tests create and drop their own database. Point them at another server with
`TEST_DATABASE_ADMIN_URL=postgresql://user:pass@host:5432/postgres`.
