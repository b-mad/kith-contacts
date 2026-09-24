# ADR-0005: Isolated instances — one database and env file per instance

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** I-01–I-09 (added), N-05 (changed), C-05 (changed)

## Context

The owner wants separate development and production environments, and
separate business and personal contact sets, all from one codebase.

## Options considered

1. **One database, `instance_id` column on every table** — one server and schema; every query must filter correctly, and one bug leaks data across instances.
2. **One schema per instance in one database** — some isolation; shared roles and `search_path` pitfalls.
3. **One database + one login role per instance on a shared PostgreSQL server** — strong isolation enforced by PostgreSQL; simple app code; separate backups.
4. **One PostgreSQL container per instance** — strongest isolation; more ports, memory and moving parts.

## Decision

Option 3. Each instance is defined by `instances/<name>.env` (name, `APP_ENV`,
color, port, `DATABASE_URL`, backup folder, default contact types). A
bootstrap command creates the database and a role that owns only that
database; `CONNECT` is revoked from `PUBLIC`. The app reads only its env file
and runs migrations for its own database at start-up.

## Consequences

- No tenant column; app code never has to filter by instance.
- Isolation is tested: a role for one instance must fail to connect to another instance's database (test marked `I-02`).
- Env files hold credentials and are git-ignored; only `instances/example.env` is committed.
- Contact types become a per-instance lookup table seeded from `CONTACT_TYPES` (C-05).
