# ADR-0003: PostgreSQL as the data store

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** N-01 (changed), N-03, N-06 (changed), S-01–S-03, S-08, D-04 (changed)

## Context

The app needs relational data (manager chain, tags, lists), fast context
search with prefix and typo tolerance, and — per the product owner — several
isolated instances (dev/prod, business/personal). The first draft proposed
SQLite with FTS5.

## Options considered

1. **SQLite + FTS5** — zero admin, file-per-instance. Weaker fuzzy search; each instance is a loose file; harder to grow into sharing.
2. **PostgreSQL + `pg_trgm` (+ `pgvector` later)** — weighted full-text and trigram similarity in the database; one server hosts many databases; mature backup tooling. Requires a running server.
3. **Document database / browser storage** — poor fit for relational data and backups.

## Decision

Use **PostgreSQL 17**, run locally via Docker Compose, with the `pg_trgm`
extension. Search uses a weighted `tsvector` column with a GIN index plus a
`pg_trgm` similarity fallback (Phase 2). Semantic search (Phase 5) uses
`pgvector`.

## Consequences

- Docker Desktop (or a native PostgreSQL) must be running; the container uses `restart: unless-stopped`.
- Backups use `pg_dump` / `pg_restore` rather than file copies.
- Tests must run against real PostgreSQL (ADR-0006) because search behavior is database-specific.

## Requirements changes

| ID | Change |
| --- | --- |
| N-01 | Changed: PostgreSQL in Docker; one command per app instance. |
| N-06, D-04 | Changed: `pg_dump` per instance instead of copying a database file. |
