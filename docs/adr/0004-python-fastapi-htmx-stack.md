# ADR-0004: Python, FastAPI and HTMX stack

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** N-10 (changed)

## Context

The owner has Python experience and no TypeScript experience. The UI is
mostly forms, tables and instant search, with small client-side needs
(clipboard, multi-select). Phase 5 adds local embeddings, where Python's
ecosystem is strongest.

## Options considered

1. **TypeScript** (Fastify, Drizzle, React) — richest UI tooling; new language and heavier toolchain for the owner.
2. **Python** (FastAPI, SQLAlchemy, Alembic, Jinja + HTMX + Alpine.js) — familiar language; server-rendered UI with minimal JavaScript.

## Decision

Use **Python 3.12** with FastAPI, SQLAlchemy 2.0 (typed ORM) + psycopg 3,
Alembic migrations, Pydantic / pydantic-settings, Jinja templates with HTMX
and Alpine.js (vendored, no CDN — N-04), pytest and Playwright for Python.
Dependencies are managed with `uv` and locked in `uv.lock`. Code is
formatted and linted with Ruff and type-checked with mypy (strict).

## Consequences

- One language for the whole codebase; easy for the owner to read and review.
- Highly interactive widgets (drag-and-drop, live org chart) need extra JavaScript; revisit with a new ADR if the UI outgrows HTMX.
- JavaScript libraries are vendored into `app/static/vendor/` with their version in the filename.
